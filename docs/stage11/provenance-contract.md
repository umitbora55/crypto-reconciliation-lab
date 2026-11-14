# Run provenance bundle v1

This contract precedes the Stage 11 implementation. It describes a bounded,
offline explanation of one saved financial run and relationships observed in one
closed schema-5 database capture. It does not recompute balances, change a saved
run, certify a publisher's institutional identity or prove the financial truth of
a signed quantity. Existing financial/review/triage v1, source-auth v1 and
recovery v2 remain unchanged.

The claim is: the selected saved run's unchanged listed evidence is associated
with delivery and authorization rows observed in the reviewed closed capture,
under the separately selected operator policies and capture observation pin.
`run_creation_authorization_cut` is always `NOT_RECORDED`.
`financial_recomputation` is always `NOT_PERFORMED`.

## Three independent identities

1. `run.json` contains the exact UTF-8 encoding of the selected SQL `runs.payload`
   TEXT value. Its SHA-256 is a raw byte identity. Existing `run_id` is the SHA-256
   of the financial model's canonical parsed payload, excluding an added run ID.
   These identities must not be substituted for one another. Findings are named
   by run ID plus zero-based ordinal and checked comparison, asset and scope.
2. `capture.json` contains one canonical SQL projection from the same read-only
   transaction that read the run. Its canonical digest identifies an operator's
   observed projection, including all physical candidates for every required
   receipt hash. The captured database byte SHA-256 and size identify the source
   file; without that file they do not cryptographically prove the projection.
3. A separate `provenance-expectations-v1` file is explicitly supplied by the
   reviewer. It pins run, raw bytes, profile, configuration, capture and, for a
   protected capture, receiver and the complete accepted policy activation map.
   Bundle contents, public keys, a self-computed manifest or an exporter status
   are not trust roots.

## Canonical bytes and material bytes

Let `C(value)` be UTF-8/ASCII bytes from JSON with keys sorted, separators `,` and
`:`, `ensure_ascii=True` and `allow_nan=False`, with no final newline. Duplicate
keys, lone Unicode surrogates, nonfinite numbers and excessive depth are rejected
before use. Structural counters and IDs use real JSON integers; booleans are not
integers. SQL BLOB columns are represented as lowercase hexadecimal strings;
SQL TEXT columns retain their exact text, integers remain integers and SQL NULL
becomes JSON null. Row arrays use their table's primary-key order; composite keys
are lexicographic. Only the projection's outer JSON is canonicalized: embedded
SQL TEXT and BLOB identities are not silently normalized.

`capture_digest = SHA256(C(capture))`. `configuration_digest` retains the existing
financial model's canonical configuration digest. Policy hashes retain the
source-auth canonical policy definition. Snapshot SHA-256, envelope bytes, signed
payload bytes, line bytes and `run_payload_sha256` are hashes of their exact raw
bytes. Re-serialized JSON is never substituted for an original signed file.

## Bundle files and manifest

The directory contains:

- `run.json`: original saved payload bytes.
- `capture.json`: canonical capture projection described below.
- `report.json`: a machine-readable explanation of saved findings and observed
  links; a view to check against the independent reader, not its scope oracle.
- `materials/policies/<policy_hash>.json`: original SQL policy TEXT as UTF-8.
- `materials/envelopes/<endorsement_id>.json`: original DSSE envelope BLOB bytes.
- `materials/snapshots/<snapshot_hash>.jsonl`: full externally supplied source
  snapshot bytes, when present. Missing material is explicitly reported.
- `index.html`, `app.js`, `style.css` and `data.js`: a safe offline explanation.
- `manifest.json`: `format: "run-provenance-bundle-v1"`, selected `run_id` and
  exact member inventory `files`, mapping relative member paths to
  `{ "bytes": integer, "sha256": lowercase_hex }`.

