# Fixed replay demonstration and release coverage

`demo-execution-replay` runs seven actual child CLI commands. Its catalog is a
named package resource, `replay/demo_catalog_v1.json` (1,231 bytes; SHA-256
`a479fae4a5c27be73d5ee8a6405e23daec16e1f04e80da34a7e2d530be7b99ca`).
The release gate independently fixes the seven identities, exits, reason codes,
comparison states and six literal financial findings. It does not accept the
producer's `expected` labels as an oracle. Missing, duplicate, or coherently
mislabeled evidence fails the gate.

| Case | Actual CLI expectation | Comparison |
|---|---|---|
| clean | `REPRODUCED`, 0, `REPLAY_REPRODUCED` | EQUAL |
| custody_difference | `REPRODUCED`, 0, `REPLAY_REPRODUCED` | EQUAL; financial difference remains +1 |
| old_cut_offline | `REPRODUCED`, 0, `REPLAY_REPRODUCED` | EQUAL after the original source changes and is removed |
| wrong_identity | `ERROR`, 2, `REPLAY_INTEGRITY` | NOT_EVALUATED |
| numeric_divergence | `DIVERGED`, 1, `REPLAY_DIVERGED` | DIFFERENT at `/ledgers/ASSET_A/liability` |
| trace_divergence | `DIVERGED`, 1, `REPLAY_DIVERGED` | DIFFERENT at `/ledgers/ASSET_A/trace/0/balances_after/I1` |
| protected_recorded | `REPRODUCED`, 0, `REPLAY_REPRODUCED` | EQUAL for genuine 0.10.1 input |

The ordinary fixtures observe each `execution_id` from the recorded API return
before export. All three temporary source databases are actually removed before
the first verifier command. The old-cut source receives a later custody report
and a distinct recorded result before removal. Numeric and trace sensitivity
cases change only the saved financial result and its binding, preserving captured
table inputs. Their new external pins are explicitly TEST-ONLY self-consistent
fixture pins. This is a comparison sensitivity check, not evidence of external
database completeness.

The protected pair is copied byte-for-byte from a focused capture made by the
unchanged 0.10.1 package at source commit
`0aa26865d5a78d6c051e1c26ad6387bdc29c8abc`, request `before-rotation`.
Its recorded return supplied the independent fixed demo pin
`b4ef410ef6066b2468a7049d8750aead659f7a889dd7087c006464cfe50ac0fd`.
The capture-generation record has SHA-256
`c647e63ff43b6ccee9448d8f94990849e0a14ffbeb33840fd6c8e713921e7515`.
The demo never generates this protected pair with the new recorder and never
invokes signature verification when replaying it.

| Packaged historical resource | Bytes | SHA-256 |
|---|---:|---|
| `replay/fixtures/protected-context.json` | 138090 | `db18fa42e2f81140172745a3a6f993221d9d4f2462dad44615044c8a0efe099e` |
| `replay/fixtures/protected-run.json` | 36958 | `14c675e3bdb3106451c069915db22095e9cacf26c1ab9e674b64d04754738dd0` |

Every command preserves argv, cwd, start/finish times, actual exit, raw stdout and
stderr. The gate binds these logs, exact input bytes, report identities and the
current replay's module bytes to the source or installed package import origin.
Original executable identity remains `NOT_RECORDED`; historical capture metadata
does not add an authorization or executable claim to the input contract.

Full release profiles run source and isolated installed demonstrations and retain
the existing suite's real timeout-child termination evidence. Core and auth-only
profiles run the seven-case installed demo; core has neither AI nor auth extras.
Non-full suites and timeout experiments remain `NOT_RUN`. The CI workflow keeps
its existing five jobs and action pins. It adds bounded JSON/Markdown, CLI logs,
two-file inputs and timeout records to the existing artifacts; no source database
is included in these replay demo records.

The 0.11.0 test inventory is authored once after declared test files are final.
Normal verification checks its immutable pin; it never discovers an expected
inventory and then treats that inventory as an independent acceptance baseline.
All 778 prior identities remain. The only edits to prior test files are the three
literal metadata lines documented in [fixture-changes.md](fixture-changes.md).
