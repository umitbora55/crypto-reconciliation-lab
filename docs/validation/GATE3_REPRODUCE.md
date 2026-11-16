# Gate 3 finite reproduction and evidence boundaries

Gate 3 starts from `6876b384030a7cdab1d35445f66bf874768dcfce` on the
existing validation branch and draft PR #7. The source-sealed Gate 3 decision
belongs in `reports/gate3/DECISION.json`. The later exact delivered commit,
CI observations and final archive identity belong outside Git. Neither replaces
the unchanged Gate 1 or Gate 2 decision at its original observation time.

Use a provisioned Python 3.12 or 3.14 environment, the pinned build/auth/AI
dependencies, the Git checkout and original retained evidence. All outputs must
be fresh. This program does not fetch private data, run frozen ML training,
publish an environment or create a release. Missing originals are a missing
evidence cell, never permission to regenerate plausible records.

## Independent raw-byte and comparison review

The public auditor uses only the standard library; it imports no production or
research parser, normalizer or arithmetic helper. Its chosen corpus is bound by
the separately sealed contract digest, which the caller must retain independently.

```sh
python -B scripts/validation/audit_gate3_public.py \
  --raw-root /workspace/validation-gate2-evidence/public-data \
  --contract contracts/gate3-public-corpus.json \
  --expected-contract-sha256 db6467497e31244fcd7b679485cb457257a6dfd4567ae4277bcf6d33c6b4f575 \
  --output /tmp/gate3-public-NEW.json
python -B scripts/validation/audit_gate3_comparison.py \
  --evidence-root /workspace/validation-gate2-evidence/benchmark/common-full \
  --source-root . --output /tmp/gate3-comparison-NEW
python -B scripts/validation/audit_gate3_trust.py \
  --protocol /workspace/validation-gate3-evidence/trust/protocol.json \
  --output /tmp/gate3-trust-NEW
```

The exact corpus requires the original Treasury API bodies, SEC ZIPs, original
official documentation and selected Gate 2 result/row-link records. The contract
lists their individual paths, sizes, digests and record-identity inventories.
SEC ZIPs and downloaded site documents are retained locally and omitted from
the shareable archive because redistribution permission is not established.
Treasury numerical API bodies have an official reuse grant. Follow the strict
manual acquisition procedure in `GATE2_REPRODUCE.md`; exact official links,
capture metadata and unknown publication vintage must survive import.
The comparison audit additionally requires the original 45 trial records,
commands, inputs, metrics and retained small artifacts. The trust audit requires
the original Gate 1 inputs and Gate 2 LAB reference records listed in its frozen
protocol. Local absolute paths in command records are observations; any replay
path mapping must be explicit and separately recorded.

## Capacity and instrumentation

Wait until other task workloads are idle, then execute the fixed protocol once:

```sh
python -B -m validation_lab.gate3_capacity \
  --history /workspace/validation-gate2-evidence/benchmark \
  --output /tmp/gate3-capacity-NEW
```

The original recorded attempt failed in the controller while sampling a disappearing
SQLite journal. Its exact source snapshot and failed extended attempt remain in
`capacity/run-001`. The separately preregistered continuation is reproduced with
`--protocol contracts/gate3-capacity-continuation.json`; it requires the selected
original run-001 input paths and counts all retained files in the capacity parent
directory. Use an isolated restored evidence layout and fresh output. The current
default command uses the repaired controller and is a new experiment; it does not
relabel the original failed attempt. See the exact command and budget/omission
requirements in `reports/gate3/CAPACITY.md`.

The protocol sets one worker and finite aggregate wall/CPU/memory/disk limits.
Original 60-second attempts and extended diagnostic attempts are separate rows.
The latter cannot establish the former's SLA. Retain actual kill/wait exits,
phase progress, sampled resources and direct postprocess SQLite recovery-copy
readback. An interrupted worker's final CPU/RSS remains NOT_MEASURED. Database
readback describes that stopped trial, not institutional RPO. The 10k paired
instrumentation comparison has one pair; it estimates an observed incremental
cost under that order and host load, not a reliable population overhead.
An ordinary 100k ingestion trial does not extend offline replay's 10,000 eligible
receipt and default 30-second worker contract.

## Separate test inventories and distributions

```sh
.venv-validation/bin/python -B scripts/verify_release.py --profile full --financial \
  --output /tmp/gate3-full312-NEW
.venv-validation314/bin/python -B scripts/verify_release.py --profile full --financial \
  --output /tmp/gate3-full314-NEW
python -B -m unittest discover -s validation_gate3_tests -v
```

The full release gates build an allowlisted sdist and wheel, then verify exact
875-ID source and isolated installed rosters and the 69/162/373 financial scope.
New Gate 3 research tests belong exclusively to `validation_gate3_tests`; they
are not added to the protected 875. The retained research driver seals their
static expected IDs, compares discovered/executed IDs and rejects every failure,
error, skip, expected failure or unexpected success. The old 134 research methods
are not rerun or relabelled as new Gate 3 work. Core/auth-only profiles intentionally
do not execute the full 875; their own dependency-isolation checks remain separate.

Adversarial evidence includes the preregistered catalog, frozen negative inputs,
old-boundary observations and fixed-boundary observations. Preserve all failed
attempts with original commands, exits and logs; a later PASS does not erase them.

## Delivery and interpretation

The new-head CI audit checks actual five-job identities, logs, four artifact ZIPs,
API digests, source manifests and protected test scope. A prior-head green run is
not acceptance. The final external decision may be GATE3_EVIDENCE_READY only when
all mandatory finite checks and new-head CI have passed; bounded capacity
timeouts remain explicitly PARTIAL.

Verify the final ZIP using `scripts/validation/package_gate3.py --verify PATH`
and compare its bytes/SHA/member count to the outside manifest. The archive
cannot contain its own later final checksum. Its inclusion/omission ledger states
which originals are required for complete replay. Hashes prove byte integrity;
they do not establish external economic truth, independent institutional
authority, execution attestation, regulatory compliance, risk reduction or savings.
