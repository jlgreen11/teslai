# Postgres 16 with PostGIS, built from the official multi-arch image so it runs
# natively on arm64 (Apple Silicon, Oracle Ampere) as well as amd64.
# postgis/postgis publishes amd64 only.
FROM postgres:16-bookworm@sha256:bb3e1a57e5407e0a5280b4211980a5e537f4abd234a87014ac979849a78dd825
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-16-postgis-3 \
 && rm -rf /var/lib/apt/lists/*
