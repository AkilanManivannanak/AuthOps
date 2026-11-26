-- Review queue: per field, how often the extractor was wrong (per the answer key), how often reviewers caught it,
-- and how often a reviewer's verdict differed from the answer key (a reviewer error or an answer-key problem).
SELECT field, COUNT(*) AS reviews,
       SUM(CASE WHEN auto_verdict IN ('wrong', 'missing') THEN 1 ELSE 0 END) AS extractor_wrong,
       SUM(CASE WHEN auto_verdict IN ('wrong', 'missing') AND verdict IN ('wrong', 'missing') THEN 1 ELSE 0 END)
           AS caught_by_reviewer,
       SUM(CASE WHEN (verdict IN ('correct', 'absent')) = (auto_verdict IN ('correct', 'absent')) THEN 0 ELSE 1 END)
           AS differs_from_answer_key
FROM qa_labels
GROUP BY field
ORDER BY extractor_wrong DESC, reviews DESC;
