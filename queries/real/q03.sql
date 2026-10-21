-- Q03: Custo anual por tipo de atendimento e tipo de despesa
-- Padrão: GROUP BY multi-dimensional, 2 colunas categóricas + ano
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
