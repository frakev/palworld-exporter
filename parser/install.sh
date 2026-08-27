#!/usr/bin/env bash
# Installe le parser de sauvegardes Palworld sur la machine de jeu, en service
# systemd, pour alimenter l'exporter Prometheus en stats « save » (Pals par
# joueur boîte/équipe, niveaux, captures, technologies…).
#
#   sudo ./install.sh [--server-dir <dir>] [--save-dir <dir>] [--interval <s>]
#
# Idempotent : ne réécrit pas la config si elle existe, recrée le venv sinon.
set -euo pipefail

SERVER_DIR="${SERVER_DIR:-/home/steam/Steam/steamapps/common/PalServer}"
SAVE_DIR="${SAVE_DIR:-}"
INTERVAL="${INTERVAL:-300}"
PORT="${PORT:-8100}"
APP_DIR=/opt/palworld-parser
DATA_DIR=/var/lib/palworld-parser

usage() {
  cat <<EOF
Usage: sudo $0 [options]

  --server-dir <dir>  Racine de l'installation Palworld (défaut: $SERVER_DIR)
  --save-dir <dir>    Dossier SaveGames (défaut: <server-dir>/Pal/Saved/SaveGames)
  --interval <s>      Cadence du reparse des saves en secondes (défaut: $INTERVAL)
  --port <port>       Port d'écoute local du parser (défaut: $PORT)
EOF
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --server-dir) SERVER_DIR="$2"; shift 2 ;;
    --save-dir)   SAVE_DIR="$2"; shift 2 ;;
    --interval)   INTERVAL="$2"; shift 2 ;;
    --port)       PORT="$2"; shift 2 ;;
    -h|--help)    usage ;;
    *) echo "Option inconnue: $1" >&2; usage ;;
  esac
done

[[ $EUID -eq 0 ]] || { echo "Ce script doit être lancé en root." >&2; exit 1; }
[[ -n "$SAVE_DIR" ]] || SAVE_DIR="$SERVER_DIR/Pal/Saved/SaveGames"

SRC="$(dirname "$(readlink -f "$0")")"
[[ -f "$SRC/server.py" ]] || { echo "server.py introuvable à côté du script." >&2; exit 1; }

# --- Python : venv avec un interpréteur ≥ 3.11 -------------------------------
PY=""
for c in python3.12 python3.11 python3; do
  command -v "$c" >/dev/null || continue
  ver="$("$c" -c 'import sys;print("%d%d"%sys.version_info[:2])')"
  if [[ "$ver" -ge 311 ]]; then PY="$c"; break; fi
done
[[ -n "$PY" ]] || {
  echo "Python ≥ 3.11 introuvable. Sur Rocky/RHEL 9 :  sudo dnf install -y python3.12" >&2
  exit 1
}
echo "→ interpréteur : $PY ($("$PY" --version))"

# --- Utilisateur : propriétaire des sauvegardes (droit de lecture) -----------
if [[ -d "$SAVE_DIR" ]]; then
  RUN_USER="$(stat -c %U "$SAVE_DIR")"
elif [[ -d "$SERVER_DIR" ]]; then
  RUN_USER="$(stat -c %U "$SERVER_DIR")"
else
  echo "⚠ $SAVE_DIR et $SERVER_DIR absents — le serveur est-il installé ?" >&2
  RUN_USER="steam"
fi
id "$RUN_USER" >/dev/null 2>&1 || { echo "Utilisateur $RUN_USER inexistant." >&2; exit 1; }
RUN_GROUP="$(id -gn "$RUN_USER")"
echo "→ le parser tournera sous $RUN_USER:$RUN_GROUP (lecture des saves)"

# --- Code + venv -------------------------------------------------------------
install -d -m 0755 "$APP_DIR"
rm -rf "$APP_DIR/app"
install -d -m 0755 "$APP_DIR/app"
cp -r "$SRC/palworld_stats" "$APP_DIR/app/"
install -m 0644 "$SRC/server.py" "$SRC/requirements.txt" "$APP_DIR/app/"

echo "→ création du venv et installation des dépendances (pyooz, palworld-save-tools)…"
"$PY" -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/app/requirements.txt"

# --- Données (SQLite des snapshots) ------------------------------------------
install -d -m 0750 -o "$RUN_USER" -g "$RUN_GROUP" "$DATA_DIR"

# --- Config ------------------------------------------------------------------
install -d -m 0755 /etc/palworld-parser
# Exemple documenté déposé à côté de la config réelle, pour référence sur l'hôte.
[[ -f "$SRC/config.example.env" ]] && \
  install -m 0644 "$SRC/config.example.env" /etc/palworld-parser/config.example.env
CONF=/etc/palworld-parser/parser.env
if [[ -f "$CONF" ]]; then
  echo "→ $CONF existe déjà, conservé tel quel (édite-le puis: systemctl restart palworld-parser)"
else
  cat > "$CONF" <<EOF
# Config palworld-parser — voir config.example.env pour toutes les options.
SAVE_DIR=$SAVE_DIR
STATS_DB=$DATA_DIR/stats.db
PARSER_PORT=$PORT
REPARSE_INTERVAL=$INTERVAL
HISTORY_KEEP=2000
EOF
  chmod 0644 "$CONF"
  echo "→ $CONF créé (SAVE_DIR=$SAVE_DIR, reparse=${INTERVAL}s)"
fi

# --- Unit systemd ------------------------------------------------------------
sed -e "s/^User=.*/User=$RUN_USER/" \
    -e "s/^Group=.*/Group=$RUN_GROUP/" \
    "$SRC/palworld-parser.service" \
    > /etc/systemd/system/palworld-parser.service
systemctl daemon-reload
systemctl enable palworld-parser
systemctl restart palworld-parser

sleep 2
echo
echo "════════════════════════════════════════════════════════════════"
echo " Parser installé. Vérifs locales :"
echo "   systemctl status palworld-parser"
echo "   curl -s http://127.0.0.1:$PORT/health"
echo "   curl -s http://127.0.0.1:$PORT/metrics-data | head"
echo "════════════════════════════════════════════════════════════════"
systemctl --no-pager --lines=8 status palworld-parser || true
