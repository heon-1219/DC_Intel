#!/bin/sh
set -e
mkdir -p /data/backups /data/logs /data/models
# Seed the model volume from the image's baked tree on first boot (manifests are tracked; .pkl only
# if present at build time). -n never clobbers a volume that already has artifacts. MODEL_DIR=/data/models.
[ -d /srv/backend/models ] && cp -rn /srv/backend/models/. /data/models/ 2>/dev/null || true
python -m app.db.migrate
python -m app.db.seed
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
