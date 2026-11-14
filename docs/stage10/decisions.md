# Stage 10 decisions

1. Add optional pinned cryptography for Ed25519; do not implement cryptography in
   project code. Core and offline financial review keep standard-library runtime.
2. Use one DSSE application profile with exact bytes, one signature and explicit
   operator policy. Embedded key identifiers are lookup hints, not trust roots.
3. Add schema 5 only. Keep all financial tables, migration history and v1 payloads
   intact. Legacy schema 4 remains readable and requires explicit backed-up migration.
4. Factor the existing delivery transaction body into a private helper. Public
   unsigned wrappers remain guarded; signed admission supplies no caller-controlled
   verified flag and commits authority evidence with the original receipt.
5. Keep complete input snapshots in bounded memory and external experiment evidence;
   store their digest in endorsements and committed line bytes in existing effects.
   Do not duplicate the full financial file in a new database blob.
6. Keep old recovery v2 evidence and its semantic reader byte-identical. A distinct
   predeclared source-auth scope defines the new experiment. Test-only keys are
   visibly synthetic and never represent production identities.
