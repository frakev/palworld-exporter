"""Correspondance CharacterID interne → nom d'espèce affiché (noms officiels EN).

Source : Palworld Wiki « Pals / Internal names ». Les variantes régionales
(``_Dark``, ``_Ice``…) ont leur propre entrée. Les préfixes de boss/alpha
(``BOSS_``, ``GYM_``, ``RAID_``, ``PREDATOR_``) sont retirés avant recherche par
:func:`display_name`.
"""

from __future__ import annotations

PAL_NAMES = {
    "Alpaca": "Melpaca", "AmaterasuWolf": "Kitsun", "Anubis": "Anubis",
    "BadCatgirl": "Nyafia", "Baphomet": "Incineram", "Baphomet_Dark": "Incineram Noct",
    "Bastet": "Mau", "Bastet_Ice": "Mau Cryst", "BerryGoat": "Caprity",
    "BirdDragon": "Vanwyrm", "BirdDragon_Ice": "Vanwyrm Cryst", "BlackCentaur": "Necromus",
    "BlackFurDragon": "Dragostrophe", "BlackGriffon": "Shadowbeak", "BlackMetalDragon": "Astegon",
    "BlueberryFairy": "Prunelia", "BlueDragon": "Azurobe", "BluePlatypus": "Fuack",
    "Boar": "Rushoar", "CandleGhost": "Sootseer", "CaptainPenguin": "Penking",
    "Carbunclo": "Lifmunk", "CatBat": "Tombat", "CatMage": "Katress",
    "CatMage_Fire": "Katress Ignis", "CatVampire": "Felbat", "ChickenPal": "Chikipi",
    "ColorfulBird": "Tocotoco", "CowPal": "Mozzarina", "CuteButterfly": "Cinnamoth",
    "CuteFox": "Vixy", "CuteMole": "Fuddler", "DarkAlien": "Xenovader",
    "DarkCrow": "Cawgnito", "DarkMutant": "Dark Mutant", "DarkScorpion": "Menasting",
    "DarkScorpion_Ground": "Menasting Terra", "Deer": "Eikthyrdeer", "Deer_Ground": "Eikthyrdeer Terra",
    "DreamDemon": "Daedream", "DrillGame": "Digtoise", "Eagle": "Galeclaw",
    "ElecCat": "Sparkit", "ElecLion": "Boltmane", "ElecPanda": "Grizzbolt",
    "FairyDragon": "Elphidran", "FairyDragon_Water": "Elphidran Aqua", "FeatherOstrich": "Dazemu",
    "FengyunDeeper": "Fenglope", "FireKirin": "Pyrin", "FireKirin_Dark": "Pyrin Noct",
    "FlameBambi": "Rooby", "FlameBuffalo": "Arsox", "FlowerDinosaur": "Dinossom",
    "FlowerDinosaur_Electric": "Dinossom Lux", "FlowerDoll": "Petallia", "FlowerRabbit": "Flopie",
    "FlyingManta": "Celaray", "FoxMage": "Wixen", "FoxMage_Dark": "Wixen Noct",
    "Ganesha": "Teafant", "Garm": "Direhowl", "GhostBeast": "Maraith",
    "Gorilla": "Gorirat", "Gorilla_Ground": "Gorirat Terra", "GrassMammoth": "Mammorest",
    "GrassMammoth_Ice": "Mammorest Cryst", "GrassPanda": "Mossanda", "GrassPanda_Electric": "Mossanda Lux",
    "GrassRabbitMan": "Verdash", "GuardianDog": "Yakumo", "HadesBird": "Helzephyr",
    "HadesBird_Electric": "Helzephyr Lux", "HawkBird": "Nitewing", "Hedgehog": "Jolthog",
    "Hedgehog_Ice": "Jolthog Cryst", "HerculesBeetle": "Warsect", "HerculesBeetle_Ground": "Warsect Terra",
    "Horus": "Faleris", "IceDeer": "Reindrix", "IceFox": "Foxcicle",
    "IceHorse": "Frostallion", "IceHorse_Dark": "Frostallion Noct", "JetDragon": "Jetragon",
    "Kelpie": "Kelpsea", "Kelpie_Fire": "Kelpsea Ignis", "KendoFrog": "Croajiro",
    "KingAlpaca": "Kingpaca", "KingAlpaca_Ice": "Kingpaca Cryst", "KingBahamut": "Blazamut",
    "KingBahamut_Dragon": "Blazamut Ryu", "Kirin": "Univolt", "Kitsunebi": "Foxparks",
    "LavaGirl": "Flambelle", "LazyCatfish": "Dumud", "LazyDragon": "Relaxaurus",
    "LazyDragon_Electric": "Relaxaurus Lux", "LeafPrincess": "Lullu", "LilyQueen": "Lyleen",
    "LilyQueen_Dark": "Lyleen Noct", "LittleBriarRose": "Bristla", "LizardMan": "Leezpunk",
    "LizardMan_Fire": "Leezpunk Ignis", "Manticore": "Blazehowl", "Manticore_Dark": "Blazehowl Noct",
    "MimicDog": "Mimog", "Monkey": "Tanzee", "MoonQueen": "Selyne",
    "MopBaby": "Swee", "MopKing": "Sweepa", "MushroomDragon": "Shroomer",
    "MushroomDragon_Dark": "Shroomer Noct", "Mutant": "Lunaris", "NaughtyCat": "Grintale",
    "NegativeKoala": "Depresso", "NegativeOctopus": "Killamari", "NightBlueHorse": "Starryon",
    "NightFox": "Nox", "NightLady": "Bellanoir", "NightLady_Dark": "Bellanoir Libero",
    "Penguin": "Pengullet", "PinkCat": "Cattiva", "PinkLizard": "Lovander",
    "PinkRabbit": "Ribbuny", "PlantSlime": "Gumoss", "PlantSlime_Flower": "Gumoss (Special)",
    "QueenBee": "Elizabee", "RaijinDaughter": "Dazzi", "RedArmorBird": "Ragnahawk",
    "RobinHood": "Robinquill", "RobinHood_Ground": "Robinquill Terra", "Ronin": "Bushi",
    "Ronin_Dark": "Bushi Noct", "SaintCentaur": "Paladius", "SakuraSaurus": "Broncherry",
    "SakuraSaurus_Water": "Broncherry Aqua", "ScorpionMan": "Prixter", "Sekhmet": "Sekhmet",
    "Serpent": "Surfent", "Serpent_Ground": "Surfent Terra", "SharkKid": "Gobfin",
    "SharkKid_Fire": "Gobfin Ignis", "SheepBall": "Lamball", "SifuDog": "Dogen",
    "SkyDragon": "Quivern", "SkyDragon_Grass": "Quivern Botan", "SmallArmadillo": "Kikit",
    "SoldierBee": "Beegarde", "Suzaku": "Suzaku", "Suzaku_Water": "Suzaku Aqua",
    "SweetsSheep": "Woolipop", "ThunderBird": "Beakon", "ThunderDog": "Rayhound",
    "ThunderDragonMan": "Orserk", "Umihebi": "Jormuntide", "Umihebi_Fire": "Jormuntide Ignis",
    "VioletFairy": "Vaelet", "VolcanicMonster": "Reptyro", "VolcanicMonster_Ice": "Reptyro Cryst",
    "WeaselDragon": "Chillet", "WeaselDragon_Fire": "Chillet Ignis", "Werewolf": "Loupmoon",
    "WhiteAlienDragon": "Xenogard", "WhiteDeer": "Celesdir", "WhiteMoth": "Sibelyx",
    "WhiteShieldDragon": "Silvegis", "WhiteTiger": "Cryolinx", "WindChimes": "Hangyu",
    "WindChimes_Ice": "Hangyu Cryst", "WingGolem": "Knocklem", "WizardOwl": "Hoocrates",
    "WoolFox": "Cremis", "Yeti": "Wumpo", "Yeti_Grass": "Wumpo Botan",
}

