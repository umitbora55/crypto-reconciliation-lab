# Protected snapshot consumer v1

Preregistered on 2026-11-19, starting at Gate 4 commit
`19b19c7cd17bd0b7e6a93964044562c584f7e63a`.

## Contract and trust

This is an opt-in Linux root-supervised boundary, separate from `review-export`.
The supervisor, kernel, Python runtime, installed package, selected producer UID
and their administrators are trusted. Host root, a compromised kernel, hostile
runtime installation, physical power loss and institutional financial truth are
outside this contract. The consumer UID is 65534, has no supplementary groups,
capabilities or privilege acquisition, and is not a trusted producer UID.

The producer may open the live WAL database through SQLite Online Backup. It
creates a distinct private inode, converts it to DELETE, verifies integrity,
schema 6 and selected saved payloads, and closes every SQLite writer. An imported
closed snapshot requires an explicit expected SHA-256. Source paths are opened
relative to directory descriptors using openat2, rejecting symlinks, traversal,
mount crossings and hardlinks. Source namespace ownership is checked. A hash is
an operator-provided byte expectation, not external source authentication.

Finalized bytes are copied to a fresh memfd and sealed with WRITE, GROW, SHRINK
and SEAL. No writable FD is passed to the consumer. The zero-link memfd is an
intentional private transport, not an exception for hardlinked source files.
The Linux experiment found that a direct memfd bind mount fails with EINVAL;
the original failed attempt is retained. The namespace supervisor therefore
materializes bytes from the sealed anchor into a fresh private tmpfs inode,
checks the digest, closes its sole writer and remounts the entire root read-only.
The consumer sees that finalized inode at one fixed path with
`ro,noatime,nosuid,nodev`; its directory is also immutable to the consumer.
Reopening by the existing exporter therefore reaches the same finalized inode.
The tmpfs inode is not itself sealed. Its protection relies on a never-exposed
inode, a read-only filesystem, absent writable descriptors and the trusted
namespace supervisor. The sealed anchor is distinct and recorded as such.
The original input FD is never used as a preflight substitute for that invariant.

Mount, PID, network, IPC and UTS namespaces plus a private filesystem root hide
the live database and producer staging. Only minimal read-only Python runtime,
package files, authorized input, private scratch and output are exposed. A new
procfs sees only the child PID namespace. Credentials/capabilities are dropped,
no_new_privs is set, cwd is inside the root and all non-stdio FDs are closed
before untrusted execution. Kernel state is checked before invoking the exporter.

The supervisor reaps the whole namespace, validates exact regular output files,
compares all three files against a trusted deterministic reference computed
from the finalized snapshot, copies them to its own staging directory, fsyncs,
then uses atomic no-replace
rename in a trusted output parent. A pre-publication interruption cannot expose a
successful final directory. Hidden abandoned work is evidence, never COMPLETE.
After successful atomic rename, a failed directory fsync or acknowledgment write
can leave a complete verified bundle with a failed command: this is an
acknowledgment ambiguity, never a partially published bundle. Recovery inspects
the target and retained proof and uses a fresh output name; it never overwrites.

The WAL producer UID's entire namespace is trusted. That producer may append
SQLite transactions while backup runs, but must not rename/unlink or replace
source files. The SQLite path reopen is covered by this explicit trusted-owner
contract, not by a claim that before/after inode checks defeat a malicious
authorized producer. Full unchanged input metadata applies to imported closed
snapshots; a live WAL's SQLite reads can affect atime/SHM and do not have that
metadata-preservation claim. Unsupported or writable source ownership/modes are
rejected, rather than silently chmodded into acceptance.

Scope is the observed ARM64 Linux VM. The x86_64 syscall mapping is present but
NOT_RUN; macOS and other platforms reject before export. User namespace creation
and mount topology syscalls are blocked by seccomp after credential drop.

## Frozen test scope

One final code fingerprint runs C01–C08. Earlier failed attempts remain separately
identified. Each observation is PASS, EXPECTED_REJECTION, FAIL or NOT_RUN.

* C01: protected valid snapshot, unchanged source metadata/ACL/xattr/namespace,
  financial output equality; valid WAL Online Backup conversion.
* C02: unsealed FD, writable FD, incorrect/no mount, non-root supervisor and
  untrusted source directory rejected before exporter.
* C03: actual concurrent non-root writers, alternate aliases, retained writable
  FD versus seals, inherited-FD closure, source isolation, before/after identities.
* C04: symlink, hardlink, traversal, bind mount alias, and source replacement race
  through actual producer/exporter consumption.
* C05: existing directory/file and dangling link; concurrent destination creation.
* C06: clean WAL header as imported snapshot, sidecars and corrupt snapshot.
* C07: independent table/payload/evidence reader, original/source/transport inode
  identities, strace, input/output inventories and source/package fingerprints.
* C08: controlled publication failure, real SIGKILL, prior evidence preservation
  and no partial successful publication.

Performance budget: three valid snapshot imports and three WAL backups of the
30-receipt custody_difference fixture; at most 60 seconds per consumer. Report
phase observations, sample count and runtime identity. These are mechanism costs,
not a repeat of Gate 4's 10k/25k workload comparison. Attack loops are bounded to
five seconds or a fixed iteration count, never infinite. Full 3.12/3.14 source
and installed regression gates run after code freeze; rerun only affected gates
after a failure or material revision. Historical tests and finance remain intact.

No production default change, automatic WAL activation, main merge or release.
READY requires every mandatory gate; unresolved controls remain NOT_RUN/BLOCKED.

## Kernel references

The input resolver uses the independent symlink, beneath and mount-crossing
controls documented in [openat2](https://man7.org/linux/man-pages/man2/openat2.2.html).
Content seals apply to all descriptors of the same inode and cannot be removed;
they do not authenticate financial input: see
[F_GET_SEALS / F_ADD_SEALS](https://man7.org/linux/man-pages/man2/F_GET_SEALS.2const.html).
The trusted PID1 lifetime monitor is necessary because credential changes clear
the parent-death signal, as documented in
[PR_SET_PDEATHSIG](https://man7.org/linux/man-pages/man2/PR_SET_PDEATHSIG.2const.html).
The kernel kills namespace members when its init process exits:
[PID namespaces](https://man7.org/linux/man-pages/man7/pid_namespaces.7.html).
These references inform the design; the retained kernel traces and tests are
the execution evidence for this particular implementation and VM.
