"""Référentiel des compétences des Pals (actives + passives).

- **Compétences actives** : table maîtresse extraite de paldb.cc (page
  « Active_Skills ») — nom interne (``EPalWazaID::X``) → nom affiché FR, élément
  et puissance (« Force »). Bundlée dans ``active_skills.json``, rafraîchissable
  depuis paldb (overlay persistant ``SKILLS_FILE``, mise en cache, comme la table
  des technologies) pour ne pas resolliciter le site.

- **Compétences passives** : les noms internes du save sont systématiques
  (``Deffence_up3``, ``MoveSpeed_up_2``, ``ElementBoost_Dragon_1_PAL``…). paldb ne
  fournit pas de correspondance interne→FR fiable, on résout donc via une table
  FR curatée + des motifs (tier, polarité bon/mauvais), avec repli lisible.

L'enrichissement (``enrich_pal``) est fait au moment de la vue : mettre à jour la
table s'applique sans re-parser les saves.
"""

from __future__ import annotations

import json as _json
import os as _os
import re as _re
import urllib.request as _url
from typing import Any

_DATA_PATH = _os.path.join(_os.path.dirname(__file__), "active_skills.json")
_OVERLAY_PATH = _os.environ.get("SKILLS_FILE", "")
_SOURCE_URL = _os.environ.get("SKILLS_SOURCE_URL", "https://paldb.cc/fr/Active_Skills")

_WORK_DATA_PATH = _os.path.join(_os.path.dirname(__file__), "work_suitability.json")
_WORK_OVERLAY_PATH = _os.environ.get("WORK_FILE", "")
_WORK_SOURCE_URL = _os.environ.get("WORK_SOURCE_URL", "https://paldb.cc/fr/Pals")

# Métiers (aptitudes de travail) : index d'icône paldb → nom FR. L'icône est
# servie via le proxy d'icônes (comme les éléments).
WORK_NAMES: dict[int, str] = {
    0: "Allumage de feu", 1: "Arrosage", 2: "Semence", 3: "Génération d'énergie",
    4: "Artisanat", 5: "Collecte", 6: "Abattage", 7: "Extraction",
    8: "Pharmacie", 9: "Extraction de pétrole", 10: "Réfrigération",
    11: "Transport", 12: "Exploitation",
}

# Préfixes de boss/alpha à retirer pour retrouver l'espèce de base.
_SPECIES_PREFIXES = ("BOSS_", "GYM_", "RAID_", "PREDATOR_", "SUMMONBOSS_")
# Suffixes de variantes régionales : repli sur l'espèce de base si la variante
# n'a pas d'entrée propre.
_SPECIES_SUFFIXES = ("_Ice", "_Dark", "_Fire", "_Water", "_Electric", "_Ground",
                     "_Lux", "_Noct", "_Terra", "_Cryst", "_Aqua", "_Ignis")


def _work_icon(idx: int) -> str:
    return f"Pal/Texture/UI/InGame/T_icon_palwork_{idx:02d}.webp"

# Éléments : index paldb → nom FR, couleur, icône (servie via le proxy d'icônes).
ELEMENTS: dict[int, dict[str, str]] = {
    0: {"name": "Neutre", "color": "#b9c2cc"},
    1: {"name": "Feu", "color": "#f0662e"},
    2: {"name": "Eau", "color": "#3d9bf0"},
    3: {"name": "Foudre", "color": "#f0c419"},
    4: {"name": "Herbe", "color": "#38c172"},
    5: {"name": "Ténèbres", "color": "#b23fd0"},
    6: {"name": "Dragon", "color": "#7c5cff"},
    7: {"name": "Terre", "color": "#c8873f"},
    8: {"name": "Glace", "color": "#4fd0e0"},
}


def _element_icon(idx: int) -> str:
    return f"Pal/Texture/UI/InGame/T_Icon_element_s_{idx:02d}.webp"


# --------------------------------------------------------------------------- #
#  Compétences actives : table maîtresse (paldb)
# --------------------------------------------------------------------------- #
ACTIVE: dict[str, dict[str, Any]] = {}


def _apply_active(data: dict[str, dict[str, Any]]) -> None:
    global ACTIVE
    ACTIVE = data