The manifest inventories every regular bundle member except itself; duplicate,
absolute, parent-traversing, symlink or escaping paths are rejected. A bundle's
external verification-record binding uses the raw manifest SHA-256. The manifest
does not authenticate itself or authorize policy. The physical database is never
included. A verification record belongs outside the sealed directory and must
name this manifest digest; exporting or rendering the page never asserts that
verification already succeeded.

The three static presentation resources must equal the installed reader's trusted
resource bytes. `data.js` is exactly the ASCII concatenation
`window.PROVENANCE_DATA = JSON.parse(` + `C(C(data).decode("ascii"))` + `);\n`,
where `data` has exactly `run`, `capture`, `report` and `materials` keys. The first
three values are the parsed corresponding JSON files; `materials` maps each actual
`materials/` bundle member to its raw byte size/SHA-256. The verifier derives and
compares this wrapper independently. JSON.parse preserves keys such as `__proto__`
as data rather than object-literal prototype semantics. Rehashed arbitrary page
scripts or injected member paths therefore cannot be accepted as this format's
trusted review page.

## Capture projection

The exact top-level fields are `format: "run-provenance-capture-v1"`,
`schema_version: 5`, `database: {"bytes": integer, "sha256": digest}`,
`configuration` and `tables`. The following table names are present even if their
arrays are empty. Each row has the exact schema-5 column names and the typed
representation above; invented columns or duplicate primary keys are invalid.

| Table | Projection selection |
|---|---|
| `receipts` | Every physical row whose receipt_hash is required by the immutable run; no preferred/first/latest row |
| `records` | Record IDs listed in the run evidence, including correction and target records |
| `admission_streams` | Streams containing the selected receipt effects |
| `delivery_effects` | Effects whose core_receipt_id is any selected physical candidate |
| `delivery_attempts` | Every attempt at those selected `(stream_id, sequence)` effect positions |
| `auth_configuration` | The database's zero or one protection row |
| `auth_policy_activations` | Complete activation history from epoch 1 through the observed head |
| `auth_policy_snapshots` | Exact union of policy snapshots referenced by those activations |
| `auth_keys` | Complete historical persistent key registry implied by activated policies |
| `auth_streams` | Owners of the selected streams |
| `auth_delivery_links` | Original links at the selected effect positions |
| `auth_attempt_links` | Links for the selected attempt IDs |
| `auth_decisions` | Union of decisions referenced by original and attempt links |
| `auth_endorsements` | Endorsements referenced by those decisions |

Unrelated rejection attempts and unrelated run/stream history are outside this
single-run projection; no claim of a full database audit is made. Exporter schema,
saved findings/evidence and correction mirror checks may reject malformed SQL
input without adding those mirror tables to the portable projection. The reader
uses the immutable run itself for required scope.

Required run scope is independently derived from all saved evidence entries,
record receipt references, raw receipt entries, quarantined-receipt identities,
finding/issue evidence links and ledger correction/target links. A dangling or
wrongly typed reference is invalid, as is a missing required receipt or record.
An empty exporter inventory is never evidence that no work is required. Every
saved record and raw/quarantined receipt must bind to its content-derived ID;
all financial state, outcome, difference and explanatory data remain unchanged.
This first version requires at least one listed receipt in the saved run for
provenance verification. A valid financial run with no listed receipt evidence
remains a saved financial result, but cannot support this source-link claim;
the verifier returns exit 2 / `NO_LISTED_EVIDENCE`, never an empty-inventory success.

For each candidate the reader follows its unique effect, the effect's sole
COMMITTED attempt and original auth delivery link, original CURRENT decision,
endorsement, activated policy and signed source line. It checks receipt/effect
IDs, raw content, disposition/core result, stream/sequence, plan and owner fields
and all corresponding original relationship identities. Replays and later
decisions are displayed separately and cannot replace an original decision.
A physical candidate ID is only a local row observation, never a global logical
transaction ID or proof that the candidate existed when the run was created.

Complete candidate retention ultimately depends on the external capture pin.
Without the DB bytes, a verifier cannot independently enumerate omitted SQL rows.
A semantic negative test may explicitly repin a controlled malformed projection
to exercise its relationship checks, but this is not a claim that an adversary
can change the actual operator's pin.

