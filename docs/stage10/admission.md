# Source-authenticated admission contract

This is a synthetic, opt-in local admission profile, not institutional identity
verification. The trust root is the local operator's policy, not a key embedded
in an envelope. See signing.md and policy-replay.md for the byte-level protocol.

Before implementation, the transaction boundary is fixed as follows. A schema-5
database is initially legacy mode. Only an empty database may atomically acquire
one immutable receiver/configuration/first-policy binding. Existing records,
receipts, evaluations or delivery history prohibit activation. There is no disable
operation. Ordinary open never migrates or enables protection.

All public unsigned write entry points check this binding inside their write
transaction, including direct Store.ingest, delivery admission and CLI paths.
Signed admission snapshots the bounded file once, verifies the exact statement
bytes and preflights the authority of every line before the first financial write.
Each line then rechecks the current policy epoch inside BEGIN IMMEDIATE. The
original financial ingest body, receipt, delivery effect, auth decision and links
share this transaction. A failed check creates no receipt or delivery reservation.
An append-only bounded rejection audit is separate from financial history.

Authority is a set of exact tuples, not independent lists whose Cartesian product
would grant extra permissions. Auth handles source authority; financial validity,
knowledge cuts and balances remain the responsibility of the unchanged core.
An authorized malformed amount therefore remains a visible INVALID core receipt.

Two real child-process SIGKILL barriers cover before commit and after commit before
ACK. The latter must recover the original receipt by replay. A separate barrier
lets the operator rotate policy after preflight but before the line transaction.
No synthetic raised exception substitutes for these process observations.

The trusted local operator can edit database files or roll back storage; neither
hostile ownership nor rollback resistance is claimed. There is no network sender,
credential service, certificate authority, clock-freshness promise or production
deployment. A signed, previously unseen file may be accepted while its key remains
authorized. History and current authorization are deliberately separate.
