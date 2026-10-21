-- Q09: Top-100 beneficiários por custo total acumulado (todo o histórico)
-- Padrão: GROUP BY chave de alta cardinalidade (sk_beneficiario ~milhões),
--         múltiplas agregações, ORDER + LIMIT — teste de hash-aggregate grande
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
