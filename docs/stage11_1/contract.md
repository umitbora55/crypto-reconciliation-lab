# Stage 11.1 maintenance contract

Package 0.9.1 repairs two bounded defects in the Stage 11 reader and its derived
offline presentation. The reviewed starting source is 0.9.0 at
`296a7c187cb516b2ecdbc030ebc8321a5cce4647`. The financial rule remains `stage2-v2`,
SQLite remains schema 5, and all authoritative v1 formats remain unchanged.
The historical [Stage 11 contract](../stage11/provenance-contract.md) remains an
immutable account of that release; the two clarifications below govern 0.9.1.

## Original acceptance and replay causality

The verifier derives each selected effect's sole original `COMMITTED` attempt
and recorded `CURRENT` decision from the captured relationships. Any other
attempt that references that existing effect must follow the original attempt
in the durable integer attempt-ID order. A later replay cannot be relabeled as
the original acceptance while an earlier effect-referencing attempt remains.
This is a local causality constraint supplied by append-only admission history,
not a trusted wall clock or the unrecorded authorization cut of a financial run.

The original attempt need not be the earliest attempt of every kind at the
position: an earlier effect-less `GAP` is possible. The reader does not require
an unselected whole stream or infer an absent run-creation authorization cut.
Detected inconsistent relationships remain exit 2 even when a signed source file
is also missing. Missing material alone retains the existing partial exit 3.

## Lossless browser identities

SQLite positive identifiers remain valid through `2**63 - 1`. Row-count limits
do not reduce that numeric domain. Authoritative JSON retains its integer types:
`run.json`, `capture.json`, expectations, their digests and signed materials are
not rewritten as strings to work around JavaScript Number precision.

Only the derived `data.js` presentation uses an exact identity representation
prepared before JavaScript `JSON.parse`. Physical receipt, attempt and decision
primary and foreign keys must retain distinct values in labels, selection,
filters, maps/sets, detail JSON and source-line relationships. Converting an
already rounded Number back to a string or BigInt cannot meet this requirement.
Financial decimal strings, hash identifiers and downloaded original bytes stay
unchanged. The verifier reconstructs the expected transport independently from
the raw captured evidence and checks the fixed local assets byte for byte.

The browser remains a read-only, network-free view. It does not import a verifier
result or certify its own export. Hostile input and prototype keys stay data.
The original limits, deterministic serialization and arbitrary-asset rejection
remain enforced.

## Old offline pages

A 0.9.0 bundle with the old, lossy page assets can receive controlled
`PRESENTATION_INTEGRITY` / exit 2 from the 0.9.1 reader. This means that its derived
presentation does not satisfy this reader's trusted asset/transport contract;
it does not establish that its unchanged financial payload or signatures are
invalid. The reader does not silently upgrade a bundle or weaken asset checks.

When the closed source database and original source materials are available,
export a fresh 0.9.1 bundle into a new directory and verify it with the appropriate
external expectations. Preserve the old bundle and verification record. An old
verification result cannot be attached to a newly generated manifest.

## Limits retained

`run_creation_authorization_cut=NOT_RECORDED` and
`financial_recomputation=NOT_PERFORMED` remain visible after successful
verification. A controlled negative fixture may update only its explicit capture
observation pin and dependent presentation/manifest to exercise semantic checks;
this does not imply authority to change a real operator's trust input. Neither
repair changes ingestion, admission, policy/crypto, financial calculation, schema,
the earlier reviewer, or the frozen experiment.
