#!/bin/sh
set -e
mkdir -p /data/backups /data/logs
python -m app.db.migrate
python -m app.db.seed
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
