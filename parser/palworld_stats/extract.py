"""Transforme les saves parsées en structures propres : guildes, joueurs, Pals.

Corrèle trois sources :

* ``Level.sav`` › ``CharacterSaveParameterMap`` : niveau/exp des joueurs, et
  chaque Pal (espèce, IV, passifs, moves, rang, propriétaire, conteneur).
* ``Level.sav`` › ``GroupSaveDataMap`` : guildes (nom, niveau de base, bases,
  roster).
* ``Players/<uid>.sav`` › ``RecordData`` : compteurs par joueur (Paldeck,
  captures, technologies, boss, donjons, zones, effigies, points de statut…).
"""

from __future__ import annotations

from typing import Any

from .decode import decode_group_raw, load_level, load_player
from .pal_names import display_name, is_boss

# Noms internes (japonais) des points de statut → clés stables pour l'UI.
STATUS_POINT_NAMES = {
    "最大HP": "hp",
    "最大SP": "stamina",
    "攻撃力": "attack",
    "所持重量": "weight",
    "捕獲率": "capture_rate",
    "作業速度": "work_speed",
    "移動速度アップ": "move_speed",
    "パルスフィアホーミング": "sphere_homing",
    "空腹率低減": "hunger",
    "滑空速度": "glide_speed",
}


def _v(d: Any, *keys: str) -> Any:
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def _flat(x: Any) -> Any:
    """Déballe les emboîtements ``{"value": …}`` successifs."""
    while isinstance(x, dict) and "value" in x:
        x = x["value"]
    return x


def _hex8(uuid: Any) -> str:
    return str(uuid).replace("-", "")[:8].lower()


# Conversion coordonnées monde → carte (plage ≈ -1000..1000). Formule confirmée
# contre palworldlol/palworld-coord et vérifiée sur des bases réelles.
def _to_map(world_x: float, world_y: float) -> tuple[float, float]:
    return (world_y - 158000.0) / 459.0, (world_x + 123888.0) / 459.0


def _container_id(struct_val: Any) -> str | None:
    cid = _v(struct_val, "value", "ID", "value")
    return _hex8(cid) if cid is not None else None


# --------------------------------------------------------------------------- #
#  Pals
# --------------------------------------------------------------------------- #
def _pal_summary(sp: dict[str, Any]) -> dict[str, Any]:
    ivs = {
        "hp": _flat(_v(sp, "Talent_HP")) or 0,
        "melee": _flat(_v(sp, "Talent_Melee")) or 0,
        "shot": _flat(_v(sp, "Talent_Shot")) or 0,
        "defense": _flat(_v(sp, "Talent_Defense")) or 0,
    }
    passives = _v(sp, "PassiveSkillList", "value", "values") or []
    equip = _v(sp, "EquipWaza", "value", "values") or []
    mastered = _v(sp, "MasteredWaza", "value", "values") or []
    gender = _flat(_v(sp, "Gender"))
    species = _flat(_v(sp, "CharacterID")) or ""
    return {
        "species": species,
        "species_name": display_name(species),
        "is_boss": is_boss(species),
        "nickname": _flat(_v(sp, "NickName")),
        "gender": (gender or "").split("::")[-1] if gender else None,
        "level": _flat(_v(sp, "Level")) or 1,
        "rank": _flat(_v(sp, "Rank")) or 1,
        "rank_hp": _flat(_v(sp, "Rank_HP")) or 0,
        "rank_attack": _flat(_v(sp, "Rank_Attack")) or 0,
        "rank_defence": _flat(_v(sp, "Rank_Defence")) or 0,
        "is_lucky": bool(_flat(_v(sp, "IsRarePal"))),
        "ivs": ivs,
        "iv_total": ivs["hp"] + ivs["shot"] + ivs["defense"],
        "passives": list(passives),
        "moves": list(equip),
        "mastered_moves": list(mastered),
        "container": _hex8(_v(sp, "SlotId", "value", "ContainerId", "value", "ID", "value"))
        if _v(sp, "SlotId", "value", "ContainerId", "value", "ID", "value") is not None
        else None,
        "slot_index": _flat(_v(sp, "SlotId", "value", "SlotIndex")),
    }