def load_overlay() -> int:
    """(Re)charge la table active : overlay persistant s'il existe, sinon table
    intégrée. Renvoie le nombre d'entrées."""
    data = None
    if _OVERLAY_PATH and _os.path.exists(_OVERLAY_PATH):
        try:
            with open(_OVERLAY_PATH, encoding="utf-8") as f:
                cand = _json.load(f)
            if isinstance(cand, dict) and cand:
                data = cand
        except (ValueError, OSError):
            data = None
    if data is None:
        try:
            with open(_DATA_PATH, encoding="utf-8") as f:
                data = _json.load(f)
        except (FileNotFoundError, ValueError):
            data = {}
    _apply_active(data)
    return len(ACTIVE)


_ACTIVE_RE = _re.compile(
    r'data-hover="\?s=Waza%2FEPalWazaID%3A%3A([A-Za-z0-9_]+)" href="[^"]*" '
    r'class="element_color_(\d+)">([^<]+)</a>.*?Force: <span[^>]*>(\d+)</span>',
    _re.S,
)


def parse_html(html: str) -> dict[str, dict[str, Any]]:
    import html as _h
    out: dict[str, dict[str, Any]] = {}
    for name, el, fr, force in _ACTIVE_RE.findall(html):
        out[name] = {"name": _h.unescape(fr.strip()),
                     "element": int(el), "power": int(force)}
    return out


def refresh_from_paldb() -> int:
    """Best-effort : re-scrape la page Active_Skills de paldb et écrit l'overlay
    persistant. Renvoie le nombre d'entrées (0 si échec / parse trop court)."""
    try:
        req = _url.Request(_SOURCE_URL, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124 Safari/537.36",
            "Accept-Language": "fr,en;q=0.8",
        })
        html = _url.urlopen(req, timeout=25).read().decode("utf-8", "replace")
        data = parse_html(html)
    except Exception:  # noqa: BLE001
        return 0
    if len(data) < 200:
        return 0
    if _OVERLAY_PATH:
        try:
            tmp = _OVERLAY_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                _json.dump(data, f, ensure_ascii=False)
            _os.replace(tmp, _OVERLAY_PATH)
        except OSError:
            pass
    _apply_active(data)
    return len(ACTIVE)


def active_detail(waza_id: str) -> dict[str, Any]:
    """Détail d'une compétence active depuis son ``EPalWazaID::X``."""
    key = str(waza_id).split("::")[-1]
    info = ACTIVE.get(key)
    el = (info or {}).get("element", 0)
    elem = ELEMENTS.get(el, ELEMENTS[0])
    return {
        "id": key,
        "name": (info or {}).get("name") or _prettify(key),
        "power": (info or {}).get("power"),
        "element": el,
        "element_name": elem["name"],
        "element_color": elem["color"],
        "element_icon": _element_icon(el),
    }


# --------------------------------------------------------------------------- #
#  Métiers (aptitudes de travail) : table par espèce (paldb, page Pals)
# --------------------------------------------------------------------------- #
WORK: dict[str, dict[str, int]] = {}
_WORK_LC: dict[str, dict[str, int]] = {}  # index insensible à la casse


def _apply_work(data: dict[str, dict[str, int]]) -> None:
    global WORK, _WORK_LC
    WORK = data
    _WORK_LC = {k.lower(): v for k, v in data.items()}


def load_work_overlay() -> int:
    data = None
    if _WORK_OVERLAY_PATH and _os.path.exists(_WORK_OVERLAY_PATH):
        try:
            with open(_WORK_OVERLAY_PATH, encoding="utf-8") as f:
                cand = _json.load(f)
            if isinstance(cand, dict) and cand:
                data = cand
        except (ValueError, OSError):
            data = None
    if data is None:
        try:
            with open(_WORK_DATA_PATH, encoding="utf-8") as f:
                data = _json.load(f)
        except (FileNotFoundError, ValueError):
            data = {}
    _apply_work(data)
    return len(WORK)


_WORK_AVA_RE = _re.compile(r'PalIcon/Normal/T_([A-Za-z0-9_]+)_icon_normal\.webp')
_WORK_BTN_RE = _re.compile(r'palwork_0(\d)\.webp"[^>]*/>\s*(\d+)</button>')


def parse_work_html(html: str) -> dict[str, dict[str, int]]:
    avas = list(_WORK_AVA_RE.finditer(html))
    table: dict[str, dict[str, int]] = {}
    for k, m in enumerate(avas):
        intn = m.group(1)
        end = avas[k + 1].start() if k + 1 < len(avas) else len(html)
        seg = html[m.start():end]
        works: dict[str, int] = {}
        for idx, lvl in _WORK_BTN_RE.findall(seg):
            works[str(int(idx))] = max(works.get(str(int(idx)), 0), int(lvl))
        if works:
            prev = table.get(intn, {})
            for i, l in works.items():
                prev[i] = max(prev.get(i, 0), l)
            table[intn] = prev
    return table


