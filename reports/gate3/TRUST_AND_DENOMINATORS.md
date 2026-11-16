# External trust and false-negative denominators

Gate3 replays 24 retained LAB reference cases and confirms the narrow benefit:
the twelve curated same-count substitutions become distinguishable when the
caller supplies the correct ordered identity/content reference. The added facts
are generated and signed by this laboratory. There are **zero independently
authenticated institutional counterparties**. The original count-only twelve
false negatives remain historical false negatives; production admission and
financial rules are unchanged.

## Separate populations and denominators

| Population / observation | Cases | Positive / negative labels | TP | FP | TN | FN | Interpretation |
|---|---:|---:|---:|---:|---:|---:|---|
| FULLY_SYNTHETIC, Gate1 original count-only | 264 | 144 / 120 | 132 | 0 | 120 | 12 | Historical ledger independently recounted; financial run not repeated in this lane |
| FULLY_SYNTHETIC, original paired subset without reference | 24 | 12 / 12 | 0 | 0 | 12 | 12 | All original stored financial results are MATCHED with alert=false |
| FULLY_SYNTHETIC, same paired inputs plus LAB signed reference | 24 | 12 / 12 | 12 | 0 | 12 | 0 | Actually replayed in Gate3; a separate added-input experiment |
| REAL_PLUS_SYNTHETIC_INJECTION, Gate2 SEC controls | 360 | 180 / 180 | 120 | 0 | 180 | 60 | Recounted retained labels/detections over **30 distinct source rows**, each reused across controlled families |
| REAL_PUBLIC_DIRECT, Treasury modern four-total equations | 60 dates | No natural error labels | — | — | — | — | 39 exact, 21 residuals of ±1 million; 32 legacy dates not evaluated by this equation |
| REAL_PUBLIC_DIRECT, SEC FTD | 89,285 records | No natural error labels | — | — | — | — | Outstanding aggregate balances; not daily new fails, fail age, fraud or short-sale-abuse labels |
| REAL_PUBLIC_ADAPTED, Treasury native-engine constructions | 60 cases | Authored expectations | — | — | — | — | One authored source, zero independent counterparties; 39 expected strict matches and 21 expected strict mismatches |

The Gate1 curated recall denominator is 144 positives, not 264 cases:
132/144; its twelve substitution false negatives are 12/144 overall and 12/12
within that family. The SEC curated recall denominator is 180 positives, not
360 cases: 120/180. Each of invalid date, invalid CUSIP, negative quantity and
duplicate key has 30 TP and 30 TN. Valid CUSIP substitution and valid quantity
change each has 30 FN and 30 TN. The paired LAB reference has 12 positives and
12 negatives. These populations, repeated controls and added inputs cannot be
pooled into a combined accuracy estimate. Natural real-world precision and
recall are **NOT_MEASURABLE**.

The 240 broader Gate2 identity-control cases and its 102 parser/encoding/time
checks remain separate historical inventories. They are not newly executed
Gate3 efficacy observations. Timing repetitions below are also not additional
detection observations.

## Executed marginal benefit and bounded cost

The preregistered protocol is
`/workspace/validation-gate3-evidence/trust/protocol.json`, SHA-256
`4a42bfc3b519380e9589fbd8e4e855d512716d5dcafa72e26088863b801a2e84`.
It selects seeds 11, 29 and 47, factors 0–3, and exactly the `clean` and
`same_count_substitution` families before execution. It pins 128 retained
source/input files. `scripts/validation/audit_gate3_trust.py` checks every pinned
file before and after execution, reconstructs economic event identities from
the original Gate1 input bytes without using the research extraction helper,
checks the independently selected clean-context equality, and compares ordered
IDs and content digests against the fixed original envelope. It then actually
calls the unchanged Gate2 verifier. The per-case roster records expected and
actual outcomes, byte identities, elapsed wall/CPU time and operation counts.

The 24-case replay passed. Every case has three economic events and a signed
envelope of **896 bytes**, plus the retained serialized trust-context file of
**550 bytes**. The context is separate caller input; it is not itself an
institutional certificate or a verified wire/storage overhead for production.
Each verification adds one Ed25519 verification, one manifest digest check,
three candidate content hashes and three ordered identity comparisons, plus
scope/revision/predecessor/key-epoch/active-key checks. The Gate3 audit also
requires equality against the separately selected original context. These
named operations are finite experiment work units, not a CPU instruction count.

| Operation, fixed original `s11-f0-clean` | Median seconds per call | Observed maximum batch-average seconds per call |
|---|---:|---:|
| Ed25519 signature verification only, predecoded key/message/signature | 0.000132127 | 0.000147501 |
| Independent context/manifest/ordered-event checks, without signature | 0.000018690 | 0.000022893 |
| Complete unchanged reference verifier | 0.000298784 | 0.000320575 |