## External expectations

Exact fields:

```json
{
  "format": "provenance-expectations-v1",
  "profile": "protected",
  "run_id": "<canonical saved run digest>",
  "run_payload_sha256": "<exact run.json byte digest>",
  "configuration_digest": "<configuration digest>",
  "capture_digest": "<canonical capture projection digest>",
  "receiver": "<operator-selected receiver>",
  "policy_head": {"epoch": 4, "policy_hash": "<head policy digest>"},
  "policies": [
    {"epoch": 1, "policy_hash": "<policy 1 digest>"},
    {"epoch": 2, "policy_hash": "<policy 2 digest>"},
    {"epoch": 3, "policy_hash": "<policy 3 digest>"},
    {"epoch": 4, "policy_hash": "<policy 4 digest>"}
  ]
}
```

Protected epochs are unique, contiguous and ordered from 1 through the explicit
head. Every policy body, predecessor epoch/hash, source namespace/capability and
immutable key identity is checked against this external map. Persistent keys
are exactly the union of activated policy keys with their first epoch. Revocation
is permanent; current key state is derived from the pinned capture head, while
the original acceptance uses its own recorded epoch. Unactivated snapshots cannot
expand the trusted inventory or hide a later accepted revocation.

For `profile: "legacy"`, `receiver` and `policy_head` are null and `policies` is
empty. Run, raw payload, configuration and capture pins are still mandatory. The
captured protection configuration and auth tables must actually be empty. A
protected expectation cannot be downgraded by deleting protection metadata or
links. Unsigned legacy is a visible limited review, never protected verification.

Expectations must be a regular external file, not a bundle member or a symlink
resolving into the bundle. The exporter does not emit a trusted expectations file.
Any optional suggestion must be a separate `UNTRUSTED_TEMPLATE`. The bounded demo
may act as its own explicit TEST-ONLY operator: it chooses known policy/run values
and observes its own closed capture before verification, without trusting an
untrusted bundle to create its own authority.

## Closed read and bounded materials

The exporter accepts `--db`, `--run-id`, `--materials` and a new `--output` path.
It opens a regular, non-symlink, closed SQLite copy read-only, checks the expected
schema-5 layout without migration, and reads the saved run plus all projected
relations in one read transaction. It does not open Store or call admission,
ingest, reconciliation or save_run. WAL, SHM and journal sidecars, file replacement,
hash changes or sidecar-inventory changes reject the capture. Source identity is
checked before and after reading and before publication. The output is built in
a sibling temporary directory and atomically renamed only after export succeeds;
an existing target is never overwritten and failed builds are not delivered.

The source-material directory supplies `snapshots/<snapshot_hash>.jsonl` files.
Every present signed feed is checked in full against its signed plan: exact SHA,
byte count, line count and `utf8-lf-jsonl-v1` framing. A saved prefix cannot stand
in for a whole file or be extended by invented suffixes. A missing file is missing
material; a supplied prefix or malformed/hash-wrong file is inconsistent evidence.
Each line retains exact bytes and must match the captured effect at its one-based
sequence, including the single terminal LF. Original envelopes and policies are
already recorded in DB; the exporter retains those original bytes.

Limits are finite and explicit: one database no larger than 256 MiB; one run and
each JSON member at most 8 MiB; capture at most 32 MiB; 100,000 projected rows in
total; 1,024 bundle files; 128 MiB total bundle bytes; generated `data.js` at most
64 MiB (including escaped nested text); JSON depth 32 and at most
200,000 structural nodes for provenance JSON. Existing source-auth limits remain
stricter where applicable: envelope 128 KiB, signed payload 64 KiB, policy 128 KiB,
snapshot 16 MiB, 10,000 lines, 64 KiB per line and its unchanged 20,000-node parser
limit. A protected capture has at most 1,024 activated epochs. Material enumeration
and cumulative bytes are bounded before expensive
parsing. No dependency limit is relaxed to admit a provenance package.