# --------------------------------------------------------------------------- #
#  Joueur : compteurs de RecordData
# --------------------------------------------------------------------------- #
def _player_records(save_data: dict[str, Any]) -> dict[str, Any]:
    rd = _v(save_data, "RecordData", "value") or {}

    def lst(key: str) -> list:
        v = _v(rd, key, "value")
        return v if isinstance(v, list) else []

    tech = _v(save_data, "UnlockedRecipeTechnologyNames", "value")
    tech_list = tech.get("values") if isinstance(tech, dict) else tech
    tech_list = [str(t) for t in (tech_list or [])]
    status_points = {}
    return {
        "captures": sum(x["value"] for x in lst("PalCaptureCount")),
        "tribes_captured": _flat(_v(rd, "TribeCaptureCount")) or 0,
        "paldeck": sum(1 for x in lst("PaldeckUnlockFlag") if x["value"]),
        "technologies": len(tech_list),
        "unlocked_tech": tech_list,
        "technology_points": _flat(_v(save_data, "TechnologyPoint")) or 0,
        "boss_technology_points": _flat(_v(save_data, "bossTechnologyPoint")) or 0,
        "tower_bosses": sum(1 for x in lst("TowerBossDefeatFlag") if x["value"]),
        "field_bosses": sum(1 for x in lst("NormalBossDefeatFlag") if x["value"]),
        "dungeons": (_flat(_v(rd, "NormalDungeonClearCount")) or 0)
        + (_flat(_v(rd, "FixedDungeonClearCount")) or 0),
        "zones_explored": sum(1 for x in lst("FindAreaFlagMap") if x["value"]),
        "fast_travels": sum(1 for x in lst("FastTravelPointUnlockFlag") if x["value"]),
        "effigies": _flat(_v(rd, "RelicPossessNum")) or 0,
        "quests_completed": len(_v(save_data, "CompletedQuestArray_FullRelease", "value") or []),
        # Ticks .NET (100 ns depuis le 01/01/0001, UTC) de la dernière *connexion*
        # du joueur — pas de sa déconnexion : recoupé à la seconde près avec les
        # lignes « joined the server » du journal du serveur de jeu. Le roster de
        # guilde porte la même valeur ; la mise en forme se fait côté navigateur,
        # dans le fuseau de celui qui regarde.
        "last_online": _flat(_v(save_data, "LastOnlineDateTime")),
        "status_points": status_points,  # rempli via CharacterSaveParameterMap
        "paldeck_species": _paldeck_species(rd),
    }


def _paldeck_species(rd: dict[str, Any]) -> list[dict[str, Any]]:
    """Détail du Paldeck par espèce : espèces débloquées + nombre de captures."""
    def lst(key):
        v = _v(rd, key, "value")
        return v if isinstance(v, list) else []

    caps = {x["key"]: x["value"] for x in lst("PalCaptureCount")}
    out = []
    for x in lst("PaldeckUnlockFlag"):
        if not x["value"]:
            continue
        sp = x["key"]
        out.append({
            "species": sp,
            "species_name": display_name(sp),
            "is_boss": is_boss(sp),
            "count": caps.get(sp, 0),
        })
    out.sort(key=lambda e: (-e["count"], e["species_name"]))
    return out


def _status_points(sp: dict[str, Any], key: str) -> dict[str, int]:
    out = {}
    for entry in _v(sp, key, "value", "values") or []:
        name = _flat(_v(entry, "StatusName"))
        pts = _flat(_v(entry, "StatusPoint"))
        out[STATUS_POINT_NAMES.get(name, name)] = pts
    return out


