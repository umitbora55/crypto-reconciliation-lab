# Financial parity

The original fixture was verified, rather than presumed to exist:

* Snapshot: `/var/tmp/crl-financial-wal-_2p915zx/snapshot-delete.sqlite3`
* SHA-256: `1a37873cd1ec44a2e498baedb26c71250fb15afa0cc85e65c21cb35cc3669133`
* Size: 352,256 bytes; SQLite header journal bytes [1,1]; physical schema 6.
* Run: `db050c7ea9ce4aec4f0a99ea47ecd3e32d30b2d10ec209ff31c12e8cc139115b`.
* Receipts 30; runs 1; findings 6; evidence 60.

The separate reader `scripts/validation/protected_regression.py` imports no
protected implementation. It reads the original files with O_NOATIME, inspects
SQLite only on new owned copies, and compares every row in all 24 source tables.
Original WAL/main/SHM and snapshot payloads match; integrity and foreign-key
checks pass. The original files' complete measured stat fields and xattrs remain
equal. Its first SQL attempt used the wrong column name `runs.run_id`; that
original failure remains, followed by the schema-inspected `runs.id` correction.

The unchanged ordinary exporter and protected exporter produce these exact
three bytestring identities for the imported reference:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| index.html | 176782 | eaa94b7d0da0bfd516dbcf5de0ad4940ce336fe661aeec0e1bfb11d1f7c3305a |
| summary.json | 861 | a44e05b8bab94ac4e45845bb3df46c6e36ca4c79b3f313a1c9c1f30d93c440ee |
| manifest.json | 3371 | 557f70b74269d513dbe19d949584eb86c45b33185d6ae56562e11e4e8fc41746 |

The final direct CLI run also consumes the original snapshot using explicitly
trusted producer UID 501 and preserves its hash, inode/device, mode, ownership,
size, atime_ns, mtime_ns, ctime_ns and xattrs. That evidence is in
`/var/tmp/crl-protected-evidence-v1/direct-cli-v3`.

For each newly produced WAL backup, the trusted reference and isolated consumer
must match all three files. WAL backup versus the old reference must match
index.html and summary.json and every financial table/payload/evidence identity.
A new backup can have different SQLite page/header counters and therefore a
different database-byte hash in manifest.json; that is not a financial change.

All 875 historical test identities and assertions remain byte-identical. The
immutable reference has 373 files (325 matrix + 12 Stage 1 + 36 Stage 2), SHA-256
`4abda380a19acd4cdfed97a46b6fb15528f32b8ef308c6931815c5b03641275e`.
The canonical full source/installed gates and supplementary source matrices check
69 scenarios / 162 evaluations for both selected Python versions. Exact final
reports, command hashes, import origins and wheel identities are in the delivery
manifest; prior successful variants are not substituted for final package checks.

No financial engine, Decimal rule, VOID/REPLACE behavior, time cut, manifest
meaning, signature/authority boundary or DELETE/FULL default was edited. Matching
hashes establish byte equality under the recorded provenance, not authentication
of an external institution or independent economic truth.