def refresh_work_from_paldb() -> int:
    try:
        req = _url.Request(_WORK_SOURCE_URL, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124 Safari/537.36",
            "Accept-Language": "fr,en;q=0.8",
        })
        html = _url.urlopen(req, timeout=30).read().decode("utf-8", "replace")
        data = parse_work_html(html)
    except Exception:  # noqa: BLE001
        return 0
    if len(data) < 150:
        return 0
    if _WORK_OVERLAY_PATH:
        try:
            tmp = _WORK_OVERLAY_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                _json.dump(data, f, ensure_ascii=False)
            _os.replace(tmp, _WORK_OVERLAY_PATH)
        except OSError:
            pass
    _apply_work(data)
    return len(WORK)


def _work_lookup(species: str) -> dict[str, int] | None:
    """Résout l'espèce (préfixes boss + variantes) vers ses métiers."""
    s = str(species)
    up = s.upper()
    for p in _SPECIES_PREFIXES:
        if up.startswith(p):
            s = s[len(p):]
            break
    if s.lower() in _WORK_LC:
        return _WORK_LC[s.lower()]
    for suf in _SPECIES_SUFFIXES:
        if s.endswith(suf) and s[:-len(suf)].lower() in _WORK_LC:
            return _WORK_LC[s[:-len(suf)].lower()]
    return None


def work_detail(species: str) -> list[dict[str, Any]]:
    works = _work_lookup(species)
    if not works:
        return []
    out = []
    for idx_s, lvl in works.items():
        idx = int(idx_s)
        out.append({"index": idx, "name": WORK_NAMES.get(idx, f"Métier {idx}"),
                    "level": lvl, "icon": _work_icon(idx)})
    out.sort(key=lambda w: (-w["level"], w["index"]))
    return out


# --------------------------------------------------------------------------- #
#  Compétences passives : résolution FR (curatée + motifs)
# --------------------------------------------------------------------------- #
_ELEMENT_FR = {
    "Normal": "Neutre", "Fire": "Feu", "Aqua": "Eau", "Thunder": "Foudre",
    "Leaf": "Herbe", "Dark": "Ténèbres", "Dragon": "Dragon", "Earth": "Terre",
    "Ice": "Glace",
}

# Passifs « nommés » : interne exact → (nom FR, bon?).
_PASSIVE_NAMED = {
    "Legend": ("Légende", True), "Rare": ("Chanceux", True),
    "Noukin": ("Musclé", True), "Alien": ("Idiosyncrasique", True),
    "NightOwl": ("Couche-tard", True), "Nocturnal": ("Nocturne", True),
    "NonKilling": ("Pacifiste", None),
    "PAL_ALLAttack_up1": ("Combatif", True), "PAL_ALLAttack_up2": ("Musclé", True),
    "PAL_ALLAttack_up3": ("Dieu de la guerre", True),
    "PAL_ALLAttack_down1": ("Chétif", False), "PAL_ALLAttack_down2": ("Malingre", False),
    "Deffence_up1": ("Endurci", True), "Deffence_up2": ("Robuste", True),
    "Deffence_up2_2": ("Robuste", True), "Deffence_up3": ("Corps de diamant", True),
    "Deffence_down1": ("Fragile", False), "Deffence_down2": ("Coquille d'œuf", False),
    "MoveSpeed_up_1": ("Agile", True), "MoveSpeed_up_2": ("Coureur", True),
    "MoveSpeed_up_3": ("Sprinteur", True),
    "CraftSpeed_up1": ("Ouvrier", True), "CraftSpeed_up2": ("Artisan", True),
    "CraftSpeed_up3": ("Maîtrise exceptionnelle", True),
    "CraftSpeed_down1": ("Lambin", False), "CraftSpeed_down2": ("Fainéant", False),
    "Stamina_Up_1": ("Endurant", True), "Stamina_Up_2": ("Marathonien", True),
    "Stamina_Down_1": ("Essoufflé", False),
    "SwimSpeed_up_1": ("Nageur", True), "SwimSpeed_up_2": ("As de la nage", True),
    "SwimSpeed_up_3": ("Roi des vagues", True),
    "CoolTimeReduction_Up_1": ("Ondes cérébrales", True),
    "CoolTimeReduction_Up_2": ("Éclair de génie", True),
    "CoolTimeReduction_Down_1": ("Tête en l'air", False),
    "AutoHPRegeneRate_Passive": ("Régénérateur", True),
    "ReloadSpeedUp_Passive": ("Rechargement rapide", True),
    "PlayerSP_DecreaseRate_Passive": ("Économe", True),
    "PAL_Sanity_Up_1": ("Placide", True), "PAL_Sanity_Up_2": ("Serein", True),
    "PAL_Sanity_Down_1": ("Anxieux", False), "PAL_Sanity_Down_2": ("Instable", False),
    "PAL_FullStomach_Up_1": ("Gros appétit", False), "PAL_FullStomach_Up_2": ("Glouton", False),
    "PAL_FullStomach_Down_1": ("Petit mangeur", True), "PAL_FullStomach_Down_2": ("Diététique", True),
    "PAL_conceited": ("Prétentieux", None), "PAL_masochist": ("Masochiste", None),
    "PAL_sadist": ("Sadique", None), "PAL_oraora": ("Brute", True),
    "PAL_rude": ("Impoli", None), "PAL_CorporateSlave": ("Bourreau de travail", True),
    "TrainerATK_UP_1": ("Avant-garde", True), "TrainerDEF_UP_1": ("Stratège défensif", True),
    "TrainerWorkSpeed_UP_1": ("Contremaître", True),
    "TrainerLogging_up1": ("Bûcheron", True), "TrainerMining_up1": ("Mineur", True),
    "SalePrice_Up_1": ("Marchand", True), "SalePrice_Up_2": ("Négociant", True),
    "SalePrice_Down_1": ("Camelote", False),
    "SelfDeathAddItemDrop_up_2": ("Corne d'abondance", True),
    "SelfDeathAddItemDrop_up_3": ("Trésor vivant", True),
    "MutationPal_Immortal": ("Immortalité", True),
    "MutationPal_Mutant": ("Idiosyncrasique", True),
}

