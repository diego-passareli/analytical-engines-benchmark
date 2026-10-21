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
-- postgresql.conf (principais parâmetros ajustados)
shared_buffers        = 8GB          -- ~13% da RAM disponível
effective_cache_size  = 24GB
work_mem              = 256MB
maintenance_work_mem  = 1GB
max_parallel_workers_per_gather = 4
wal_buffers           = 64MB
checkpoint_completion_target = 0.9
random_page_cost      = 1.1          -- SSD
```

## Medição de Consumo Energético

A interface Intel RAPL não está disponível no ambiente virtualizado (`/sys/class/powercap/intel-rapl` ausente). O consumo energético foi estimado pelo `codecarbon 3.3.1` com `tracking_mode="process"`, que utiliza a porcentagem de CPU do processo Python multiplicada pelo TDP nominal do processador (270 W por socket).

**Limitação conhecida:** para o PostgreSQL, cujo processamento ocorre em workers separados do processo Python, o `codecarbon` captura apenas o overhead de coordenação. A comparação energética entre engines utiliza o tempo de execução como proxy (tempo × TDP), conforme detalhado na Seção 4 da dissertação.

## Protocolo de Execução

- **Repetições:** 5 por query/engine (rep 1 = aquecimento, descartada na análise)
- **Timeout:** 300 s por query (queries que excedem são registradas como `TIMEOUT`)
- **Isolamento:** cache do SO limpo antes de cada execução (`sync; echo 3 > /proc/sys/vm/drop_caches` via sudo)
- **Ordem de execução:** sequencial por engine para evitar interferência de cache entre motores
- **Saída:** CSV com colunas `engine, suite, sf, query, rep, elapsed_s, cpu_pct, ram_mb, disk_mb, energy_kwh`
