# Stage13 decisions

1. Consume two explicit authoritative files and a required external execution
   pin. Keep the existing five-file export unchanged; do not authenticate its
   presentation files or infer an external trust root from self-contained hashes.
2. Reuse pure existing integrity helpers but keep replay validation in its own
   module. The existing DB reader's registry/mirror/legacy checks remain intact.
3. Use an input-only two-table in-memory adapter with unchanged Store.known and
   unchanged engine.reconcile. The saved answer never enters the adapter. This
   preserves original IDs/raw strings/duplicates without ingest or DB restore.
4. Compare complete canonical payloads with typed, deterministic JSON Pointer
   differences. Raw saved bytes retain their separate hash identity. Financial
   mismatch can be a successfully reproduced result.
5. Isolate all data-dependent validation and calculation in a bounded child.
   Keep numeric format/row/byte/JSON/result budgets explicit; do not promise a
   portable hard-memory cap or launch a generic benchmark worker framework.
6. Publish atomically to a fresh canonical destination. Preserve completed
   comparison evidence separately from later output I/O failures.
7. Hash the actual imported implementation for this replay only. Original binary
   identity remains NOT_RECORDED; source signatures and actor authority are not
   newly verified. Same-engine equality does not replace the literal tests or
   independent integer oracle.
8. Preserve778 existing test IDs/assertions, all earlier scope anchors and373
   fixed financial references. Only the three explicitly authorized current
   metadata strings in two old test files change, with exact reversible proofs.
9. First finish focused tests and fixed demo, then seal source and run the normal
   sdist-to-wheel source/installed full gate and small dependency profiles.
   Reuse existing five CI jobs. Do not rerun the accepted baseline full gate or
   frozen experiment. Actual commands/failures and final CI live outside Git.
