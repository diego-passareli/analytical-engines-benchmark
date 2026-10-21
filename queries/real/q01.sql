-- Q01: Custo total pago por mês (série temporal completa)
-- Padrão: GROUP BY DATE_TRUNC sobre tabela inteira — varredura full-scan
SELECT
    DATE_TRUNC('month', data_competencia)  AS mes,
    SUM(valor_pago)                        AS total_pago,
    SUM(valor_faturado)                    AS total_faturado,
    COUNT(*)                               AS registros
FROM fato_custo
GROUP BY 1
ORDER BY 1;
