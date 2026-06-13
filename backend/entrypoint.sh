#!/bin/sh
set -e
python -m app.db.migrate
python -m app.db.seed
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
