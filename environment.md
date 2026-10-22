# Especificação do Ambiente Experimental

> Servidor de benchmark: **vmbench01**
> Dissertação de Mestrado PPGI/UTFPR-CP — Diego Augusto Passareli (2026)

## Hardware

| Componente       | Especificação                                      |
|------------------|----------------------------------------------------|
| Processador      | Intel Xeon Gold 6444Y (Sapphire Rapids, AVX-512)  |
| vCPUs            | 16 (dedicadas, sem overcommit)                    |
| Memória RAM      | 62 GB                                              |
| Armazenamento    | SSD 490 GB (LVM sobre `/dev/sda`)                 |
| Rede             | Isolada durante os experimentos                   |

> **Nota:** os experimentos foram conduzidos em máquina virtual com recursos dedicados (sem overcommit de CPU ou memória), replicando o padrão de implantação típico de organizações de médio porte.

## Software

| Componente            | Versão                        |
|-----------------------|-------------------------------|
| Sistema Operacional   | Ubuntu 22.04.5 LTS            |
| Kernel Linux          | 5.15.0-194-generic            |
| Python                | 3.10.x                        |
| PostgreSQL            | 14.24                         |
| DuckDB                | 1.5.6                         |
| Polars                | 1.44.2                        |
| codecarbon            | 3.3.1                         |
| psutil                | 6.1.0                         |
| psycopg2-binary       | 2.9.9                         |

## Configuração do PostgreSQL

```sql
-- Valores verificados em pg_settings na vmbench01
shared_buffers                  = 8GB
work_mem                        = 1GB
max_parallel_workers            = 16
max_parallel_workers_per_gather = 8
effective_cache_size            = 45GB
```

## Medição de Consumo Energético

A interface Intel RAPL não está disponível no ambiente virtualizado (`/sys/class/powercap/intel-rapl` ausente). O `codecarbon 3.3.1` (`tracking_mode="process"`) foi registrado por consulta, mas mede apenas o processo Python. A análise de energia usa a proxy `tempo × TDP` (270 W).

**Limitação conhecida:** para o PostgreSQL, cujo processamento ocorre em workers separados do processo Python, o `codecarbon` captura apenas o overhead de coordenação. A comparação energética entre engines utiliza o tempo de execução como proxy (tempo × TDP), conforme detalhado na Seção 4 da dissertação.

## Protocolo de Execução

- **Repetições:** 5 por query/engine; a 1ª (aquecimento) é descartada e reporta-se a mediana das 4 seguintes. Nos CSVs de TPC-H, TPC-DS e ClickBench o aquecimento não é gravado (rep 1–4 = execuções válidas); no CSV de dados reais ele é gravado como rep 1.
- **Timeout:** `statement_timeout` de 270 s no PostgreSQL (TPC-DS e ClickBench) e 300 s por query no subprocesso do Polars; 300 s nos dados reais. Falhas são gravadas com `elapsed_s = -1`.
- **DuckDB:** `threads=16`, `memory_limit=40GB`.
- **Polars:** `POLARS_MAX_THREADS=16`, subprocesso isolado com limite de 30 GB de memória virtual (`RLIMIT_AS`).
- **Isolamento:** cache do SO limpo antes de cada execução (`sync; echo 3 > /proc/sys/vm/drop_caches` via sudo)
- **Ordem de execução:** suítes sintéticas — para cada query e repetição, PostgreSQL → DuckDB → Polars; dados reais — as 5 repetições de cada engine em sequência.
- **Saída:** CSV com colunas `engine, suite, sf, query, rep, elapsed_s, cpu_pct, ram_mb, disk_mb, energy_kwh`
