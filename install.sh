#!/usr/bin/env bash
# Installe palworld-exporter sur la machine qui héberge le serveur Palworld.
#
#   sudo ./install.sh --home-ip <IP publique de la maison> [options]
#
# L'exporter interroge l'API REST officielle du serveur Palworld (127.0.0.1) et,
# si présent, le parser de sauvegardes, puis réexpose le tout au format
# Prometheus. Aucun agent requis. Le script est idempotent : il ne réécrit pas
# la config si elle existe déjà, et récupère l'AdminPassword depuis le .ini.
set -euo pipefail

PORT="${PORT:-9812}"
SERVER_DIR="${SERVER_DIR:-/home/steam/Steam/steamapps/common/PalServer}"
SETTINGS_PATH="${SETTINGS_PATH:-}"
REST_PASSWORD="${REST_PASSWORD:-}"
REST_PORT="${REST_PORT:-}"
HOME_IP=""

usage() {
  cat <<EOF
Usage: sudo $0 --home-ip <IP> [options]

  --home-ip <IP>        IP publique autorisée à scruter /metrics (obligatoire)
  --port <port>         Port d'écoute de l'exporter (défaut: $PORT)
  --server-dir <dir>    Racine de l'install Palworld, pour trouver le .ini
  --settings <path>     Chemin de PalWorldSettings.ini (sinon déduit de server-dir)
  --rest-password <pw>  AdminPassword (sinon lu dans le .ini)
  --rest-port <port>    Port de l'API REST (sinon lu dans le .ini, défaut 8212)
EOF
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --home-ip)       HOME_IP="$2"; shift 2 ;;
    --port)          PORT="$2"; shift 2 ;;
    --server-dir)    SERVER_DIR="$2"; shift 2 ;;
    --settings)      SETTINGS_PATH="$2"; shift 2 ;;
    --rest-password) REST_PASSWORD="$2"; shift 2 ;;
    --rest-port)     REST_PORT="$2"; shift 2 ;;
    -h|--help)       usage ;;
    *) echo "Option inconnue: $1" >&2; usage ;;
  esac
done

[[ $EUID -eq 0 ]] || { echo "Ce script doit être lancé en root." >&2; exit 1; }
[[ -n "$HOME_IP" ]] || { echo "--home-ip est obligatoire." >&2; usage; }
[[ -n "$SETTINGS_PATH" ]] || \
  SETTINGS_PATH="$SERVER_DIR/Pal/Saved/Config/LinuxServer/PalWorldSettings.ini"

BIN_SRC="$(dirname "$(readlink -f "$0")")/palworld-exporter"
[[ -x "$BIN_SRC" ]] || {
  echo "Binaire absent : construis-le d'abord avec" >&2
  echo "  CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags='-s -w' -o palworld-exporter ." >&2
  exit 1
}

# AdminPassword + port REST : extraits du bloc OptionSettings=(...) du .ini,
# sauf s'ils sont fournis en option.
if [[ -z "$REST_PASSWORD" && -r "$SETTINGS_PATH" ]]; then
  REST_PASSWORD="$(grep -oP 'AdminPassword="\K[^"]*' "$SETTINGS_PATH" | head -1 || true)"
fi
if [[ -z "$REST_PORT" && -r "$SETTINGS_PATH" ]]; then
  REST_PORT="$(grep -oP 'RESTAPIPort=\K[0-9]+' "$SETTINGS_PATH" | head -1 || true)"
fi
REST_PORT="${REST_PORT:-8212}"
if [[ -z "$REST_PASSWORD" ]]; then
  echo "⚠ AdminPassword introuvable dans $SETTINGS_PATH."
  echo "  Renseigne-le avec --rest-password, ou édite ensuite /etc/palworld-exporter/exporter.env."
  echo "  (Vérifie aussi RESTAPIEnabled=True dans le .ini.)"
fi

# --- Utilisateur système dédié (aucun privilège requis) ----------------------
EXP_USER=palworld-exporter
if ! id "$EXP_USER" >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin "$EXP_USER"
  echo "→ utilisateur système $EXP_USER créé"
fi

# --- Binaire et arborescence -------------------------------------------------
install -m 0755 "$BIN_SRC" /usr/local/bin/palworld-exporter
install -d -m 0750 -o "$EXP_USER" -g "$EXP_USER" /etc/palworld-exporter

CONF=/etc/palworld-exporter/exporter.env
if [[ -f "$CONF" ]]; then
  echo "→ $CONF existe déjà, conservé tel quel"
else
  cat > "$CONF" <<EOF
LISTEN=:$PORT
REST_URL=http://127.0.0.1:$REST_PORT
REST_USER=admin
REST_PASSWORD=$REST_PASSWORD
PARSER_URL=http://127.0.0.1:8100
METRICS_TOKEN=
EOF
  chown "$EXP_USER:$EXP_USER" "$CONF"
  chmod 0640 "$CONF"
  echo "→ $CONF créé (REST http://127.0.0.1:$REST_PORT, AdminPassword ${REST_PASSWORD:+repris du .ini}${REST_PASSWORD:-À RENSEIGNER})"
fi

# --- Unit systemd ------------------------------------------------------------
install -m 0644 "$(dirname "$(readlink -f "$0")")/palworld-exporter.service" \
  /etc/systemd/system/palworld-exporter.service
systemctl daemon-reload
systemctl enable palworld-exporter
systemctl restart palworld-exporter

# --- Pare-feu : /metrics ouvert à l'IP maison uniquement ---------------------
if command -v firewall-cmd >/dev/null && firewall-cmd --state >/dev/null 2>&1; then
  firewall-cmd --permanent --add-rich-rule="rule family=ipv4 source address=$HOME_IP port port=$PORT protocol=tcp accept" >/dev/null
  firewall-cmd --reload >/dev/null
  echo "→ firewalld : port $PORT ouvert pour $HOME_IP uniquement"
elif command -v ufw >/dev/null; then
  ufw allow from "$HOME_IP" to any port "$PORT" proto tcp >/dev/null
  echo "→ ufw : port $PORT ouvert pour $HOME_IP uniquement"
else
  echo "⚠ aucun pare-feu détecté — restreins le port $PORT à $HOME_IP à la main"
fi

# --- Récapitulatif -----------------------------------------------------------
sleep 1
echo
echo "════════════════════════════════════════════════════════════════"
echo " Cible de scrape Prometheus (côté cluster) :"
echo
echo "   <ip-de-cette-machine>:$PORT   /metrics   (HTTP)"
echo "════════════════════════════════════════════════════════════════"
echo
systemctl --no-pager --lines=5 status palworld-exporter || true
echo
echo "Vérif locale :  curl -s http://127.0.0.1:$PORT/metrics | head"
