# C01–C08 results

The final fixed runtime completed all **19** preregistered controls on the actual
local ARM64 Lima VM. The final source run is
`/var/tmp/crl-protected-evidence-v1/final-source-v3/results.json`; its status is
PASS, with no skipped, failed or unexecuted test identities, and unchanged source
hashes during execution. Kernel traces are in sibling `final-trace-v3`.

| Family | Actual controls and result |
| --- | --- |
| C01 | Protected imported snapshot; ACL, xattr, full source inventory/stat preservation; 30/1/6/60 financial counts; all three review files equal. Three real WAL Online Backup/conversion runs and three imported snapshot runs pass. |
| C02 | Unsealed input, writable sealed handle, non-root supervisor, untrusted parent, missing contract, actual writable-root and strict-atime-root faults all rejected before export. |
| C03 | Four non-root processes fail 400 writes through a retained writable sealed-anchor FD. Four real consumer children fail 1,600 path/alias/proc attacks while export runs. A separate 14-class privilege/namespace probe and three concurrent writers pass. An inherited original-source writable FD is absent in consumer preflight. An original-source mutation aborts publication; a controlled trusted-supervisor mutation of the consumed inode is detected. |
| C04 | Symlink ELOOP, hardlink SOURCE_TYPE, traversal UNSAFE_PATH, bind alias EXDEV; real process inode replacement after pinning is rejected. Exporter reopens the stable read-only namespace inode; attempts to rename/link it fail. |
| C05 | Existing directory, file and dangling link unchanged. A competing process creates the final destination immediately before renameat2; atomic no-replace publication refuses and preserves its evidence. |
| C06 | Closed clean WAL [2,2] imported as snapshot, each SQLite sidecar and a corrupt DELETE database rejected. Valid DELETE and explicit live WAL producer controls pass. |
| C07 | Distinct source, backup, sealed-anchor and consumed-inode observations; 24-table independent financial reader; actual canonical output bytes; PID-aware strace and independent evidence reader. Forged self-consistent COMPLETE output fails trusted reference comparison. |
| C08 | Controlled EIO; genuine SIGKILL before publication; genuine supervisor SIGKILL with active consumer and detached grandchild; zero surviving descendants; previous evidence preserved. Fresh recovery succeeds while retaining the first failed attempt. |

Expected input/attack rejection is a successful negative control, not an
application failure. Test harness failures and rejected experimental designs
remain in their original directories; they are not counted in final PASS totals.
The exact identities and complete per-test observations are in the machine
readable protocol/results, not inferred from this table.

The final installed wheels also pass the same 19 controls on Python 3.12 and
3.14. A separate reader validates all three execution populations, complete
file inventories, canonical outputs, payload identities, error codes and kill
observations. The final targeted PID-mapped trace observes 1,600 denied attack
syscalls, including 400 denied hidden-source opens, in four real child processes.

Complete historical regression and CI observations are bound separately in the
delivery EVIDENCE_MANIFEST and FINAL_DECISION. A source
test result alone does not imply an installed or remote CI pass. All consumer
execution here uses the recorded system Python 3.14 runtime; producer/package
verification spans Python 3.12 and 3.14.

NOT_RUN / outside scope: x86_64 execution, other kernels/filesystems, hostile host
root or kernel compromise, physical power loss and institutional source
authentication. Evidence deletion is intentionally not run. These are not
reclassified as successful controls.
