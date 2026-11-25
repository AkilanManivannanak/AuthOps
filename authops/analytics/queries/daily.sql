-- Activity per day.
SELECT day, COUNT(DISTINCT session_id) AS sessions, COUNT(DISTINCT NULLIF(who, '')) AS people, COUNT(*) AS actions
FROM usage
GROUP BY day
ORDER BY day;
