# Sidecar de statistiques Palworld : parse les saves PlM1 (Oodle) et sert
# guildes/joueurs/Pals en JSON sur localhost, pour l'app palworld-admin.
FROM python:3.12-slim

WORKDIR /app

# Dépendances d'abord (couche cache).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY palworld_stats/ ./palworld_stats/
COPY server.py .

# Non-root, même uid que l'app pour partager le volume proprement.
USER 65532:65532

ENV SAVE_DIR=/data/save \
    STATS_DB=/data/stats.db \
    PARSER_PORT=8100

EXPOSE 8100
ENTRYPOINT ["python", "server.py"]
