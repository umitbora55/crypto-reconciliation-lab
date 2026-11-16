# Error detection — Gate 2 revision, 16 November 2026

The canonical **264 FULLY_SYNTHETIC observations remain TP132/FP0/TN120/FN12**.
All 12 false negatives are same-count identity substitutions with unchanged
observable amounts. They are NOT_IDENTIFIABLE_WITH_GIVEN_INPUTS; no relabeling
removes them. Natural-error precision and recall have not been measured.

An optional laboratory identity-reference contract supplies additional ordered
IDs/content digests, signed scope/revision facts and key lifecycle policy. Its
separate 24-observation clean/substitution matrix is TP12/FP0/TN12/FN0. It is a
subset of 240 laboratory reference controls, not a replacement for the original
264 observations. The authority facts are generated and controlled by the lab;
no independent institutional trust anchor was supplied. The extra reference
availability and lifecycle cost is part of that changed input contract.

Finite parser/encoding/time/correction-boundary controls are recorded separately.
They neither add confusion-matrix rows nor establish universal correctness.
The independent audit's oracle-strengthening and retained RED/GREEN evidence
are disclosed in the [Gate2 detection report](gate2/ERROR_DETECTION.md).

The distinct SEC-derived injection population is TP120/FP0/TN180/FN60 across
360 observations from 30 source rows. Its schema-valid identity and quantity
changes remain false negatives for schema-only checks. Real public-source
observations carry no natural anomaly truth labels and no real-world recall.

See [separate scorecards](gate2/scorecards/),
[real-data boundaries](REAL_DATA_VALIDATION.md), and the
[byte-preserved Gate1 detailed report](history/gate1-f3dff8d/ERROR_DETECTION.md).
The financial engine and frozen ML experiment were not changed or retrained.
