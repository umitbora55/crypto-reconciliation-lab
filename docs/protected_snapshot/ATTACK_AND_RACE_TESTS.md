# Attacks, races and retained first failures

The baseline RED script pins Gate 4 commit
`19b19c7cd17bd0b7e6a93964044562c584f7e63a` and checks its runtime is unchanged.
`scripts/validation/protected_red.py` reproduces C03/C04 with real Linux processes:
a non-root alias writer and a retained writable FD both change a read-only bind
view; the old exporter accepts symlink/hardlink sources; an external pinned-FD
check and a hash-to-copy barrier both permit another process to substitute the
inode consumed by the unchanged exporter. These are RED_REPRODUCED, not security
acceptance PASS. Results: `/var/tmp/crl-protected-red-02`.

The new boundary separates imported source, finalized backup, sealed transport
anchor and private consumed inode. No writable consumer descriptor or path points
to the consumed inode. A fresh entire tmpfs filesystem is read-only before the
consumer starts; root PID1 observes that actual inode before and after execution.
The trusted attestation is outside the consumer-writable output area. The final
supervisor verifies this proof and compares all canonical output bytes against
the authorized snapshot before publishing a newly copied directory.

The final controls include actual concurrent forked processes, actual syscall
denials, symlink/hardlink/bind aliases, a deterministic process replacement race,
wrong filesystem flags, user-namespace/clone/clone3 attempts, capability and root
reacquisition, hidden live WAL and supervisor FD access. Test-only fault workers
are separately hashed copies; no production bypass flag disables protection.
Controlled privileged tampering demonstrates detection, not prevention of a
host-root adversary. The trusted producer's WAL path-stability promise remains
explicit; a malicious authorized producer is not inside the consumer threat model.

Original unsuccessful observations remain distinct:

| Original observation | Classification and correction |
| --- | --- |
| Baseline RED C03 alias blocked by root-only evidence ancestor | Test setup failure; rerun in a fresh traversable task-owned tree. Original directory preserved. |
| Direct memfd bind mount returned EINVAL | Real rejected design; replaced by sealed anchor plus newly materialized private read-only tmpfs inode. |
| Exploratory extra libffi/script FD | Observed runtime/test setup issue; pre-exec FD closure and preflight fixed. Later imports may legitimately open read-only runtime files. |
| Self-consistent forged COMPLETE output accepted | Real implementation defect found by independent reader; trusted canonical three-file comparison added; identical forged files now rejected. |
| WAL test attempted UPDATE against append-only runs table | Test setup error, not relaxed append-only semantics; same-value user_version write creates a genuine WAL page instead. |
| Atime-fault injection omitted a remount flag but retained noatime | Fault injection failed to create the intended condition; explicit strict-atime remount now reaches and fails the real mount check. |
| SIGKILL observer read /proc after process exited (ESRCH) | Observer lifecycle race; treats ENOENT/ESRCH as disappearance, preserving real readiness/count/signal/survivor assertions. |
| Portable Python 3.12 omitted memfd and fcntl seal names | Real compatibility failure; audited libc memfd_create and identical Linux UAPI constants retain the same kernel protections. New package gates rerun. |
| Gate 4 research subprocesses launched from guest home | Orchestration cwd error; unchanged 50-test suite rerun from its required source root. |
| First PID-trace helper had a syntax error | Zero controls ran in that attempt; corrected helper and fresh trace output retained. |

Some early exploratory module snapshots were reconstructed after execution from
the recorded edit sequence. They are explicitly labelled reconstructed, not
contemporaneously source-sealed. Their failures and logs remain; none supplies a
final acceptance claim. Final preregistered executions include exact source and
test hashes captured before execution and verified afterward.

No skipped or failed control is counted as a pass. Reproduction code, raw stderr,
exit codes, syscall traces, prior source identities and subsequent corrections
are listed in the delivery evidence manifest.
