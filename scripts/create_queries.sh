#!/bin/bash
# Cola e executa no vmbench01:
#   bash create_queries.sh

mkdir -p ~/bench/scripts/queries/real
Q=~/bench/scripts/queries/real

cat > "$Q/q01.sql" << 'EOF'
SELECT
    DATE_TRUNC('month', data_competencia)  AS mes,
    SUM(valor_pago)                        AS total_pago,
    SUM(valor_faturado)                    AS total_faturado,
    COUNT(*)                               AS registros
FROM fato_custo
GROUP BY 1
ORDER BY 1;
EOF

cat > "$Q/q02.sql" << 'EOF'
SELECT
    sk_prestador_executante,
    SUM(valor_pago)                        AS custo_total,
    SUM(valor_pago_honor)                  AS total_honorarios,
    COUNT(*)                               AS atendimentos,
    COUNT(DISTINCT sk_beneficiario)        AS beneficiarios_distintos
FROM fato_custo
GROUP BY 1
ORDER BY 2 DESC
LIMIT 50;
EOF

cat > "$Q/q03.sql" << 'EOF'
SELECT
    EXTRACT(YEAR FROM data_competencia)    AS ano,
    tipo_atendimento,
    tipo_despesa,
    SUM(valor_pago)                        AS total_pago,
    SUM(valor_faturado)                    AS total_faturado,
    SUM(valor_faturado - valor_pago)       AS glosa_total,
    COUNT(*)                               AS registros
FROM fato_custo
GROUP BY 1, 2, 3
ORDER BY 1, 4 DESC;
EOF

cat > "$Q/q04.sql" << 'EOF'
SELECT
    carater_internacao,
    tipo_internacao,
    custo_acomodacao,
    COUNT(DISTINCT sk_beneficiario)        AS pacientes,
    COUNT(*)                               AS registros,
    SUM(valor_pago)                        AS custo_total,
    AVG(valor_pago)                        AS custo_medio,
    SUM(valor_pago_filme)                  AS total_filme,
    SUM(valor_pago_co)                     AS total_co
FROM fato_custo
WHERE internacao = 'SIM'
GROUP BY 1, 2, 3
ORDER BY 6 DESC;
EOF

cat > "$Q/q05.sql" << 'EOF'
SELECT
    EXTRACT(MONTH FROM data_competencia)   AS mes_numero,
    turno_atendimento,
    SUM(valor_pago)                        AS total_pago,
    COUNT(*)                               AS atendimentos,
    AVG(valor_pago)                        AS ticket_medio
FROM fato_custo
WHERE turno_atendimento IS NOT NULL
  AND turno_atendimento <> ''
GROUP BY 1, 2
ORDER BY 1, 2;
EOF

cat > "$Q/q06.sql" << 'EOF'
SELECT
    cid,
    COUNT(*)                               AS ocorrencias,
    COUNT(DISTINCT sk_beneficiario)        AS pacientes_distintos,
    SUM(valor_pago)                        AS custo_total,
    AVG(valor_pago)                        AS custo_medio_por_registro,
    SUM(valor_pago) / COUNT(DISTINCT sk_beneficiario) AS custo_medio_por_paciente
FROM fato_custo
WHERE cid IS NOT NULL
  AND cid <> ''
GROUP BY 1
ORDER BY 4 DESC
LIMIT 20;
EOF

cat > "$Q/q07.sql" << 'EOF'
SELECT
    sk_contrato,
    EXTRACT(YEAR FROM data_competencia)    AS ano,
    SUM(valor_pago)                        AS custo_ano,
    SUM(valor_faturado)                    AS faturado_ano,
    COUNT(DISTINCT sk_beneficiario)        AS beneficiarios_ativos,
    COUNT(*)                               AS registros
FROM fato_custo
GROUP BY 1, 2
ORDER BY 1, 2;
EOF

cat > "$Q/q08.sql" << 'EOF'
SELECT
    sistema_fonte,
    EXTRACT(YEAR FROM data_competencia)    AS ano,
    SUM(valor_faturado)                    AS total_faturado,
    SUM(valor_pago)                        AS total_pago,
    SUM(valor_faturado - valor_pago)       AS total_glosa,
    ROUND(
        100.0 * SUM(valor_faturado - valor_pago) / NULLIF(SUM(valor_faturado), 0),
        2
    )                                      AS pct_glosa,
    COUNT(*)                               AS registros
FROM fato_custo
GROUP BY 1, 2
ORDER BY 2, 5 DESC;
EOF

cat > "$Q/q09.sql" << 'EOF'
SELECT
    sk_beneficiario,
    COUNT(*)                               AS total_registros,
    COUNT(DISTINCT tipo_atendimento)       AS tipos_atendimento,
    SUM(valor_pago)                        AS custo_total,
    SUM(valor_pago_honor)                  AS total_honorarios,
    SUM(valor_pago_filme)                  AS total_filme,
    SUM(valor_pago_co)                     AS total_co,
    MIN(data_competencia)                  AS primeiro_atendimento,
    MAX(data_competencia)                  AS ultimo_atendimento
FROM fato_custo
GROUP BY 1
ORDER BY 4 DESC
LIMIT 100;
EOF

cat > "$Q/q10.sql" << 'EOF'
SELECT
    sk_prestador_executante,
    DATE_TRUNC('year', data_competencia)   AS ano,
    SUM(valor_pago)                        AS custo_ano,
    SUM(SUM(valor_pago)) OVER (
        PARTITION BY sk_prestador_executante
        ORDER BY DATE_TRUNC('year', data_competencia)
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    )                                      AS custo_acumulado,
    COUNT(*)                               AS atendimentos_ano
FROM fato_custo
GROUP BY 1, 2
ORDER BY 1, 2;
EOF

echo "Arquivos criados em $Q:"
ls -1 "$Q"
