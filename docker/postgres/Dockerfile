# Postgres 16 with pgvector (from the base image) + Apache AGE (built from source).
# NOTE: pin AGE_VERSION to a tag that exists for your Postgres major version; the AGE
# release cadence lags Postgres, so this may need adjusting during dev setup.
FROM pgvector/pgvector:pg16

ARG AGE_VERSION=v1.5.0-rc0
USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential git postgresql-server-dev-16 \
        flex bison libreadline-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch "PG16/${AGE_VERSION}" https://github.com/apache/age.git /tmp/age \
    && cd /tmp/age \
    && make PG_CONFIG=/usr/bin/pg_config \
    && make install PG_CONFIG=/usr/bin/pg_config \
    && rm -rf /tmp/age

USER postgres
