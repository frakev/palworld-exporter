"""Sidecar de statistiques Palworld.

Lit un bundle de save (``Level.sav`` + ``Players/*.sav``) déposé par l'app Go
dans un volume partagé, le parse (voir :mod:`palworld_stats`), stocke un snapshot
horodaté dans SQLite, et sert le tout en JSON sur ``localhost``.

Endpoints :
  GET  /health                 -> {"ok": true, "last_snapshot": <ts|null>}
  POST /reparse                -> reparse immédiat du bundle, renvoie le résumé
  GET  /api/guilds             -> guildes (dernier snapshot) + agrégats
  GET  /api/players            -> joueurs (dernier snapshot)
  GET  /api/player/{uid}       -> joueur + son équipe/boîte (pals)
  GET  /api/player/{uid}/history -> séries temporelles (onglet Activité)

Aucune dépendance web : http.server + sqlite3 (tous deux dans la stdlib).
"""

from __future__ import annotations

import glob
import json
import os
import re
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from palworld_stats import extract
from palworld_stats import pal_names
from palworld_stats import technologies
from palworld_stats import skills

SAVE_DIR = os.environ.get("SAVE_DIR", "/data/save")
DB_PATH = os.environ.get("STATS_DB", "/data/stats.db")
LISTEN = int(os.environ.get("PARSER_PORT", "8100"))
# Snapshots d'historique conservés (pour les graphes d'activité).
HISTORY_KEEP = int(os.environ.get("HISTORY_KEEP", "2000"))
# Reparse périodique automatique (secondes ; 0 = désactivé). Utilisé quand le
# parser tourne directement sur l'hôte de jeu, à côté de l'exporter Prometheus,
# sans l'app Go pour déclencher les /reparse. Le parsing est coûteux : viser
# large (5 min et plus). En mode sidecar cluster, laisser à 0.
REPARSE_INTERVAL = int(os.environ.get("REPARSE_INTERVAL", "0"))

_lock = threading.Lock()


# --------------------------------------------------------------------------- #
#  SQLite
# --------------------------------------------------------------------------- #
def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                taken_at INTEGER NOT NULL,
                payload  TEXT NOT NULL          -- résultat extract() en JSON
            );
            CREATE TABLE IF NOT EXISTS player_history (
                snapshot_id INTEGER NOT NULL,
                taken_at    INTEGER NOT NULL,
                uid         TEXT NOT NULL,
                level       INTEGER,
                captures    INTEGER,
                paldeck     INTEGER,
                pals_owned  INTEGER,
                technologies INTEGER,
                field_bosses INTEGER,
                dungeons    INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_hist_uid ON player_history(uid, taken_at);
            """
        )


def store_snapshot(data: dict) -> int:
    ts = int(time.time())
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO snapshots(taken_at, payload) VALUES (?, ?)",
            (ts, json.dumps(data, ensure_ascii=False)),
        )
        sid = cur.lastrowid
        conn.executemany(
            """INSERT INTO player_history
               (snapshot_id, taken_at, uid, level, captures, paldeck, pals_owned,
                technologies, field_bosses, dungeons)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    sid, ts, p["uid"], p.get("level"), p.get("captures"),
                    p.get("paldeck"), p.get("pals_owned"), p.get("technologies"),
                    p.get("field_bosses"), p.get("dungeons"),
                )
                for p in data["players"]
            ],
        )
        # Purge des vieux snapshots (garde les N derniers).
        conn.execute(
            """DELETE FROM snapshots WHERE id NOT IN
               (SELECT id FROM snapshots ORDER BY id DESC LIMIT ?)""",
            (HISTORY_KEEP,),
        )
        conn.execute(
            """DELETE FROM player_history WHERE snapshot_id NOT IN
               (SELECT id FROM snapshots)"""
        )
    return sid


def latest_payload() -> dict | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT payload FROM snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return json.loads(row["payload"]) if row else None


