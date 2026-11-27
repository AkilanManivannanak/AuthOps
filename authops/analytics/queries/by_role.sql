-- Sessions by the role they ended up in. Each session counts once, under the last role it picked;
-- "left before choosing" is only for sessions that never picked one. Sums to the funnel's first step.
WITH last_pick AS (
    SELECT session_id, MAX(ts) AS ts FROM usage WHERE role <> '' GROUP BY session_id
), final_role AS (
    SELECT u.session_id, MAX(u.role) AS role
    FROM usage u JOIN last_pick l ON u.session_id = l.session_id AND u.ts = l.ts
    GROUP BY u.session_id
), per_session AS (
    SELECT session_id, COUNT(*) AS actions FROM usage GROUP BY session_id
)
SELECT COALESCE(f.role, 'left before choosing') AS role, COUNT(*) AS sessions, SUM(p.actions) AS actions
FROM per_session p LEFT JOIN final_role f ON p.session_id = f.session_id
GROUP BY COALESCE(f.role, 'left before choosing')
ORDER BY sessions DESC;
