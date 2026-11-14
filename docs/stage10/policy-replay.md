# Local policy and replay v1

These rules are prototype design choices. The trust anchor is the local operator,
the database owner and the running Python code, not a key embedded in an envelope.
Protection is enabled only in a new empty schema-5 database; configuration alone
may exist. Setup atomically fixes the receiver, canonical configuration digest
and first policy. Legacy databases remain legacy; there is no disable operation.

A policy has exactly `format`, `receiver`, `configuration_digest`, `sources`, and
`keys`. Format is `source-auth-policy-v1`. Each source has `source`, `namespace`,
and exact `capabilities`. Each key has `key_id`, `source`, raw public-key hex,
SHA-256 fingerprint and `active`/`revoked` status. Sources are the configured
platform or custodian. ASCII namespaces end in a colon and cannot overlap or
contain one another. Source/namespace and key identity/bytes/source are immutable
across epochs. Later policies retain all historical sources and keys; capabilities
may change and keys may be added. Revocation is monotonic, including fingerprint
aliases. Local activation compares expected previous epoch/hash in the same
transaction and appends a snapshot and activation; stale updates have no effect.

Signature and whole-file consistency preflight do not grant a current permission.
Every delivery transaction rereads the active epoch and checks every tuple in the
whole file. Policy activation and delivery serialize with SQLite BEGIN IMMEDIATE.
A preflight race cannot authorize a later effect with stale permissions. A source
owns each committed stream with receiver/configuration and first immutable plan;
key rotation does not change stream ownership. An unauthorized request cannot
reserve a stream or manufacture a transport conflict. A currently authorized
source submitting a genuinely different plan retains Stage 9 PLAN_CONFLICT.

Each successful or transport-terminal delivery decision records the policy epoch,
verified endorsement and key status with the attempt. A new effect also links its
original decision and receipt. All these rows commit in one transaction. The
original effect link is never replaced by later replay decisions. Rejection audit
is separate, bounded to 10,000 rows, and never produces core/admission effects.
A busy database returns RETRYABLE_BUSY without pretending that rejection persisted.
A killed process before its reply has UNKNOWN caller knowledge: reopening and
replaying determines committed state. Process-kill tests do not prove power-loss
or malicious-owner durability.

Normal exact replay returns the original terminal disposition and receipt without
another economic effect. After revocation, HISTORICAL_REPLAY is allowed only for
an already committed line linked to the identical original verified statement,
snapshot, source and receiver. It reports the original authorization separately
from current revoked status and currently_authorized=false. No unseen suffix is
admitted. A new active key for the same source can sign the same statement/plan,
replay the prefix and commit the suffix with its current epoch; old links remain.
Revoked replay never clears Stage 9 permanent BLOCKED priority. Active keys whose
capabilities have been removed have no historical exception. No wall-clock expiry
is implemented; an old previously unseen file can be accepted while its source/key
remain authorized. Whole-database rollback is outside this local epoch guarantee.

Public APIs take raw snapshot/envelope bytes, never a caller-provided verified
flag. The private transaction body is part of the trusted implementation boundary.
`max_lines` only bounds a demo's committed prefix; whole-file preflight still runs.
Named barriers are auth_after_preflight (outside transaction), auth_before_commit
(after decision/receipt/links) and auth_after_commit (before response delivery).
