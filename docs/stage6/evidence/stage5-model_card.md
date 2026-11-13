# Synthetic triage model card

One L2 LogisticRegression with frozen parameters; no hyperparameter search.
144 world groups, 576 episodes, 1152 visible asset units; actual eligible/label counts are in metrics.json.
72 train / 24 validation / 24 final-test worlds; 24 separate COMBINED_REOPEN challenge worlds.
Target: unresolved_at_horizon at T+24h; not calibrated financial risk, fraud, loss or a required action.

Primary test: No additional benefit demonstrated in this synthetic experiment.
Challenge: No additional benefit demonstrated in this synthetic experiment.

Exact-T twins have different future labels and must receive identical features/scores.
Family timelines, sample sizes and budgets were fixed before final labels. Dependent asset units are not independent statistical samples.
Preprocessing uses train-only medians, all-feature missing indicators and train-only scaling. Original financial text/null remains in evidence.
Training/library parity checks and exact installed dependencies are in training.json; model.json is strict data, never pickle/joblib.
Same model JSON and feature input yield deterministic ranking; retraining bit equality across BLAS/OS is not claimed.
No operational/institutional benefit is inferred. There is no rule fallback or automatic remediation.