## Independent verifier, states and exits

`verify-provenance --bundle PATH --expectations OUTSIDE_FILE` requires neither
source DB nor network. It must not import/call the exporter, demo, financial
engine or mutable auth admission to infer expected relationships. Existing pure
parse, hashing, schema-description, policy and crypto helpers can be reused;
the new reader independently derives run scope and traverses table relationships.
It is generic for valid publisher, asset and namespace names and bounded policy
histories with more than three epochs; it is not the old fixed seed-19 experiment
reader. Core import/help remains usable without optional AI/auth dependencies.

Verification order is external identity, exact bundle membership, raw/canonical
run identity, independently listed scope, capture pin, available full signed
bytes, signature and policy/capability bindings, then original delivery links.
Available checks continue when other material is absent. A known inconsistency
always outranks missing material or ambiguity.

| Axis | Values / meaning |
|---|---|
| Financial | Saved state/outcome/difference exactly; never recalculated |
| Run identity | `VERIFIED` or `FAILED` |
| Listed evidence coverage | `COMPLETE` or `PARTIAL` |
| Capture binding | `MATCHES_EXTERNAL_OBSERVATION` or `FAILED` |
| Signature/original admission | `VERIFIED`, `MISSING_MATERIAL`, `UNSIGNED_LEGACY`, `INCONSISTENT` |
| Physical binding | `UNIQUE_CANDIDATE` or `MULTIPLE_CANDIDATES` |
| Original policy/current key | Distinct recorded epoch and pinned capture-head status |
| Run creation auth cut | Always `NOT_RECORDED` |
| Financial recomputation | Always `NOT_PERFORMED` |

- Exit 0: `VERIFIED_FOR_CAPTURE`, required evidence/material complete and no
  ambiguous physical binding; the two permanent limitation fields remain visible.
- Exit 3: `PARTIAL`, only missing full signed material, genuine unsigned legacy
  or multiple physical candidates prevent complete verification.
- Exit 2: `FAILED`, malformed/path/size/dependency input, wrong expectations,
  broken protected link, bad signature, inconsistent material or required scope.

The report records explicit reason codes, including `MISSING_SIGNED_SNAPSHOT`,
`UNSIGNED_LEGACY` and `MULTIPLE_RECEIPT_CANDIDATES` for partial cases. Missing
optional crypto is an explicit exit 2 dependency error, not semantic test success.
Exit 2 takes priority over exit 3. An exporter returns `CREATED`; that result is
never interchangeable with `VERIFIED_FOR_CAPTURE`.

`report.json` has exact fields `format: "run-provenance-report-v1"`, `run_id`,
`run_payload_sha256`, `capture_digest`, `configuration_digest`, `capture_profile`,
`record_ids`, `receipt_hashes`, `findings`, `run_creation_authorization_cut`,
`financial_recomputation` and `source_verification`. The last three fields are
`NOT_RECORDED`, `NOT_PERFORMED` and `NOT_PERFORMED`, respectively. The capture
profile describes observed protection metadata; it cannot override external
expectations. Record and receipt inventories are sorted unique lists. Each finding
entry has `id` (`run_id + ":" + decimal ordinal`), `ordinal`, `comparison`, `asset`,
`scope` and `evidence_ids`. Every field is compared against the immutable run and
independently traversed capture; dishonest report entries are rejected. The
report's scope edges and the capture's original SQL relationship edges together
form the machine-readable relationship report. The verifier does not treat the
exporter's lists as expected coverage.

## Offline page

The page shows the selected saved run/cuts and financial findings first, then
expandable record, physical candidate, original admission, signature, policy and
raw line details. Links/downloads name exact bytes and hashes. It has no network
dependencies, backend, CDN, external fonts or institution branding. All data is
rendered as text, never executable source HTML. Keyboard controls and narrow
layouts remain usable. A separate optional verification-record import may show
the result only when its manifest binding matches, with its externally observed
status clearly distinguished from the page's own unverified capture view.
