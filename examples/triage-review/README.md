# Historical T-only ranking example

This is an explicit **two-unit subset**, not a complete experiment. It contains
both observed assets in historical test episode `e0297829c0dcfe888`:
`ASSET_A` is OPEN and `ASSET_B` is NO_OPEN_FINDING. No labels, private future plans,
metrics, freeze or lock files are included. The example was selected from the
Stage 5.1 maintenance episode without consulting future labels.

The unchanged historical `0.5.0` JSON model is copied from
`stage5-output/experiment-001/main/model.json`. The selected observations and all
their current/history snapshots come from the historical main feature document.
[selection-manifest.json](selection-manifest.json) records exact original relative
paths, byte sizes, SHA-256 values, selected unit IDs and each packaging-only
transformation. These large original sources are preserved separately; they are
not claimed to be contained in the small example. Model coefficients, feature
values, financial strings/nulls, findings and saved payload bytes are unchanged.
The original full split hash remains bound to the unchanged model.

[features.json](features.json) uses only observations at or before
`T = 2026-11-11T00:00:00Z`. Both actual snapshots, including the earlier observed
history, are included at their original relative `payload_file` paths. Machine
specific live database paths and adapter proof lists are omitted from the
packaging copy; JSON ranking needs the saved feature/model documents, not live
source databases. This omission is explicit in the selection manifest and does
not change the original files.

[features-future.json](features-future.json) is the negative control. It changes
one provenance source time to `H = 2026-11-12T00:00:00Z` while leaving its T summary
unchanged. The real CLI must reject this inconsistency with exit **2** and publish
no successful queue. The valid input must exit **0**, preserving both units,
including NO_OPEN_FINDING. These are validation outcomes, not model-success
metrics or claims of calibrated financial risk.

From a source or extracted source distribution, run the small offline review:

```sh
python scripts/reproduce_review.py --output review-new
```

For an already installed wheel, invoke the same script with its environment's
Python and `--mode installed`. It uses isolated child processes from an outside
working directory and verifies their actual site-packages imports. Installation
may require downloads; the demo, saved-result export and JSON ranking themselves
require no network or API key after installation.
