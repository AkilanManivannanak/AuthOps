-- How far visitors get: open the app, pick a role, use a tool, tell us whether the AI was right.
SELECT 1 AS step, 'Opened the app' AS stage, COUNT(DISTINCT session_id) AS sessions FROM usage
UNION ALL
SELECT 2, 'Picked a role', COUNT(DISTINCT session_id) FROM usage WHERE role <> ''
UNION ALL
SELECT 3, 'Used a tool', COUNT(DISTINCT session_id) FROM usage
 WHERE action IN ('assist', 'benefit_call', 'appeal_case', 'phone_call', 'long_chart', 'qa_review', 'rule_approve', 'appeal_view', 'x12',
                  'payor_send', 'doc_review', 'agent_run_start', 'approval_outlook')
UNION ALL
SELECT 4, 'Rated an AI answer', COUNT(DISTINCT session_id) FROM feedback
ORDER BY step;
