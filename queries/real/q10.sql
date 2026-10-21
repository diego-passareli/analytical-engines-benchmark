-- Q10: Custo acumulado corrente por prestador executante (função de janela)
-- Padrão: SUM(...) OVER (PARTITION BY ... ORDER BY ...) — window function com agregação
--         Este é o query mais complexo e testa suporte a funções de janela.
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