Each row is five batches of 100 calls after ten warmup calls per operation;
operation order rotates by batch. Maxima are observed maxima of batch averages,
not tail latency estimates for individual calls. Whole-audit wall time was
0.324469 seconds, CPU 0.320243 seconds, and high-water RSS 25,645,056 bytes.
The enclosing process completed with exit 0 in 0.418896 seconds; that includes
startup and interpreter/import overhead. Warmup took 0.003294 seconds. The
preregistered bounds were 60 seconds outer wall, 45 seconds CPU, 512 MiB address
space and 20 MiB output. Output is a finite small audit; the microdiagnostic
does not model storage durability, transport, key management or institutional
source acquisition. Host contention was not controlled. RSS is the whole audit
process high-water mark, not incremental signature allocation.

The independent signature check and verifier share the installed
`cryptography`/OpenSSL Ed25519 implementation. JSON/SHA-256 definitions also
overlap by specification. This is an independent record/identity and expected
outcome calculation, **not an independent cryptographic implementation**.
Exact interpreter, import origins, source SHA, inputs, limits, command exits
and stdout/stderr are retained in `trust/run-001/` and
`trust/commands/replay-001/`. No failed replay attempt preceded this successful
run. New research tests are separate from the protected 875 application IDs.

## Unfulfilled independent two-party acquisition protocol

**Current status: NOT_AVAILABLE.** No institutional records, private customer
data, institution-issued keys, data-sharing consent or independent institutional
ground truth were obtained. The following is an acquisition specification for
a separately authorized future task, not a claim of completed reconciliation.

1. **Agree the economic question and grain before receipt.** Source A's record
   holder is the institution responsible for customer liabilities/ledger;
   source B's holder is the custodian responsible for confirmations. Identify
   legal entities, custody arrangements, assets, account partitions and
   beneficial/omnibus ownership. Fix asset identifiers, unit scales, positions
   versus events, account mapping, timezone and economic cut. Reconcile exact
   asset/account/cut balances only where both sources represent the same
   economic claim; explicitly bridge receivables, pending settlement, fees,
   reserves and unmatched ownership. Never equate aggregate Treasury totals
   with customer liabilities or custody confirmations.
2. **Obtain separate authority and authorization.** Each holder independently
   authorizes an export and nominates its signer. Record the holder, signer,
   signer role, identity-verification method, public-key provenance, allowed
   dataset/scope, validity interval, revocation process and authorization
   evidence through a separately authenticated channel. A signer is not
   automatically the holder; an analyst's candidate manifest is not a trust
   root. Consent, minimization, retention and redistribution permissions must
   cover the actual fields and purpose before access. No data are to be
   acquired under this unfulfilled protocol without separate authorization.
3. **Capture each source independently.** Retain exact signed export bytes,
   source-selected immutable record IDs, source holder and export request ID,
   economic cut, source-system extraction time, publication/vintage time and
   receiver capture time as distinct facts. Record pagination/completeness,
   sequence ranges, counts, cancellations, corrections, missing partitions,
   late arrivals and reissues. A retrieval timestamp does not prove publication
   vintage or ledger cutoff. Unknown vintage stays UNKNOWN and fails any
   freshness requirement that requires a proven value.
4. **Bind the comparison externally.** The authorized reviewer independently
   selects expected source identities, approved scopes/cuts, current versions,
   predecessor chain and keys before accepting candidate files. Verify
   signatures against those selections, record revocation observation time,
   and preserve previously accepted decisions as history. Keep A and B's raw
   objects, signatures and provenance separate; use a versioned, reviewed
   crosswalk with explicit many-to-one/one-to-many rules. Unknown or duplicate
   identities are unresolved exceptions, not silently normalized matches.
5. **Establish ground truth and disputes.** Source A attests customer-liability
   truth; B attests its custody confirmation. Neither attestation alone proves
   ultimate economic truth. For discrepancies, obtain independent documentary
   evidence of settlement, ownership and corrections with named adjudicator,
   decision rationale and timestamps. Distinguish an identified disagreement
   from an actual loss or error. Natural precision/recall requires an independently
   adjudicated representative error population and denominator; curated
   injections cannot supply it.
6. **Release only a qualified evidence decision.** Retain exact acceptance and
   rejection reasons, unresolved disputes, publication/freshness gaps, omitted
   artifacts, source rights and authorized review audience. Define operational
   freshness, availability, recovery and audit obligations separately, with
   actual production measurements before claiming an SLA, RTO/RPO, risk
   reduction, regulatory compliance or deployment readiness.

## Limitations and manual replay prerequisites

Replaying this audit requires the unchanged Gate1 run-004 files and Gate2
identity run-002 / public analysis-02 results at the absolute paths enumerated
by the pinned protocol, the pinned original identity verifier, and the recorded
Python/cryptography dependencies. Missing or substituted files fail; the script
does not regenerate plausible records. The script, protocol, 24-case roster,
timing rows and execution logs are small review artifacts. Original SEC ZIPs
and site documents retain their separate redistribution limitations; no new
SEC downloads or redistribution authorization were obtained in this lane.

Not run: independent institutional acquisition; natural labelled error sample;
persistent reference/epoch registry and fresh revocation feed; production
admission integration; independent crypto implementation; isolated allocation
measurement; institutional network/storage/key-management costs; provider
pricing; production RTO/RPO. **INSTITUTIONAL_DEPLOYMENT, COST_SAVINGS,
RISK_REDUCTION and REGULATORY_COMPLIANCE remain NOT_PROVEN.**
