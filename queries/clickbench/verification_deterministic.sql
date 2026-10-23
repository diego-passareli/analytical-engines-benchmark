-- Versões determinísticas de consultas do ClickBench, usadas APENAS na verificação
-- de resultados (scripts/check_results.py --queries). As consultas originais usam
-- LIMIT sem ORDER BY (Q18) ou ORDER BY com empates antes de LIMIT/OFFSET, de modo
-- que mais de um conjunto de linhas é uma resposta válida. Aqui, as colunas de
-- agrupamento são acrescentadas ao ORDER BY como critério de desempate.
-- Os tempos do benchmark foram medidos com as consultas originais (queries.sql).
-- Q18
SELECT UserID, SearchPhrase, COUNT(*) FROM hits GROUP BY UserID, SearchPhrase ORDER BY UserID, SearchPhrase LIMIT 10;
-- Q25
SELECT SearchPhrase FROM hits WHERE SearchPhrase <> '' ORDER BY EventTime, SearchPhrase LIMIT 10;
-- Q31
SELECT SearchEngineID, ClientIP, COUNT(*) AS c, SUM(IsRefresh), AVG(ResolutionWidth) FROM hits WHERE SearchPhrase <> '' GROUP BY SearchEngineID, ClientIP ORDER BY c DESC, SearchEngineID, ClientIP LIMIT 10;
-- Q32
SELECT WatchID, ClientIP, COUNT(*) AS c, SUM(IsRefresh), AVG(ResolutionWidth) FROM hits WHERE SearchPhrase <> '' GROUP BY WatchID, ClientIP ORDER BY c DESC, WatchID, ClientIP LIMIT 10;
-- Q39
SELECT URL, COUNT(*) AS PageViews FROM hits WHERE CounterID = 62 AND EventDate >= '2013-07-01' AND EventDate <= '2013-07-31' AND IsRefresh = 0 AND IsLink <> 0 AND IsDownload = 0 GROUP BY URL ORDER BY PageViews DESC, URL LIMIT 10 OFFSET 1000;
-- Q40
SELECT TraficSourceID, SearchEngineID, AdvEngineID, CASE WHEN (SearchEngineID = 0 AND AdvEngineID = 0) THEN Referer ELSE '' END AS Src, URL AS Dst, COUNT(*) AS PageViews FROM hits WHERE CounterID = 62 AND EventDate >= '2013-07-01' AND EventDate <= '2013-07-31' AND IsRefresh = 0 GROUP BY TraficSourceID, SearchEngineID, AdvEngineID, Src, Dst ORDER BY PageViews DESC, TraficSourceID, SearchEngineID, AdvEngineID, Src, Dst LIMIT 10 OFFSET 1000;
-- Q41
SELECT URLHash, EventDate, COUNT(*) AS PageViews FROM hits WHERE CounterID = 62 AND EventDate >= '2013-07-01' AND EventDate <= '2013-07-31' AND IsRefresh = 0 AND TraficSourceID IN (-1, 6) AND RefererHash = 3594120000172545465 GROUP BY URLHash, EventDate ORDER BY PageViews DESC, URLHash, EventDate LIMIT 10 OFFSET 100;
-- Q42
SELECT WindowClientWidth, WindowClientHeight, COUNT(*) AS PageViews FROM hits WHERE CounterID = 62 AND EventDate >= '2013-07-01' AND EventDate <= '2013-07-31' AND IsRefresh = 0 AND DontCountHits = 0 AND URLHash = 2868770270353813622 GROUP BY WindowClientWidth, WindowClientHeight ORDER BY PageViews DESC, WindowClientWidth, WindowClientHeight LIMIT 10 OFFSET 10000;
