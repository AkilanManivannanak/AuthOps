-- When people said an answer was wrong: what was wrong, on how many different documents, and whether those were
-- samples. Each row links to the stored result snapshot by doc_id. The top rows are the next things to fix.
SELECT kind, what, COUNT(*) AS times, COUNT(DISTINCT NULLIF(doc_id, '')) AS documents,
       SUM(CASE WHEN is_sample = 1 THEN 1 ELSE 0 END) AS on_samples,
       MAX(doc_id) AS example_doc_id
FROM feedback
WHERE verdict = 'wrong'
GROUP BY kind, what
ORDER BY times DESC, kind
LIMIT 15;