# Préfixes de variantes spéciales (boss de terrain, tours, raids, prédateurs).
_PREFIXES = ("GYM_", "BOSS_", "RAID_", "PREDATOR_", "SummonBoss_")

# Overlay optionnel : un JSON {internal: display} déposé dans le volume partagé
# surcharge la table intégrée sans rebuild d'image. Il est (re)généré depuis le
# wiki par refresh_from_wiki() — appelé best-effort au démarrage du sidecar, ce
# qui garde la table à jour à chaque patch du jeu, avec repli garanti sur le
# socle ci-dessus si le réseau ou le format du wiki fait défaut.
import json as _json
import os as _os
import re as _re
import urllib.request as _url

_OVERLAY_PATH = _os.environ.get("PAL_NAMES_FILE", "/shared/pal_names.json")
_WIKI_URL = "https://palworld.wiki.gg/wiki/Pals_/_Internal_names?action=raw"
_WIKI_PAT = _re.compile(r"\{\{i\|([^|}]+)\|([^|}]+)\}\}")  # {{i|Affiché|Interne}}

_names = dict(PAL_NAMES)


def load_overlay() -> int:
    """(Re)charge l'overlay JSON par-dessus la table intégrée. Renvoie le nombre
    d'entrées surchargées (0 si aucun overlay)."""
    global _names
    merged = dict(PAL_NAMES)
    try:
        with open(_OVERLAY_PATH, encoding="utf-8") as f:
            overlay = _json.load(f)
        if not isinstance(overlay, dict):
            return 0
    except (OSError, ValueError):
        return 0
    merged.update(overlay)
    _names = merged
    return len(overlay)


def refresh_from_wiki() -> int:
    """Best-effort : télécharge la table depuis le wiki, l'écrit dans l'overlay
    et la recharge. Renvoie le nombre d'espèces, ou 0 en cas d'échec (le socle
    intégré reste en place)."""
    try:
        req = _url.Request(_WIKI_URL, headers={"User-Agent": "palworld-stats/1.0"})
        text = _url.urlopen(req, timeout=20).read().decode("utf-8", "replace")
        fresh = {i.strip(): d.strip() for d, i in _WIKI_PAT.findall(text) if i.strip() and d.strip()}
        if len(fresh) < 50:
            return 0  # format inattendu : on ne remplace pas
        tmp = _OVERLAY_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            _json.dump(fresh, f, ensure_ascii=False)
        _os.replace(tmp, _OVERLAY_PATH)
        return load_overlay()
    except Exception:
        return 0


load_overlay()  # charge un overlay déjà présent au démarrage


def is_boss(char_id: str) -> bool:
    return char_id.startswith(_PREFIXES)


def display_name(char_id: str) -> str:
    """Nom affichable d'un CharacterID, préfixes de boss retirés.

    Repli lisible pour les IDs inconnus (humains/PNJ, nouvelles espèces) :
    on coupe le CamelCase (« FlowerDinosaur » → « Flower Dinosaur »)."""
    if not char_id:
        return "?"
    key = char_id
    for p in _PREFIXES:
        if key.startswith(p):
            key = key[len(p):]
            break
    if key in _names:
        return _names[key]
    # PNJ humains capturables (Female_People03, Male_People01, SalesPerson…).
    if "People" in key or "Human" in key or "NPC" in key:
        return "Humain (PNJ)"
    # Repli : CamelCase → mots, en retirant un suffixe de variante éventuel.
    base = key.split("_")[0]
    out = "".join(" " + c if c.isupper() else c for c in base).strip()
    return out or key
