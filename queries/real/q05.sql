-- Q05: Sazonalidade — custo por mês-do-ano e turno de atendimento
-- Padrão: EXTRACT em duas dimensões + filtro NOT NULL + GROUP BY
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
