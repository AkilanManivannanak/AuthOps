-- When people said the AI was wrong, what was wrong. The top rows are the next things to fix.
SELECT kind, what, COUNT(*) AS times
FROM feedback
WHERE verdict = 'wrong'
GROUP BY kind, what
ORDER BY times DESC, kind
LIMIT 15;
