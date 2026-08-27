#!/usr/bin/env python3
"""Régénère la table de noms d'espèces Pal depuis le wiki (best-effort).

Le wiki (palworld.wiki.gg) expose la correspondance sous forme de modèles
``{{i|NomAffiché|NomInterne}}`` dans le wikitext brut. On les extrait et on
écrit un JSON ``{interne: affiché}`` qui sert d'**overlay** : déposé dans le
volume partagé (``/shared/pal_names.json``), il surcharge la table intégrée
sans rebuild d'image (voir palworld_stats/pal_names.py).

Usage :
    python tools/fetch_pal_names.py [chemin_sortie.json]

À relancer après une mise à jour de contenu du jeu. Si le format du wiki
change, ce script échoue proprement et la table intégrée continue de servir.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request

WIKI_URL = "https://palworld.wiki.gg/wiki/Pals_/_Internal_names?action=raw"
# {{i|Chikipi|ChickenPal}} -> (affiché, interne)
PAT = re.compile(r"\{\{i\|([^|}]+)\|([^|}]+)\}\}")


def fetch() -> dict[str, str]:
    req = urllib.request.Request(WIKI_URL, headers={"User-Agent": "palworld-stats/1.0"})
    text = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    names: dict[str, str] = {}
    for display, internal in PAT.findall(text):
        display, internal = display.strip(), internal.strip()
        if internal and display:
            names[internal] = display
    return names


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "pal_names.json"
    names = fetch()
    if len(names) < 50:
        print(f"trop peu d'entrées ({len(names)}) : le format du wiki a peut-être changé", file=sys.stderr)
        return 1
    with open(out, "w", encoding="utf-8") as f:
        json.dump(names, f, ensure_ascii=False, indent=0, sort_keys=True)
    print(f"{len(names)} espèces écrites dans {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
