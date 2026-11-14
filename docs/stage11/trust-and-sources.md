# Trust and technical context

The reviewer chooses two things separately: which saved run is being inspected,
and which observed capture/policies they are willing to trust. A directory that
contains a signed file and its public key cannot make that choice for them. The
external expectations file fixes the run ID, raw payload hash, configuration,
capture digest and protected/legacy profile. For protected captures it also fixes
the receiver and the entire activated policy map through a stated head.

That map binds more than key bytes. It binds each key to its source and fingerprint,
each source to its namespace and exact capabilities, and the current/revoked state
at the chosen capture head. An original acceptance under epoch 1 and a revoked
key at epoch 4 are compatible observations; neither replaces the other. Removing
the later policy or reclassifying protected rows as legacy must not erase a
reviewer's external choice.

## What the operator observation establishes

The capture digest pins the complete selected SQL projection the operator
observed. It includes every physical receipt candidate for each listed run hash,
the selected original delivery relationships and the complete policy history.
It is a trust decision about this capture, not a cryptographic certificate of
SQLite execution. The database hash helps identify the source file; without DB
bytes the verifier cannot prove that the projection was actually read from it.
The supplied database may be under a malicious owner's control; this feature
does not add tamper-proof storage, trusted clocks or institutional certification.

This division is deliberate. Matching a receipt hash in today's database does
not establish which physical receipt existed at run creation. A later delivery
can have the same content hash. All candidates remain visible; the run creation
authorization cut remains `NOT_RECORDED`, including otherwise successful results.
The saved financial result is never recomputed or overwritten.

Keep operational expectations outside a received bundle. Obtain the pinned run
and capture from the operator's separate observation process; do not take an
untrusted export's proposed pins and automatically call them trusted. Any future
exporter suggestion would be a separate `UNTRUSTED_TEMPLATE`, not an authority.
The small demo explicitly acts as its own TEST-ONLY operator and uses synthetic
keys and controlled fixtures. It is not an onboarding mechanism for a real
publisher or a general certificate infrastructure.

## Primary reference record

Access date for the two external contextual sources below: 14 November 2026.
These sources inform the engineering explanation. The bundle schema, capture
scope, limits, error precedence and CLI states are this prototype's design
assumptions, not rules imposed by these publications.

| Source | Publication / access | Narrow supported point | Boundary |
|---|---|---|---|
| [W3C PROV-DM: The PROV Data Model](https://www.w3.org/TR/prov-dm/) | W3C Recommendation, 30 April 2013; HTML accessible | Its conceptual model distinguishes entities, activities and responsible agents and describes their relationships. | Stage 11 uses this distinction as conceptual vocabulary. It does not implement RDF, PROV-O or claim full PROV conformance. |
| [BCBS 239 publication page](https://www.bis.org/publications/201301-guidelines-principles-effective-risk-data-aggregation-and-risk-reporting) and [January 2013 text](https://www.bis.org/publications/201301-guidelines-principles-effective-risk-data-aggregation-and-risk-reporting.pdf) | Page dated 9 January 2013; HTML and 28-page PDF accessible | Principle 3 paragraph 36(c) discusses source reconciliation; Principle 7 paragraphs 52–53 discuss report accuracy, validation and explaining data integrity issues. | This supplies professional context for explaining a synthetic difference. It neither certifies this project nor establishes current shortcomings at any named institution. |
| [Existing signing profile](../stage10/signing.md) | Preserved Stage 10 project contract; read during Stage 11 | Documents existing DSSE/Ed25519 application framing, exact byte checks and finite bounds. | Signing behavior and optional dependency versions are unchanged. Stage 11 does not implement new cryptographic primitives. |
| [Existing local policy/replay contract](../stage10/policy-replay.md) | Preserved Stage 10 project contract; read during Stage 11 | Separates local operator policy, original acceptance and later historical replay/revocation. | Local activation is not a certificate chain or proof of a run-time auth snapshot. |

The W3C mapping is an engineering interpretation: a saved run, receipt and feed
are entities; financial evaluation and original admission are distinct activities;
the operator-approved publisher is the actor bound by local policy. This small
bundle expresses those links in its own JSON contract.

No claim is made about a current MKK, Borsa İstanbul or Takasbank defect, any
institution's use of this project, regulatory compliance, production readiness
or the truth of a custody quantity. A valid source signature and a saved
`MISMATCH +1` can legitimately appear together.
