"""Arbre technologique de référence (588 entrées) + calcul débloqué / restant.

La liste maîtresse ``technologies.json`` est extraite de paldb.cc (page
« Technologies ») : nom interne, nom affiché (FR), niveau requis, coût en points,
catégorie (Structures / Objets), drapeau « antique » (points de boss) et icône.
Les totaux (1413 points normaux, 185 antiques) correspondent à l'en-tête du site.

Mise à jour dynamique : comme la table des noms de Pals, la liste peut être
rafraîchie depuis paldb via :func:`refresh_from_paldb` (bouton dans l'UI ou
rafraîchissement hebdomadaire). Le résultat est écrit dans un *overlay* JSON sur
le volume persistant (``TECH_FILE``) qui prend le pas sur la table intégrée — les
ajouts / modifications / suppressions de technos sont ainsi pris en compte sans
reconstruire l'image.

Le save d'un joueur ne contient que la *liste* des recettes débloquées
(``UnlockedRecipeTechnologyNames``). On la croise ici avec la liste maîtresse,
en insensible à la casse, pour produire le détail « débloqué vs à trouver ».
"""

from __future__ import annotations

import json as _json
import os as _os
import re as _re
import urllib.request as _url
from typing import Any

_DATA_PATH = _os.path.join(_os.path.dirname(__file__), "technologies.json")
# Overlay persistant (survit aux redémarrages) — rafraîchi depuis paldb.
_OVERLAY_PATH = _os.environ.get("TECH_FILE", "")
_SOURCE_URL = _os.environ.get("TECH_SOURCE_URL", "https://paldb.cc/fr/Technologies")

# Liste courante + index par clé minuscule. (Re)construits par _apply().
MASTER: list[dict[str, Any]] = []
_BY_KEY: dict[str, dict[str, Any]] = {}


def _apply(techs: list[dict[str, Any]]) -> None:
    global MASTER, _BY_KEY
    MASTER = techs
    _BY_KEY = {t["key"]: t for t in techs}


def _load_bundled() -> list[dict[str, Any]]:
    try:
        with open(_DATA_PATH, encoding="utf-8") as f:
            return _json.load(f)
    except (FileNotFoundError, ValueError):  # pragma: no cover
        return []


def load_overlay() -> int:
    """(Re)charge la table : overlay persistant s'il existe, sinon table intégrée.
    Renvoie le nombre d'entrées de la table active."""
    techs = None
    if _OVERLAY_PATH and _os.path.exists(_OVERLAY_PATH):
        try:
            with open(_OVERLAY_PATH, encoding="utf-8") as f:
                cand = _json.load(f)
            if isinstance(cand, list) and cand:
                techs = cand
        except (ValueError, OSError):
            techs = None
    if techs is None:
        techs = _load_bundled()
    _apply(techs)
    return len(MASTER)


# --------------------------------------------------------------------------- #
#  Rafraîchissement depuis paldb
# --------------------------------------------------------------------------- #
_ROW_RE = _re.compile(
    r'<div class="d-inline-block hoverTech ([^"]*)"[^>]*background-image: '
    r'url\(([^)]*)\)[^>]*data-hover="\?s=Technology/([^"]+)">\s*'
    r'<div class="hoverTechCost badge">(\d+)</div>\s*'
    r'<div class="hoverTechHeader">([^<]*)</div>\s*'
    r'<div class="hoverTechFooter">([^<]*)</div>'
)
_LVL_RE = _re.compile(r'width:32px;"><div>(\d+)</div>')
_CDN = "https://cdn.paldb.cc/image/"


def parse_html(html: str) -> list[dict[str, Any]]:
    """Extrait la liste des technologies depuis le HTML de la page paldb."""
    techs: list[dict[str, Any]] = []
    for col in _re.split(r'<div class="col pt-2 pb-1 border-bottom">', html)[1:]:
        m = _LVL_RE.search(col)
        if not m:
            continue
        level = int(m.group(1))
        col = col.split("</h5>")[0]
        for cls, icon, name, cost, cat, disp in _ROW_RE.findall(col):
            icon = icon.strip()
            rel = icon[len(_CDN):] if icon.startswith(_CDN) else ""
            techs.append({
                "name": name, "key": name.lower(), "display": disp.strip(),
                "category": cat.strip(), "level": level, "cost": int(cost),
                "ancient": "BossTechnology" in cls, "icon": rel,
            })
    return techs


def refresh_from_paldb() -> int:
    """Best-effort : télécharge la page Technologies de paldb, la parse et écrit
    l'overlay persistant. Renvoie le nombre d'entrées (0 si échec / injoignable,
    la table active restant alors inchangée)."""
    try:
        req = _url.Request(_SOURCE_URL, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124 Safari/537.36",
            "Accept-Language": "fr,en;q=0.8",
        })
        html = _url.urlopen(req, timeout=25).read().decode("utf-8", "replace")
        techs = parse_html(html)
    except Exception:  # noqa: BLE001 - best-effort
        return 0
    # Garde-fou : on n'écrase la table que si le parse a l'air complet.
    if len(techs) < 400:
        return 0
    if _OVERLAY_PATH:
        try:
            tmp = _OVERLAY_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                _json.dump(techs, f, ensure_ascii=False)
            _os.replace(tmp, _OVERLAY_PATH)
        except OSError:
            pass  # écriture impossible : on applique quand même en mémoire
    _apply(techs)
    return len(techs)


# --------------------------------------------------------------------------- #
#  Croisement save ↔ table maîtresse
# --------------------------------------------------------------------------- #
def breakdown(unlocked_names: list[str] | None) -> dict[str, Any]:
    """Détail de l'arbre technologique pour un joueur.

    ``unlocked_names`` : noms internes bruts issus du save. Renvoie les compteurs
    globaux (normal / antique), plus la liste complète groupée par niveau, chaque
    techno portant ``unlocked: bool`` — de quoi afficher débloqué et restant.
    """
    have = {str(n).lower() for n in (unlocked_names or [])}

    levels: dict[int, dict[str, Any]] = {}
    n_tot = n_have = a_tot = a_have = 0
    pts_tot = pts_have = apts_tot = apts_have = 0
    for t in MASTER:
        got = t["key"] in have
        row = {**t, "unlocked": got}
        lvl = levels.setdefault(
            t["level"], {"level": t["level"], "techs": [], "unlocked": 0, "total": 0}
        )
        lvl["techs"].append(row)
        lvl["total"] += 1
        lvl["unlocked"] += 1 if got else 0
        if t["ancient"]:
            a_tot += 1
            apts_tot += t["cost"]
            if got:
                a_have += 1
                apts_have += t["cost"]
        else:
            n_tot += 1
            pts_tot += t["cost"]
            if got:
                n_have += 1
                pts_have += t["cost"]

    # Recettes présentes dans le save mais absentes de la liste maîtresse
    # (mise à jour du jeu non encore reflétée) : comptées à part pour rester
    # honnête sur « débloqué » — un rafraîchissement de la table les résorbe.
    extra = sorted(n for n in have if n not in _BY_KEY)

    return {
        "total": n_tot + a_tot,
        "unlocked": n_have + a_have,
        "normal": {"total": n_tot, "unlocked": n_have,
                   "points": pts_tot, "points_unlocked": pts_have},
        "ancient": {"total": a_tot, "unlocked": a_have,
                    "points": apts_tot, "points_unlocked": apts_have},
        "levels": [levels[k] for k in sorted(levels)],
        "unmatched": extra,
    }


load_overlay()  # charge la table (overlay persistant ou intégrée) au démarrage
