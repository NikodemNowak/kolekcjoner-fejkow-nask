# CPU image for the jury: base install + `ml` (+ `bge`) extras with CPU-only torch, the model
# weights and the face / logo reference sets baked in. Runs offline. Corpus data and runs are
# mounted, never copied in. The `app` target serves the CLI and the JSON API (:8600); the `web`
# target is the Next.js UI (:3000) in front of it. `docker compose build` builds both.
#   docker build -t fakecollector .                          (full: models + references)
#   docker build --build-arg WITH_BGE=0 -t fakecollector .   (without bge-m3, ~2 GB smaller)
#   docker build --build-arg WITH_ML=0 -t fakecollector .    (light: no models at all)
ARG WITH_ML=1
ARG WITH_BGE=1

# Next.js UI. `next/font` fetches the Geist fonts here, at build time, and self-hosts them, so
# the running UI needs no network. The API address is baked into the `/api/*` rewrite.
FROM node:22-slim AS web-build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
ARG KF_API_URL=http://app:8600
ENV KF_API_URL=$KF_API_URL NEXT_TELEMETRY_DISABLED=1
# No `npm prune --omit=dev`: `next start` needs TypeScript to load next.config.ts and would
# otherwise try to install it at run time.
RUN npm run build

FROM node:22-slim AS web
ARG KF_API_URL=http://app:8600
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 KF_API_URL=$KF_API_URL
WORKDIR /web
COPY --from=web-build --chown=node:node /web ./
USER node
EXPOSE 3000
CMD ["node_modules/.bin/next", "start", "-H", "0.0.0.0", "-p", "3000"]

FROM python:3.12-slim AS build
ARG WITH_ML
ARG WITH_BGE
# insightface has no wheel for 3.12 and compiles a small C extension
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock README.md ./
# Same pinned versions as uv.lock; torch resolves to its +cpu build and the CUDA-only
# packages (nvidia-*, triton) are left out, which saves several GB.
RUN uv venv /opt/venv \
    && EXTRAS="--extra web" \
    && if [ "$WITH_ML" = "1" ]; then EXTRAS="$EXTRAS --extra ml"; fi \
    && if [ "$WITH_ML" = "1" ] && [ "$WITH_BGE" = "1" ]; then EXTRAS="$EXTRAS --extra bge"; fi \
    && uv export --frozen --no-dev $EXTRAS --no-hashes --no-emit-project -o /tmp/req.txt \
    && grep -vE '^(nvidia-|triton)' /tmp/req.txt > /tmp/req-cpu.txt \
    && uv pip install --python /opt/venv --index-strategy unsafe-best-match \
       --extra-index-url https://download.pytorch.org/whl/cpu -r /tmp/req-cpu.txt
COPY src ./src
RUN uv pip install --python /opt/venv --no-deps .

FROM python:3.12-slim AS app
ARG WITH_ML
ARG WITH_BGE
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 app \
    && mkdir -p /opt/models/hf /opt/refs /app \
    && chown -R app:app /opt/models /opt/refs /app
COPY --from=build /opt/venv /opt/venv
# Caches of every model library live under the app user's home or HF_HOME, so the
# prefetch below fills exactly what the runtime reads.
ENV PATH=/opt/venv/bin:$PATH \
    HOME=/home/app \
    HF_HOME=/opt/models/hf \
    FAKECOLLECTOR_DEVICE=cpu \
    FACE_DB=/opt/refs/faces/db.npz \
    LOGO_REFS=/opt/refs/logos/refs.npz
USER app
WORKDIR /build
COPY --chown=app:app scripts/prefetch_models.py scripts/fetch_face_refs.py \
     scripts/build_face_db.py scripts/build_logo_refs.py scripts/
COPY --chown=app:app refs refs
# Models first, then the reference sets built with them (public-figure photos and brand
# logos from Wikimedia Commons, listed with licenses in refs/*.csv). Only the derived
# vectors are kept; the downloaded photos and logos are removed. /opt/refs sits outside
# the mounted ./data, so the mount cannot hide it.
RUN if [ "$WITH_ML" = "1" ]; then \
      PREFETCH_BGE=$WITH_BGE python scripts/prefetch_models.py \
      && python scripts/fetch_face_refs.py --out /tmp/faces \
      && python scripts/build_face_db.py /tmp/faces --out /opt/refs/faces/db.npz \
      && python scripts/build_logo_refs.py \
      && mkdir -p /opt/refs/logos && mv data/logos/refs.npz /opt/refs/logos/refs.npz \
      && rm -rf /tmp/faces data; \
    fi
# From here on nothing may reach the network (works with `docker run --network none`).
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 FAKECOLLECTOR_B_CACHE=/app/runs/.cache/derived
WORKDIR /app
EXPOSE 8600
# The API reads the run from APP_RUN_DIR; 0.0.0.0 so the `web` container can reach it.
CMD ["uvicorn", "fakecollector.api.server:app", "--host", "0.0.0.0", "--port", "8600"]
