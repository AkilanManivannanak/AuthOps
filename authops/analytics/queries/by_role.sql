-- Who uses the app, by the role they picked.
SELECT CASE WHEN role = '' THEN 'not chosen yet' ELSE role END AS role,
       COUNT(DISTINCT session_id) AS sessions, COUNT(*) AS actions
FROM usage
GROUP BY CASE WHEN role = '' THEN 'not chosen yet' ELSE role END
ORDER BY sessions DESC;
