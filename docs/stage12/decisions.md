# Stage 12 decisions

1. Use the existing BEGIN IMMEDIATE transaction helper, preserving its ownership
   and rollback behavior. This reserves the local writer for the bounded
   calculation and can delay other writers. SQLite documents separate-connection
   isolation and transaction/COMMIT busy behavior; the project's process tests
   establish the actual application boundary.
   Sources read 15 November 2026:
   https://www.sqlite.org/isolation.html and
   https://www.sqlite.org/lang_transaction.html .
2. Separate execution/request/context storage from immutable financial runs.
   Deterministic content-bound execution IDs simplify reproducible synthetic
   evidence while request uniqueness stays local to one DB registry.
3. Keep the financial engine byte-preserved. Extract only Store's persistence
   body and pass a private owned-transaction facade from the new runtime.
   Validate existing financial mirrors before any reuse, including actual run
   TEXT byte hashing.
4. Record every eligible physical input and a finite admission relation closure,
   not only selected evidence and not an inferred unique historical receipt.
   Observed admission policy is not actor authorization for reconciliation.
5. Add exact versioned validators and explicit real legacy-5 initialization.
   Preserve closed {5,6} ordinary runtime support, fixed provenance-v1/schema5,
   and explicit financial-review/schema6 support. No fake downgrade, table
   hiding, validator mock or broad future-version acceptance.
6. Keep runtime standard-library-only. Source crypto remains optional for
   producing protected fixtures; recording existing admission does not repeat
   cryptographic verification. No new service, independent verifier or web UI.
7. Preserve unsuccessful setup attempts. The old Git object store could not
   read a pack during fetch; an isolated fresh public clone supplies the accepted
   main and a new managed task worktree. No old worktree, output or distribution
   is repaired or reset. This observation does not establish the filesystem
   cause.

