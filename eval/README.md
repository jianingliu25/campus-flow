# Evaluation data, not evaluation results

`development/qa_set.json` contains 20 annotated questions covering the six historical
templates, four preset actions, simple responses, duplicate notices, unknown time,
timezone conversion and unsafe requests. Reference: 2026-10-12 09:00 Asia/Shanghai.

M1 validates data shape and references only. It does not run these questions through
SMOA, and reports no accuracy or score. A separate frozen holdout corpus and actual
model/ablation runs will be added in M8, after the task semantics are stable.
