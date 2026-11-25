-- People's verdicts on AI answers, by tool and by which layer produced the answer (AI or rule checks).
SELECT kind, layer, COUNT(*) AS ratings,
       SUM(CASE WHEN verdict = 'right' THEN 1 ELSE 0 END) AS rated_right,
       ROUND(100.0 * SUM(CASE WHEN verdict = 'right' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_right
FROM feedback
GROUP BY kind, layer
ORDER BY kind, layer;
