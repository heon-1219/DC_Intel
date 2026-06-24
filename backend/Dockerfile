FROM python:3.11-slim
WORKDIR /srv/backend

# Copy source first, then editable-install: editable keeps `app` pointing at
# /srv/backend/app so the __file__-relative migrations/ and ../config paths resolve.
COPY backend/ ./
COPY config/ /srv/config/
# CPU-only torch FIRST from the PyTorch CPU index (the default Linux wheel pulls the multi-GB
# CUDA build); then the editable install with the [ml] extra (torch already satisfied) for the
# M4 sentiment/clustering models. Models themselves download from HuggingFace at first use.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -e ".[ml,x]"

ENV DATABASE_URL=sqlite+aiosqlite:////data/dcintel.db
# Normalize line endings (Windows authoring) before making the entrypoint executable.
RUN sed -i 's/\r$//' entrypoint.sh && chmod +x entrypoint.sh

CMD ["./entrypoint.sh"]