_TIER_RE = _re.compile(r"_?(up|down)_?([123])?(?:_\d)?(?:_PAL)?$", _re.I)


def _prettify(s: str) -> str:
    s = _re.sub(r"^EPalWazaID::", "", s)
    s = _re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    return s.replace("_", " ").strip()


def passive_detail(pid: str) -> dict[str, Any]:
    """Détail FR d'un passif : nom, tier (1-3), polarité (bon/mauvais/neutre)."""
    raw = str(pid)
    # 1) affinité / résistance élémentaire
    m = _re.match(r"Element(Boost|Resist)_([A-Za-z]+)_(\d)_PAL$", raw)
    if m:
        kind, el, tier = m.groups()
        elfr = _ELEMENT_FR.get(el, el)
        name = (f"Affinité {elfr}" if kind == "Boost" else f"Résistance {elfr}")
        return {"id": raw, "name": name, "tier": int(tier), "good": True}
    # 2) surclassement de métier (WorkSuitabilityAddRank_X_N)
    m = _re.match(r"WorkSuitabilityAddRank_([A-Za-z]+)_(\d)$", raw)
    if m:
        return {"id": raw, "name": f"Aptitude {m.group(1)}", "tier": int(m.group(2)), "good": True}
    # 3) table nommée
    if raw in _PASSIVE_NAMED:
        fr, good = _PASSIVE_NAMED[raw]
        tier = 0
        mt = _re.search(r"([123])(?:_\w+)?$", raw)
        if mt:
            tier = int(mt.group(1))
        return {"id": raw, "name": fr, "tier": tier, "good": good}
    # 4) motif générique up/down avec tier
    good = None
    tier = 0
    mt = _TIER_RE.search(raw)
    if mt:
        good = mt.group(1).lower() == "up"
        tier = int(mt.group(2) or 1)
    return {"id": raw, "name": _prettify(raw), "tier": tier, "good": good}


# --------------------------------------------------------------------------- #
#  Enrichissement d'un Pal
# --------------------------------------------------------------------------- #
def enrich_pal(pal: dict[str, Any]) -> None:
    """Ajoute au Pal ``moves_detail`` (actives équipées + maîtrisées) et
    ``passives_detail``. In place."""
    equipped = pal.get("moves") or []
    mastered = [m for m in (pal.get("mastered_moves") or []) if m not in equipped]
    pal["moves_detail"] = [{**active_detail(m), "equipped": True} for m in equipped]
    pal["mastered_detail"] = [{**active_detail(m), "equipped": False} for m in mastered]
    pal["passives_detail"] = [passive_detail(p) for p in (pal.get("passives") or [])]
    pal["work"] = work_detail(pal.get("species") or "")


load_overlay()       # table des compétences actives (overlay persistant ou intégrée)
load_work_overlay()  # table des métiers (overlay persistant ou intégrée)
