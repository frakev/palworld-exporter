"""Décodage des saves Palworld au format PlM1 (Oodle/Kraken).

Palworld a migré ses saves vers un conteneur ``PlM1`` : 12 octets d'en-tête
(``uint32 uncompressed_len`` + ``uint32 compressed_len`` + magic ``b"PlM1"``)
suivis d'un flux **Oodle/Kraken**. palworld-save-tools n'accepte que l'ancien
format ``PlZ`` + zlib, d'où l'échec historique. On décompresse le flux Oodle avec
``pyooz`` (module importé sous le nom ``ooz``) puis on parse le GVAS.

Deux sous-décodeurs de palworld-save-tools 0.24.0 ont pris du retard sur le
patch actuel du jeu (quelques octets de décalage) :

* ``character`` : un trailer de 24 octets suit les propriétés → on rend le
  décodeur tolérant plutôt que de lever « EOF not reached ». On récupère quand
  même toutes les propriétés utiles (Level, IV, passifs, moves…).
* ``group`` (guildes) : ``+4`` octets inconnus après
  ``individual_character_handle_ids`` et ``+4`` avant ``base_camp_level`` → on
  fournit un décodeur manuel (``decode_group_raw``).

Tout le reste (map objects, item containers…) est laissé en octets bruts : on
ne l'active pas ici pour éviter les crashs des décodeurs périmés.
"""

from __future__ import annotations

import contextlib
import os
import struct
from typing import Any

import ooz  # pyooz : décompresseur Oodle/Kraken en binaire natif
import palworld_save_tools.rawdata.base_camp as _base_camp
import palworld_save_tools.rawdata.character as _character
from palworld_save_tools.archive import FArchiveReader
from palworld_save_tools.gvas import GvasFile
from palworld_save_tools.paltypes import (
    PALWORLD_CUSTOM_PROPERTIES,
    PALWORLD_TYPE_HINTS,
)

PLM1_MAGIC = b"PlM1"
CHAR_PROP = ".worldSaveData.CharacterSaveParameterMap.Value.RawData"
BASECAMP_PROP = ".worldSaveData.BaseCampSaveData.Value.RawData"


# --------------------------------------------------------------------------- #
#  Décompression PlM1 → GVAS
# --------------------------------------------------------------------------- #
def sav_to_gvas(raw: bytes) -> bytes:
    """Renvoie les octets GVAS décompressés d'une save ``.sav``."""
    magic = raw[8:12]
    if magic == PLM1_MAGIC:
        uncompressed_len = int.from_bytes(raw[0:4], "little")
        return ooz.decompress(raw[12:], uncompressed_len)
    # Repli sur l'ancien format zlib (PlZ) si jamais on tombe dessus.
    from palworld_save_tools.palsav import decompress_sav_to_gvas

    return decompress_sav_to_gvas(raw)[0]


# --------------------------------------------------------------------------- #
#  Décodeur « character » tolérant
# --------------------------------------------------------------------------- #
def _lenient_character_decode_bytes(parent_reader, char_bytes):
    reader = parent_reader.internal_copy(bytes(char_bytes), debug=False)
    obj = reader.properties_until_end()
    reader.read_to_end()  # on ignore le trailer (24 o) plutôt que de crasher
    return {"object": obj}


def _lenient_basecamp_decode_bytes(parent_reader, b_bytes):
    """Décode un base camp jusqu'au champ dont on a besoin (la transform monde
    et la guilde propriétaire), en ignorant le trailer ajouté par le patch."""
    r = parent_reader.internal_copy(bytes(b_bytes), debug=False)
    data = {
        "id": r.guid(),
        "name": r.fstring(),
        "state": r.byte(),
        "transform": r.ftransform(),
        "area_range": r.float(),
        "group_id_belong_to": r.guid(),
    }
    r.read_to_end()
    return data


# --------------------------------------------------------------------------- #
#  SetProperty : type de propriété inconnu de palworld-save-tools 0.24.0
# --------------------------------------------------------------------------- #
# Un patch du jeu a ajouté ``.worldSaveData.InLockerCharacterInstanceIDArray``,
# une ``SetProperty``. La lib ne connaît pas ce type et lève « Unknown type », ce
# qui faisait échouer *tout* le parse (plus aucun snapshot depuis le patch). On
# n'exploite aucune de ces données : il suffit de traverser la propriété. Son
# en-tête est celui de n'importe quel conteneur (type d'élément + guid
# optionnel), suivi de ``size`` octets de charge utile — on les saute pour
# reprendre pile au début de la propriété suivante.
_orig_property = FArchiveReader.property


def _property_with_set(self, type_name, size, path, nested_caller_path=""):
    is_custom = path in self.custom_properties and (
        path is not nested_caller_path or nested_caller_path == ""
    )
    if type_name == "SetProperty" and not is_custom:
        set_type = self.fstring()
        _id = self.optional_guid()
        self.skip(size)
        return {"id": _id, "set_type": set_type, "value": None, "type": type_name}
    return _orig_property(self, type_name, size, path, nested_caller_path)


FArchiveReader.property = _property_with_set


