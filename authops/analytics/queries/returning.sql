-- Signed-in people who came back on more than one day.
SELECT COUNT(*) AS returning_people
FROM (SELECT who FROM usage WHERE who LIKE 'acct:%' GROUP BY who HAVING COUNT(DISTINCT day) > 1) AS r;
