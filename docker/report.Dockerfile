FROM python:3.13-slim-bookworm

ARG WEASYPRINT_VERSION=70.0

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        fonts-liberation \
        libharfbuzz-subset0 \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "weasyprint==${WEASYPRINT_VERSION}"

ENTRYPOINT ["weasyprint"]