def latest_ts() -> int | None:
    with _db() as conn:
        row = conn.execute("SELECT taken_at FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
    return row["taken_at"] if row else None


def player_history(uid: str) -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            """SELECT taken_at, level, captures, paldeck, pals_owned,
                      technologies, field_bosses, dungeons
               FROM player_history WHERE uid = ? ORDER BY taken_at""",
            (uid,),
        ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
#  Parsing
# --------------------------------------------------------------------------- #
# Une save de joueur est nommée ``<UID 32 hexa>.sav``. Le jeu dépose à côté des
# fichiers annexes (``<UID>_dps.sav``) qui n'ont pas la même structure : les
# passer à ``load_player`` fait dérailler le décodeur, qui lit des longueurs
# aberrantes et alloue ~600 Mio pour un fichier de 35 Ko (→ sidecar OOMKilled).
# Pire, la clé retenue étant le préfixe d'UID, ils écrasaient la vraie save du
# joueur une fois sur deux, selon l'ordre renvoyé par glob.
PLAYER_SAV_RE = re.compile(r"^[0-9a-f]{32}\.sav$", re.IGNORECASE)


def _world_dir() -> str:
    """Dossier contenant ``Level.sav``. En sidecar cluster, l'app dépose le
    bundle directement dans ``SAVE_DIR``. Sur l'hôte de jeu, ``SAVE_DIR`` pointe
    sur ``SaveGames`` et le monde est imbriqué dessous : ``SaveGames/<hexa>``,
    ou ``SaveGames/0/<hexa>`` sur un serveur dédié (le ``0`` est l'index de
    profil local). On résout les deux profondeurs automatiquement, en écartant
    les copies de ``<monde>/backup/world/<date>/``."""
    if os.path.exists(os.path.join(SAVE_DIR, "Level.sav")):
        return SAVE_DIR
    candidates = []
    for depth in ("*", os.path.join("*", "*")):
        for level in glob.glob(os.path.join(SAVE_DIR, depth, "Level.sav")):
            rel = os.path.relpath(level, SAVE_DIR).split(os.sep)
            if "backup" in rel:
                continue
            candidates.append(os.path.dirname(level))
    # Le monde actif est le plus récemment modifié (utile si plusieurs mondes).
    candidates.sort(key=lambda d: os.path.getmtime(os.path.join(d, "Level.sav")))
    return candidates[-1] if candidates else SAVE_DIR


def read_bundle() -> tuple[bytes, dict[str, bytes]]:
    base = _world_dir()
    level_path = os.path.join(base, "Level.sav")
    level = open(level_path, "rb").read()
    players = {}
    for f in glob.glob(os.path.join(base, "Players", "*.sav")):
        name = os.path.basename(f)
        if not PLAYER_SAV_RE.match(name):
            continue
        players[name[:8].lower()] = open(f, "rb").read()
    return level, players


def reparse() -> dict:
    with _lock:
        level, players = read_bundle()
        data = extract(level, players)
        store_snapshot(data)
    return {
        "guilds": len(data["guilds"]),
        "players": len(data["players"]),
        "pals": len(data["pals"]),
    }


# --------------------------------------------------------------------------- #
#  Vues (agrégats) construites sur le dernier snapshot
# --------------------------------------------------------------------------- #
def _pals_by_owner(data: dict) -> dict[str, list]:
    out: dict[str, list] = {}
    for pal in data["pals"]:
        out.setdefault(pal["owner_uid"], []).append(pal)
    return out


def view_guilds(data: dict) -> list[dict]:
    players = {p["uid"]: p for p in data["players"]}
    guilds = []
    for g in data["guilds"]:
        members = []
        cumul = 0
        for m in g["members"]:
            p = players.get(m["uid"], {})
            lvl = p.get("level", 0)
            cumul += lvl or 0
            members.append(
                {
                    "uid": m["uid"],
                    "name": m.get("name") or p.get("nickname"),
                    "level": lvl,
                    "captures": p.get("captures"),
                    "pals_owned": p.get("pals_owned"),
                    "last_online": m.get("last_online") or p.get("last_online"),
                }
            )
        members.sort(key=lambda x: -(x["level"] or 0))
        guilds.append(
            {
                "guild_uid": g["guild_uid"],
                "name": g["name"],
                "base_camp_level": g["base_camp_level"],
                "base_count": g["base_count"],
                "member_count": len(members),
                "cumulative_level": cumul,
                "members": members,
            }
        )
    guilds.sort(key=lambda x: -x["cumulative_level"])
    return guilds


def view_map(data: dict) -> dict:
    """Marqueurs pour la carte : bases (par guilde) et dernière position joueur."""
    guild_name = {g["guild_uid"]: g["name"] for g in data["guilds"]}
    bases = [
        {**b, "guild_name": guild_name.get(b.get("guild_uid"))}
        for b in data.get("bases", [])
    ]
    players = [
        {"uid": p["uid"], "name": p.get("nickname"), "guild_uid": p.get("guild_uid"),
         "map_x": p["map_x"], "map_y": p["map_y"],
         "world_x": p.get("world_x"), "world_y": p.get("world_y"),
         "last_online": p.get("last_online")}
        for p in data["players"]
        if p.get("map_x") is not None
    ]
    return {"bases": bases, "players": players, "taken_at": latest_ts()}


def view_metrics(data: dict) -> dict:
    """Agrégat compact par joueur pour l'exporter Prometheus : compteurs de la
    fiche joueur + répartition des Pals (boîte / équipe / lucky), calculée en une
    passe. Sert de source aux métriques ``palworld_player_*`` côté exporter."""
    by_owner = _pals_by_owner(data)
    guild_name = {g["guild_uid"]: g["name"] for g in data["guilds"]}
    players_out = []
    total_pals = total_lucky = 0
    for p in data["players"]:
        mine = by_owner.get(p["uid"], [])
        box = sum(1 for x in mine if x.get("container") == p.get("box_container"))
        party = sum(1 for x in mine if x.get("container") == p.get("party_container"))
        lucky = sum(1 for x in mine if x.get("is_lucky"))
        total_pals += len(mine)
        total_lucky += lucky
        players_out.append({
            "uid": p["uid"],
            "name": p.get("nickname") or "",
            "guild": guild_name.get(p.get("guild_uid")) or "",
            "level": p.get("level") or 0,
            "exp": p.get("exp") or 0,
            "pals_owned": p.get("pals_owned") or 0,
            "pals_box": box,
            "pals_party": party,
            "pals_lucky": lucky,
            "captures": p.get("captures") or 0,
            "tribes_captured": p.get("tribes_captured") or 0,
            "paldeck": p.get("paldeck") or 0,
            "technologies": p.get("technologies") or 0,
            "technology_points": p.get("technology_points") or 0,
            "boss_technology_points": p.get("boss_technology_points") or 0,
            "tower_bosses": p.get("tower_bosses") or 0,
            "field_bosses": p.get("field_bosses") or 0,
            "dungeons": p.get("dungeons") or 0,
            "zones_explored": p.get("zones_explored") or 0,
            "fast_travels": p.get("fast_travels") or 0,
            "effigies": p.get("effigies") or 0,
            "quests_completed": p.get("quests_completed") or 0,
            "last_online": p.get("last_online"),
        })
    return {
        "taken_at": latest_ts(),
        "players": players_out,
        "guild_count": len(data["guilds"]),
        "player_count": len(data["players"]),
        "pal_count": total_pals,
        "lucky_count": total_lucky,
    }


def view_player(data: dict, uid: str) -> dict | None:
    p = next((x for x in data["players"] if x["uid"] == uid), None)
    if not p:
        return None
    mine = _pals_by_owner(data).get(uid, [])
    party = [x for x in mine if x["container"] == p.get("party_container")]
    box = [x for x in mine if x["container"] == p.get("box_container")]
    party.sort(key=lambda x: (x.get("slot_index") or 0))
    box.sort(key=lambda x: (-(x.get("level") or 0), -(x.get("iv_total") or 0)))
    for pal in (*party, *box):
        skills.enrich_pal(pal)
    tech = technologies.breakdown(p.get("unlocked_tech"))
    return {"player": p, "party": party, "box": box, "technologies": tech}


# --------------------------------------------------------------------------- #
#  HTTP
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_):  # silence
        pass

    def do_GET(self):
        parts = self.path.strip("/").split("/")
        if self.path == "/health":
            return self._send(200, {"ok": True, "last_snapshot": latest_ts()})
        data = latest_payload()
        if data is None:
            return self._send(503, {"error": "aucun snapshot encore"})
        if parts == ["api", "guilds"]:
            return self._send(200, {"guilds": view_guilds(data), "taken_at": latest_ts()})
        if parts == ["api", "players"]:
            return self._send(200, {"players": data["players"], "taken_at": latest_ts()})
        if parts == ["metrics-data"]:
            return self._send(200, view_metrics(data))
        if parts == ["api", "map"]:
            return self._send(200, view_map(data))
        if len(parts) == 3 and parts[:2] == ["api", "player"]:
            v = view_player(data, parts[2])
            return self._send(200, v) if v else self._send(404, {"error": "joueur inconnu"})
        if len(parts) == 4 and parts[:2] == ["api", "player"] and parts[3] == "history":
            return self._send(200, {"history": player_history(parts[2])})
        return self._send(404, {"error": "route inconnue"})

    def do_POST(self):
        if self.path == "/reparse":
            try:
                return self._send(200, reparse())
            except FileNotFoundError:
                return self._send(503, {"error": "bundle de save absent"})
            except Exception as e:  # noqa: BLE001
                return self._send(500, {"error": f"{type(e).__name__}: {e}"})
        if self.path == "/refresh-tech":
            # Rafraîchit la table des technologies depuis paldb (best-effort).
            n = technologies.refresh_from_paldb()
            if n:
                return self._send(200, {"ok": True, "count": n})
            return self._send(502, {"ok": False, "error": "paldb injoignable",
                                     "count": len(technologies.MASTER)})
        if self.path == "/refresh-skills":
            # Rafraîchit compétences actives + métiers depuis paldb.
            n = skills.refresh_from_paldb()
            w = skills.refresh_work_from_paldb()
            if n or w:
                return self._send(200, {"ok": True, "count": n or len(skills.ACTIVE),
                                        "work": w or len(skills.WORK)})
            return self._send(502, {"ok": False, "error": "paldb injoignable",
                                     "count": len(skills.ACTIVE), "work": len(skills.WORK)})
        return self._send(404, {"error": "route inconnue"})


