# Gate 2 offline reproduction and evidence boundaries

Run experiment commands from the existing Git checkout with Python 3.12 or 3.14
and the repository's pinned build/auth/AI requirements. Provision these before
disconnecting. The review ZIP contains source bytes, not Git history; a local
clone of the retained checkout preserves commit metadata without network access.
Keep every output directory fresh. Gate1 evidence remains under
`/workspace/validation-evidence`; Gate2 evidence is separately retained under
`/workspace/validation-gate2-evidence`. Historical reports are preserved at
`reports/history/gate1-f3dff8d`. Nothing in these commands changes the historical
875-ID scope or regenerates the frozen ML experiment.

## Verify downloaded evidence before interpreting it

The final delivery directory contains `archive.sha256`,
`archive-verification.json`, `evidence-manifest.json` and the review ZIP. Run:

```sh
sha256sum --check archive.sha256
python /path/to/source/scripts/validation/package_gate2.py --verify crypto-reconciliation-validation-gate2.zip
```

The verifier requires a nonempty exact member inventory and validates each
member's bytes and SHA256. These self-issued hashes establish byte integrity,
not publisher authority. Official URL/retrieval metadata and source semantics
are separately audited. Large generated databases and reinstallable environments
are explicitly omitted. Treasury numeric API bodies have an official reuse
grant and may be included outside Git. SEC raw ZIPs and downloaded site documents
remain local; their exact identities and manual-import instructions are retained.

## Offline real-data replay

With the original raw captures available at their recorded paths:

```sh
python -B scripts/validation/run_gate2_public_data.py \
  --access-root /workspace/validation-gate2-evidence/public-data/access-01 \
  --data-root /workspace/validation-gate2-evidence/public-data/data-02 \
  --policy /workspace/validation-gate2-evidence/public-data/policy-frozen.json \
  --output /tmp/crl-gate2-public-NEW
```

This command snapshots its execution closure, runs from that snapshot in an
isolated child, and checks unchanged source/input identities afterward. It
performs no network access. Missing required raw files must be
imported under the explicit manual procedure in the Gate2 real-data report;
do not substitute copied page examples or invent their provenance. The importer
must retain official URLs, acquisition timestamps, bytes, SHA256 and unknown
publication vintage. Retrieval time is not original publication time.

Interpret the output's separate populations: direct Treasury arithmetic,
authored adaptations of real totals to the native engine schema, SEC layout
checks and deliberate real-plus-synthetic injections. Zero tolerance defines
exact equality. A separate fixed rounding diagnostic never changes a nonzero
residual into exact equality. The independent audit scripts retained in
`independent-public-audit` parse the same raw artifacts separately; they are not
independent financial counterparties.

## Separate research controls

```sh
python -B -m unittest discover -s validation_tests -v
python -B -m validation_lab.identity_reference --output /tmp/crl-gate2-identity-NEW \
  --baseline /workspace/validation-evidence/properties/run-004
python -B scripts/validation/gate2_race.py --source . \
  --schedule unmodified --repeats 20 --output /tmp/crl-gate2-race-NEW
```

The identity run's extra signatures/revisions/key policy are laboratory facts.
They do not supply an independent institutional trust anchor. Keep the preserved
264-case baseline (TP132/FP0/TN120/FN12), the 24-observation enhanced laboratory
matrix, the larger semantic-control roster and finite parser cases separate.
The race witness requires exact admitted test bytes, one expected test ID,
zero skips/xfails/xpasses and actual schedule evidence. Scheduled tests are
diagnostic evidence only; release verification has no scheduling hooks.

## Full source and installed release gates

```sh
.venv-validation/bin/python -B scripts/verify_release.py --profile full --financial \
  --output /tmp/crl-gate2-full312-NEW
.venv-validation314/bin/python -B scripts/verify_release.py --profile full --financial \
  --output /tmp/crl-gate2-full314-NEW
```

These build the allowlisted sdist and wheel, create independent environments,
verify exact expected/discovered/executed 875-ID rosters for source and installed
tests, and execute the 69-case/162-evaluation financial matrix with the immutable
373-file reference. Installation may need package-network access; provision the
pinned dependencies first for a disconnected environment. The raw test logs,
module origins, executed IDs and original exits are part of acceptance.

Run `--profile core` and `--profile auth-only` separately on Python 3.14. Their
full 875 suite status is intentionally NOT_RUN; they verify dependency isolation
and their own release demonstrations. Reuse a verified extracted `--source`
and corresponding `--wheel` from the same build when desired. The new separately
pinned three-file exception composes actual restored historical bytes; old
contracts and expected IDs are not regenerated from the candidate.

## Quiet, bounded performance runs

Stop other task workloads before running these sequentially:

```sh
python -B -m validation_lab.benchmark_gate2 --mode full --output /tmp/crl-gate2-common-NEW
python -B -m validation_lab.benchmark_gate2 --mode triage --output /tmp/crl-gate2-capacity-NEW
```

The first program has a 420-second budget and five paired/interleaved repetitions
at 100, 1,000 and 10,000 events. The second has its own 180-second budget, with
100,000/25,000/50,000 production-adapter attempts. Each child retains the original
60-second maximum and one-GiB memory limit. Exit 3 means PARTIAL, including a
genuine timeout; retain actual kill/wait exit codes and incomplete phase progress.
Do not convert PARTIAL to PASS or silently increase the cap.

Common-output equivalence requires matching validation, input, SQLite settings,
persisted DB/export bytes and integer output. The full evidence/history lane is
not implemented by the references. Neither five local trials nor a successful
smaller capacity probe establishes a production SLA, institutional cost savings,
operational-risk reduction or natural-error recall.

## Final revision and remote CI

The committed decision records the local evidence available at source sealing.
Final commit/PR/CI observations and downloaded-log/artifact verification belong
in the outside-Git `VALIDATION_GATE2_HANDOFF.md` and terminal decision record.
This avoids claiming that a working-tree experiment ran a later Git commit or
creating a commit/CI/documentation feedback loop. Verify that final CI evidence
names the exact delivered head; prior successful CI does not erase earlier RED
records or substitute for the new revision.
