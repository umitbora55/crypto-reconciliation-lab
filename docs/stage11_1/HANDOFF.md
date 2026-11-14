# Stage 11.1 source handoff

This maintenance release is 0.9.1, starting from reviewed task head
`296a7c187cb516b2ecdbc030ebc8321a5cce4647`. It repairs only
[S11-F1](f1.md), the later-replay/original-acceptance contradiction, and
[S11-F2](f2.md), lossy SQL identities in the derived browser transport.
The [maintenance contract](contract.md) explains the scope and old-page boundary;
[decisions](decisions.md) records the choices.

## Implemented behavior

The verifier rejects an effect-referencing attempt that precedes the claimed
original COMMITTED attempt. It uses durable integer order and recorded relations,
without requiring that effect-less attempts come later or interpreting timestamps
as authority. The exact reviewed promoted-replay witness now receives semantic
`DELIVERY_CAUSALITY` / exit 2 with current valid assets.

The derived offline data transports the declared integer identity columns as
exact decimal text before JavaScript parsing. Adjacent receipt, attempt and
decision IDs above `2**53` stay distinct, including the supported SQL maximum.
The verifier reconstructs the transport independently. Raw saved run, capture,
external pins, signed bytes, authoritative integer types and financial quantities
retain their original semantics. Old 0.9.0 page assets can receive controlled
`PRESENTATION_INTEGRITY`; re-export into a fresh directory from available closed
DB/materials instead of rewriting old evidence.

## Preserved and tested source scope

The 0.9.1 frozen scope contains **661 unique test identities**: all 641 reviewed
identities plus 8 causality regressions, 6 identity-transport regressions and 6
release-control regressions. No old test method or assertion AST changes. The
only old fixture edits are two current release/scope metadata expressions and
the independently encoded `refresh` view fixture, with exact reversible diffs in
[fixture changes](fixture-changes.md). Historical scope anchors remain immutable;
0.9.0 is a separate pinned ancestor.

The same F1 regression file ran RED against real 0.9.0 (4 failures, 4 positive
passes), then GREEN (8 tests) against the repair. The same final F2 file ran RED
against real 0.9.0, then GREEN (6 tests). Their actual commands, file hashes,
origins and result distinctions are in the finding records and external task
evidence. The 31 existing provenance UI/verifier tests passed with the narrow
fixture update. A focused release check ran 26 tests successfully. Its independent
small CLI hook observed rotation 0, promoted replay 2/DELIVERY_CAUSALITY, supported
large identities 0, and tampered transport 2/PRESENTATION_INTEGRITY.

Financial rule `stage2-v2`, schema 5, admission/auth runtime, policy/crypto,
authoritative v1 contracts, old recovery/source-auth scopes, the 373-file financial
reference and frozen experiment are outside this change. Run-creation authority
remains `NOT_RECORDED`; financial recomputation remains `NOT_PERFORMED`.

## Distribution and verification procedure

The allowlisted source archive includes the new fixed scope, maintenance helper
and these documents. The wheel is built only from the safely extracted sdist.
The release gate checks expected, discovered and actually executed unique test
IDs, zero skips/failures, source versus installed package bytes and import origins.
It retains the existing core, auth-only and full profiles, 10-group/24-case
provenance demo, recovery/source-auth checks, no-AI paths and 69/162/373 financial
comparison. Full source and installed, and auth-only installed, additionally
execute four bounded maintenance CLI controls. Core checks dependency refusal
before output; its auth-dependent controls remain `NOT_RUN`.

```sh
python3 scripts/build_release.py --output build-new
python3 scripts/verify_release.py --source build-new/sdist/crypto_reconciliation_lab-0.9.1 --wheel build-new/dist/crypto_reconciliation_lab-0.9.1-py3-none-any.whl --output release-full-new --profile full --financial
```

Use the actual `source_root` and wheel paths recorded by the build if they differ
from the example. Run core/auth-only against the same extracted source and wheel
in separate new output directories. Only the requested full financial cell runs
the financial matrix; other cells explicitly retain `NOT_RUN` for that matrix.
No gate invokes main-experiment generation, training or final holdout evaluation.

This source handoff is sealed before final distribution/CI execution. Real final
commands, exits, import origins, browser observations, preservation records,
archive identities, final task SHA, draft PR #3 and CI artifacts are delivered
outside Git in `stage11_1-output/HANDOFF.md` and its evidence records. Reading this
source document alone does not establish that a subsequent CI or browser check
ran. Failed and partial attempts remain in that external record. Main is not
merged by this task, and no tag, release or PyPI publication is authorized.
