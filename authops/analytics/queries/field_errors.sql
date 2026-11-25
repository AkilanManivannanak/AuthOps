-- Error analysis from the review queue: fields where reviewers disagreed with what the extractor read.
SELECT field, COUNT(*) AS reviews,
       SUM(CASE WHEN (verdict IN ('correct', 'absent')) = (auto_verdict IN ('correct', 'absent')) THEN 0 ELSE 1 END)
           AS reviewer_disagreed,
       SUM(CASE WHEN auto_verdict IN ('wrong', 'missing') THEN 1 ELSE 0 END) AS extractor_wrong,
       SUM(CASE WHEN auto_verdict IN ('wrong', 'missing') AND verdict IN ('wrong', 'missing') THEN 1 ELSE 0 END)
           AS caught_by_reviewer
FROM qa_labels
GROUP BY field
ORDER BY extractor_wrong DESC, reviews DESC;