def _refresh_pal_names_loop() -> None:
    """Rafraîchit la table de noms d'espèces depuis le wiki au démarrage puis
    chaque semaine. Best-effort : échec silencieux, la table intégrée reste."""
    while True:
        n = pal_names.refresh_from_wiki()
        print(f"noms d'espèces : {n} entrées depuis le wiki" if n else
              "noms d'espèces : table intégrée (wiki injoignable)", flush=True)
        t = technologies.refresh_from_paldb()
        print(f"technologies : {t} entrées depuis paldb" if t else
              f"technologies : table active ({len(technologies.MASTER)} entrées, "
              "paldb injoignable)", flush=True)
        s = skills.refresh_from_paldb()
        print(f"compétences actives : {s} entrées depuis paldb" if s else
              f"compétences actives : table active ({len(skills.ACTIVE)} entrées, "
              "paldb injoignable)", flush=True)
        wk = skills.refresh_work_from_paldb()
        print(f"métiers : {wk} espèces depuis paldb" if wk else
              f"métiers : table active ({len(skills.WORK)} espèces, paldb injoignable)",
              flush=True)
        time.sleep(7 * 24 * 3600)


def _reparse_loop() -> None:
    """Reparse périodique des saves locales, pour l'exécution sur l'hôte de jeu
    (sans app Go pour déclencher /reparse). Chaque cycle relit Level.sav du monde
    actif et met à jour le snapshot."""
    while True:
        time.sleep(REPARSE_INTERVAL)
        try:
            reparse()
        except Exception as e:  # noqa: BLE001
            print("reparse périodique échoué:", e, flush=True)


def main() -> None:
    init_db()
    threading.Thread(target=_refresh_pal_names_loop, daemon=True).start()
    # Premier parse au démarrage si un bundle est déjà là.
    try:
        print("parse initial:", reparse(), flush=True)
    except Exception as e:  # noqa: BLE001
        print("pas de parse initial:", e, flush=True)
    if REPARSE_INTERVAL > 0:
        threading.Thread(target=_reparse_loop, daemon=True).start()
        print(f"reparse périodique toutes les {REPARSE_INTERVAL}s", flush=True)
    srv = ThreadingHTTPServer(("127.0.0.1", LISTEN), Handler)
    print(f"palworld-stats sidecar en écoute sur 127.0.0.1:{LISTEN}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
