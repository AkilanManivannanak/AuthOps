-- The pages and actions people actually use.
SELECT page, action, COUNT(*) AS times, COUNT(DISTINCT session_id) AS sessions
FROM usage
WHERE action <> 'view'
GROUP BY page, action
ORDER BY times DESC
LIMIT 15;
