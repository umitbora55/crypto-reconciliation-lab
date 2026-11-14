# Stage 11 decisions

These are prototype design decisions. Historical stage contracts remain intact.
Actual commands, failures, release results and final CI belong outside Git in
`stage11-output`; this document does not predeclare those checks as passed.

| Decision | Reason and consequence |
|---|---|
| One saved run and one closed schema-5 copy | A single read transaction can observe the run and authorization projection together. No migrations or database writes are needed. Existing historical runs can be read only when already present in supported schema 5. |
| Preserve raw run bytes and canonical run ID separately | The existing logical run identity does not identify its exact serialization. Reviewers must be able to pin both without silently normalizing history. |
| Keep `NOT_RECORDED` permanently visible | The old model did not save a run-creation physical receipt/auth cut. Later matching hashes cannot supply that missing historical fact. |
| External capture pin plus independently checked relations | The pin protects the observed complete candidate inventory; relationship checks reject incoherent edges even in intentionally repinned test projections. Neither substitutes for the other. |
| Full activated policy map through a pinned head | Checking only original acceptance epochs would hide later revocation. Original authorization and capture-head key state remain separate. |
| Preserve every physical hash candidate | Identical economic content can arrive in multiple physical deliveries, including after a saved run. Selecting the first, latest or signed candidate would create unsupported certainty. |
| Selected effects and their attempts, not the whole database | The finite capture covers required receipt hashes and their original delivery closure. Unrelated runs, streams and rejection audit history remain outside the single-run claim. |
| Original envelopes from SQL, full snapshots from explicit files | The DB stores envelope bytes but does not guarantee whole feed retention. Missing full files stay missing; reconstructed prefixes do not become signed originals. |
| Separate independent verifier | It derives required run scope and joins itself; it cannot use the exporter's report as an oracle or call export/admission/reconciliation. Existing pure JSON/crypto/policy helpers are reusable. |
| `CREATED`, exit 0 verification, exit 3 partial and exit 2 failure | Export completion is not source verification. Known inconsistency has priority over ambiguity, legacy or missing material, so a partial explanation cannot conceal a bad protected link. |
| Trusted fixed UI assets plus independently checked data wrapper | A rehashed malicious HTML/JS file must not pass package verification. JSON.parse over an escaped canonical string keeps hostile keys/text as data; the old review UI remains untouched. |
| External verification record | A CLI result can bind to the raw manifest digest without modifying the sealed bundle or causing a hash cycle. The page does not bootstrap trust from its embedded keys. |
| Same optional auth dependency, no AI requirement | New primitive implementations or network services would add unrelated trust and deployment problems. Core import/help remains available without crypto; protected verification reports missing auth explicitly. |
| Finite operational fixtures and one final release gate | Independent literal amounts/expected links make the ten scenarios inspectable. New feature tests are not retroactively described as old-version defect regressions. Baseline tests are not rerun without reason; final unchanged financial/reference gates remain authoritative. |
| Separately pinned accepted 0.8.2 test ancestor | The 575 accepted IDs and original file identities remain bound without rewriting older historical anchors. Only two current-version fixture expressions change, with exact reversible byte proof; new IDs enter a new 0.9.0 roster. |
| Release-owned ten-group/24-case coverage | A demo's expected labels cannot excuse missing cases or dependency failures. The release gate checks fixed identities, semantic reason codes and literal clean/mismatch amounts, then repeats one positive and one semantic-negative CLI check. |
| Nonempty listed evidence in provenance v1 | A valid saved financial result with no listed receipts remains readable, but cannot receive a provenance completeness claim. Verification returns `NO_LISTED_EVIDENCE` rather than vacuous success. |

The contract was written before feature code. During interface coordination,
SQL BLOBs were fixed to lowercase hex in exact schema-column rows, and the static
page data transport was fixed to a double-encoded canonical JSON string passed
to `JSON.parse`. This avoids JavaScript object-literal semantics for `__proto__`
while retaining deterministic bytes. These decisions do not change the financial,
admission or source-auth runtime contracts.
