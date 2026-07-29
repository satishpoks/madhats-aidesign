FROM python:3.12-slim

WORKDIR /app

# libmagic for python-magic (file type sniffing).
#
# curl is REQUIRED, not a debugging convenience: catalogue_sync fetches the
# Shopify feed by shelling out to it. Shopify's Cloudflare edge 429s Python's
# TLS fingerprint from a hosting ASN while accepting curl's from the same
# host and IP (measured on the prod droplet 2026-07-29). Remove curl and the
# nightly catalogue sync dies in production but still passes in dev.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY app/ ./app/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
