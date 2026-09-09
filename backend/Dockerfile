# The Bhav API.
#
# The pipeline's output — data/bhav.db and models/*.pkl — is committed and
# copied into the image, so a fresh deploy serves a decade of history on its
# first request instead of 503ing until someone runs an ingest. What the image
# cannot provide is anywhere durable to *write*: point BHAV_DATA_DIR at a
# mounted disk and bhav/bootstrap.py copies the shipped snapshot across on first
# boot, after which subscriptions survive every redeploy. See DEPLOY.md.

FROM python:3.12-slim

# Python 3.12 rather than the newest: lightgbm, numpy and scikit-learn all
# publish manylinux wheels for it, so the build is a download rather than a
# twenty-minute compile — and a slim image has no compiler to do it with.

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libgomp1 is LightGBM's OpenMP runtime. It is not a build dependency — the
# wheel imports it at runtime — so leaving it out produces an image that builds
# cleanly and then fails on `import lightgbm`.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Requirements first, as their own layer: they change far less often than the
# code, and pandas + lightgbm is not a fast reinstall.
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY bhav/ ./bhav/
COPY scripts/ ./scripts/
COPY data/ ./data/
COPY models/ ./models/

# Serving does not need root, and a container that cannot write to its own code
# is one fewer thing to reason about. /var/data is created and handed over so a
# disk mounted there is writable from the first boot.
RUN useradd --create-home --uid 10001 bhav \
    && mkdir -p /var/data \
    && chown -R bhav:bhav /var/data /app
USER bhav

ENV BHAV_DATA_DIR=/var/data \
    BHAV_MODELS_DIR=/var/data/models \
    PORT=8000

EXPOSE 8000

# /health is deliberately the cheap one — no database, no model — so a slow
# first query can never stop a healthy deploy from going live. /readyz is the
# one that says whether there is anything to serve.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('PORT','8000')}/health\").read()"

# One worker on purpose. Each worker holds its own copy of the feature matrix
# and the model, so a second one doubles the memory for no throughput on an
# instance with a fraction of a CPU. Scale by raising WEB_CONCURRENCY only once
# the instance has the cores and the RAM to back it.
CMD ["sh", "-c", "exec uvicorn bhav.api:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-1} --timeout-keep-alive 65"]
