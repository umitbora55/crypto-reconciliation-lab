# Stage13.1: two bounded replay consistency repairs

Package 0.11.1 retains stage2-v2, schema6 and execution-replay v1. The reviewed
baseline is 0ecf194c80d82f363b1868585787361abab84f57, tree
7535752df07cdad41e02e230a28c6468118588f2. The independent review is input evidence;
its Linux/Python3.12 results are distinguished from this task's own executions.

S13-F1 requires each captured auth attempt link to resolve to an existing decision
and attempt at exactly the same (stream_id, sequence). A contradiction is
REPLAY_INTEGRITY before financial calculation. Existing identity/existence checks
remain. This does not restore a full database, authorize historical activity using
current policy, or verify signatures. A TEST-ONLY rebound pin exercises internal
consistency; the original trusted external pin continues to reject altered bytes.
The defect is not a financial miscalculation or signature bypass.

S13-F2 classifies a RuntimeError from output path canonicalization as REPLAY_OUTPUT
at that boundary only. The existing completed report survives publication failure:
ERROR/2 describes the operation while REPRODUCED/EQUAL or DIVERGED/DIFFERENT,
completion flags and differences remain visible. Input bytes and no-overwrite
publication semantics are unchanged. Python3.12's real symlink-loop RuntimeError
must run unskipped in CI; a narrowly targeted test-owned seam exercises the same
API boundary on other Python versions and is labelled separately.

The only production logic changes are in replay/validation.py and replay/api.py.
Adapter, comparison, worker, financial engine, Store, capture/readers, admission,
policy, cryptography, migrations and all old reference/experiment bytes are kept.
New finite tests and a small release CLI checker cover both repairs in core mode.
There is no runtime dependency or new product feature.

The 858-ID/89-file 0.11.0 scope is separately pinned. Six authorized metadata
literal edits in three old test files must reverse exactly; old assertions and
method bodies remain intact. A separate current contract is written only after
final test files are known. Final verification uses sdist -> extracted source ->
wheel, exact source/installed test identities, core/auth-only profiles and the
immutable 69-case/162-evaluation/373-file financial reference. Actual commands,
failed attempts, CI artifacts, archive checks and HANDOFF stay outside Git.

Baseline full rerun, historical heavy recovery/auth/performance experiments and
frozen generation/training/holdout remain NOT_RUN. Existing small suite tests are
retained. Finish with draft PR #5; independent acceptance precedes any merge.
