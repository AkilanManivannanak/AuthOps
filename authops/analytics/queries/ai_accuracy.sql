-- People's verdicts on answers, by tool, by which layer answered (AI or rule checks), and whether the
-- document was one of the built-in samples or a real upload. Sample ratings measure one fixed document.
SELECT kind, layer,
       CASE WHEN is_sample = 1 THEN 'sample' WHEN is_sample = 0 THEN 'real upload' ELSE 'not recorded' END AS document,
       COUNT(*) AS ratings, COUNT(DISTINCT NULLIF(doc_id, '')) AS documents,
       SUM(CASE WHEN verdict = 'right' THEN 1 ELSE 0 END) AS rated_right,
       ROUND(100.0 * SUM(CASE WHEN verdict = 'right' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_right
FROM feedback
GROUP BY kind, layer, CASE WHEN is_sample = 1 THEN 'sample' WHEN is_sample = 0 THEN 'real upload' ELSE 'not recorded' END
ORDER BY kind, layer, document;