# --------------------------------------------------------------------------- #
#  Point d'entrée
# --------------------------------------------------------------------------- #
def extract(level_raw: bytes, player_raws: dict[str, bytes]) -> dict[str, Any]:
    """Renvoie ``{"guilds": [...], "players": [...], "pals": [...]}``.

    :param level_raw: octets bruts de ``Level.sav``.
    :param player_raws: ``{uid8: octets bruts}`` des ``Players/<uid>.sav``.
    """
    level = load_level(level_raw)
    wsd = level.properties["worldSaveData"]["value"]
    cmap = wsd["CharacterSaveParameterMap"]["value"]

    players: dict[str, dict] = {}
    pals: list[dict] = []
    for entry in cmap:
        sp = (
            entry["value"]["RawData"]["value"]["object"]
            .get("SaveParameter", {})
            .get("value", {})
        )
        if _v(sp, "IsPlayer", "value"):
            uid = _hex8(_v(entry["key"], "PlayerUId", "value"))
            players[uid] = {
                "uid": uid,
                "nickname": _flat(_v(sp, "NickName")),
                "level": _flat(_v(sp, "Level")) or 1,
                "exp": _flat(_v(sp, "Exp")) or 0,
                "status_points_level": _status_points(sp, "GotStatusPointList"),
                "status_points_elixir": _status_points(sp, "GotExStatusPointList"),
                "pals_owned": 0,
                "guild_uid": None,
            }
        else:
            owner = _v(sp, "OwnerPlayerUId", "value")
            summary = _pal_summary(sp)
            summary["owner_uid"] = _hex8(owner) if owner else None
            pals.append(summary)

    for pal in pals:
        if pal["owner_uid"] in players:
            players[pal["owner_uid"]]["pals_owned"] += 1

    # Guildes. On rattache un joueur à sa guilde via le roster décodé quand il
    # est là, sinon via l'admin et les handles de personnages possédés (robuste
    # aux guildes solo comme ce serveur, où group_name == uid du seul membre).
    guilds = []
    internal_to_guild: dict[str, str] = {}  # group_id interne -> guild_uid affiché
    for entry in wsd["GroupSaveDataMap"]["value"]:
        raw = bytes(entry["value"]["RawData"]["value"]["values"])
        g = decode_group_raw(raw)
        if not g:
            continue
        # La clé du GroupSaveDataMap est l'UUID interne du groupe, dans la même
        # représentation que le group_id_belong_to des bases → lien fiable.
        internal_to_guild[_hex8(entry["key"])] = g["guild_id"]
        handle_set = set(g["handle_uids"])
        assigned = [
            uid
            for uid in players
            if uid == g["admin_uid"] or uid in handle_set or uid == g["guild_id"]
        ]
        for uid in assigned:
            players[uid]["guild_uid"] = g["guild_id"]
        # Roster : le sous-bloc décodé s'il existe, sinon les joueurs assignés.
        if g["players"]:
            members = g["players"]
        else:
            members = [
                {"uid": uid, "name": players[uid]["nickname"], "last_online": None}
                for uid in assigned
            ]
        guilds.append(
            {
                "guild_uid": g["guild_id"],
                "name": g["display_name"],
                "base_camp_level": g["base_camp_level"],
                "base_count": g["base_count"],
                "members": members,
            }
        )

    # Bases (BaseCampSaveData) : position monde → carte, rattachée à sa guilde.
    bases = []
    for entry in wsd.get("BaseCampSaveData", {}).get("value", []):
        rd = _v(entry, "value", "RawData", "value")
        if not isinstance(rd, dict) or "transform" not in rd:
            continue
        loc = _v(rd, "transform", "translation") or {}
        wx, wy = loc.get("x", 0.0), loc.get("y", 0.0)
        mx, my = _to_map(wx, wy)
        owner = _hex8(rd.get("group_id_belong_to"))
        bases.append(
            {
                "map_x": round(mx, 1),
                "map_y": round(my, 1),
                "world_x": round(wx, 1),
                "world_y": round(wy, 1),
                "guild_uid": internal_to_guild.get(owner),
            }
        )

    # Compteurs par joueur (Players/*.sav) + dernière position connue.
    for uid, raw in player_raws.items():
        if uid not in players:
            continue
        try:
            sd = load_player(raw).properties["SaveData"]["value"]
        except Exception:
            continue
        players[uid].update(_player_records(sd))
        # conteneurs équipe / boîte
        players[uid]["party_container"] = _container_id(_v(sd, "OtomoCharacterContainerId"))
        players[uid]["box_container"] = _container_id(_v(sd, "PalStorageContainerId"))
        # position (dernière déconnexion) pour la carte
        loc = _v(sd, "LastTransform", "value", "Translation", "value") or {}
        if loc:
            wx, wy = loc.get("x", 0.0), loc.get("y", 0.0)
            mx, my = _to_map(wx, wy)
            players[uid]["map_x"] = round(mx, 1)
            players[uid]["map_y"] = round(my, 1)
            players[uid]["world_x"] = round(wx, 1)
            players[uid]["world_y"] = round(wy, 1)

    return {
        "guilds": guilds,
        "players": list(players.values()),
        "pals": pals,
        "bases": bases,
    }
