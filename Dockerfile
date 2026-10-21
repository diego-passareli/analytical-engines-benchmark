# ============================================================
# Dockerfile — Benchmark Analítico On-Premise
# Dissertação de Mestrado PPGI/UTFPR-CP — Diego Augusto Passareli
#
# Reproduz o ambiente Python dos scripts de benchmark.
# PostgreSQL roda fora do contêiner (servidor dedicado).
#
# Build:  docker build -t bench-analytics .
# Run:    docker run --rm -v $(pwd)/results:/bench/results bench-analytics \
#             python scripts/run_tpcds.py 1
# ============================================================

FROM ubuntu:22.04

LABEL maintainer="knightdiegopassareli@gmail.com"
LABEL description="Ambiente de benchmark analítico — PostgreSQL vs DuckDB vs Polars"
LABEL version="1.0"

# Evita prompts interativos durante o build
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# ── Dependências do sistema ───────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 \
    python3.10-dev \
    python3-pip \
    python3-venv \
    libpq-dev \
    gcc \
    g++ \
    curl \
    procps \
    sudo \
    && rm -rf /var/lib/apt/lists/*

# Apelido python → python3.10
RUN ln -sf /usr/bin/python3.10 /usr/bin/python3 \
 && ln -sf /usr/bin/python3.10 /usr/bin/python

# ── Dependências Python (versões exatas do experimento) ───────────────────
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

# ── Estrutura de diretórios do benchmark ─────────────────────────────────
RUN mkdir -p /bench/scripts /bench/data /bench/results /bench/queries

WORKDIR /bench

# ── Scripts de benchmark ──────────────────────────────────────────────────
COPY scripts/ /bench/scripts/

# ── Permissão para limpar cache de disco (necessário para drop_caches) ───
# Em produção, o usuário do host deve ter sudo sem senha para:
#   sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'
# Dentro do contêiner isso requer --privileged ou execução no host.

# ── Variáveis de ambiente configuráveis ──────────────────────────────────
ENV PGHOST=host.docker.internal
ENV PGPORT=5432
ENV PGUSER=bench
ENV PGPASSWORD=bench
ENV BENCH_DATA_DIR=/bench/data
ENV BENCH_RESULTS_DIR=/bench/results

# ── Entrypoint padrão: exibe ajuda ───────────────────────────────────────
CMD ["python3", "scripts/run_tpcds.py", "--help"]