@contextlib.contextmanager
def _quiet():
    """palworld-save-tools écrit des avertissements « Struct type … » via
    ``print`` (types de struct inconnus, sans gravité). On les avale pour ne pas
    noyer les logs du sidecar sous des milliers de lignes à chaque parse."""
    with open(os.devnull, "w") as devnull, contextlib.redirect_stdout(devnull):
        yield


def load_level(raw: bytes) -> GvasFile:
    """Parse ``Level.sav`` avec le seul décodeur ``character`` (tolérant) actif.

    Les guildes (``GroupSaveDataMap``) restent en octets bruts et sont décodées
    par :func:`decode_group_raw`.
    """
    _character.decode_bytes = _lenient_character_decode_bytes
    _base_camp.decode_bytes = _lenient_basecamp_decode_bytes
    custom = {
        CHAR_PROP: PALWORLD_CUSTOM_PROPERTIES[CHAR_PROP],
        BASECAMP_PROP: PALWORLD_CUSTOM_PROPERTIES[BASECAMP_PROP],
    }
    with _quiet():
        return GvasFile.read(sav_to_gvas(raw), PALWORLD_TYPE_HINTS, custom)


def load_player(raw: bytes) -> GvasFile:
    """Parse un ``Players/<uid>.sav`` avec les décodeurs standards (il n'a pas
    la grosse ``CharacterSaveParameterMap``, donc pas de drift bloquant)."""
    with _quiet():
        return GvasFile.read(sav_to_gvas(raw), PALWORLD_TYPE_HINTS, PALWORLD_CUSTOM_PROPERTIES)


# --------------------------------------------------------------------------- #
#  Décodeur manuel des guildes (GroupSaveDataMap → RawData brut)
# --------------------------------------------------------------------------- #
class _Reader:
    __slots__ = ("b", "i")

    def __init__(self, b: bytes):
        self.b = b
        self.i = 0

    def take(self, n: int) -> bytes:
        v = self.b[self.i : self.i + n]
        if len(v) < n:
            raise EOFError(f"besoin de {n} octets à {self.i}, reste {len(self.b) - self.i}")
        self.i += n
        return v

    def u8(self) -> int:
        return self.take(1)[0]

    def i32(self) -> int:
        return struct.unpack("<i", self.take(4))[0]

    def i64(self) -> int:
        return struct.unpack("<q", self.take(8))[0]

    def guid(self) -> str:
        return self.take(16).hex()

    def fstr(self) -> str:
        n = self.i32()
        if n == 0:
            return ""
        if n > 0:
            return self.take(n)[:-1].decode("utf-8", "replace")
        return self.take(-2 * n)[:-2].decode("utf-16-le", "replace")


def decode_group_raw(raw_bytes: bytes) -> dict[str, Any] | None:
    """Décode le ``RawData`` brut d'une entrée ``GroupSaveDataMap`` en guilde.

    Renvoie ``None`` si l'entrée n'est pas une guilde de joueurs (groupes
    neutres/organisations sans membres). Le layout diffère de
    palworld-save-tools 0.24.0 de deux blocs de 4 octets (voir l'en-tête du
    module).
    """
    r = _Reader(raw_bytes)
    # --- Tête : la partie fiable (nom, niveau de base, nb de bases, admin). ---
    try:
        group_id_internal = r.guid()  # id interne du groupe (lié par les bases)
        group_id_name = r.fstr()  # group_name interne (= uid admin en hexa)
        n = r.i32()
        handle_uids = []
        for _ in range(n):
            handle_uids.append(r.guid()[:8].lower())  # guid du personnage possédé
            r.take(16)  # instance_id
        r.take(4)  # bloc inconnu (nouveau patch)
        r.u8()  # org_type
        nb = r.i32()
        r.take(nb * 16)  # base_ids
        r.take(4)  # bloc inconnu (nouveau patch)
        base_camp_level = r.i32()
        base_count = r.i32()
        r.take(base_count * 16)  # base_points (= bases posées)
        display_name = r.fstr()  # nom affiché (« Unnamed Guild »)
        admin = r.guid()
    except (EOFError, struct.error, UnicodeError):
        return None
    if not group_id_name:
        return None

    # --- Roster : sous-liste joueurs (layout instable selon le patch jeu). ---
    # Best-effort : si le décodage échoue, le roster sera reconstitué côté
    # extract à partir des joueurs assignés à la guilde (via handle_uids/admin).
    players = _try_decode_players(r)

    return {
        "guild_id": group_id_name[:8].lower(),
        "group_id_internal": group_id_internal[:8].lower(),
        "display_name": display_name,
        "base_camp_level": base_camp_level,
        "base_count": base_count,
        "admin_uid": admin[:8].lower(),
        "handle_uids": handle_uids,
        "players": players,
    }


def _try_decode_players(r: "_Reader") -> list[dict[str, Any]]:
    try:
        r.take(4)  # bloc inconnu
        player_count = r.i32()
        if not 0 <= player_count <= 64:
            return []
        players = []
        for _ in range(player_count):
            uid = r.guid()
            last = r.i64()
            name = r.fstr()
            players.append({"uid": uid[:8].lower(), "last_online": last, "name": name})
        return players
    except (EOFError, struct.error, UnicodeError):
        return []
