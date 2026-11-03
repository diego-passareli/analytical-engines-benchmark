# Resultados externos (referência)

`clickbench_official_c6a4xlarge.json`: tempos oficiais publicados no painel do ClickBench
(https://benchmark.clickhouse.com, arquivo `data.generated.js`, consulta em 03/11/2026) para a máquina
AWS c6a.4xlarge (16 vCPUs), usados na comparação com os nossos resultados do ClickBench.

Sistemas e datas dos resultados: DuckDB (2026-05-11), PostgreSQL (2026-09-21) e
PostgreSQL (with indexes, marcado como "tuned" no painel; 2025-03-10).
`cold` = primeira execução de cada consulta; `hot` = menor tempo entre a 2ª e a 3ª execução.
