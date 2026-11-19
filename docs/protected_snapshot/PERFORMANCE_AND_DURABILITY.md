# Mechanism cost and durability scope

This is a 30-receipt synthetic mechanism measurement. The preregistered sample
is three WAL backups and three closed imports, with a 60-second consumer limit.
The table below is the untraced final-runtime Python 3.12 supervisor compatibility
run; the child runtime is the recorded system Python 3.14. Concurrent validation
work may affect timing. These are observations, not capacity or superiority claims.

Median seconds, n=3 for each input kind:

| Phase | WAL backup | Closed import |
| --- | ---: | ---: |
| SQLite Online Backup | 0.001551 | not applicable |
| DELETE conversion | 0.001219 | not applicable |
| Input byte copy | included in backup | 0.001034 |
| Snapshot validation | 0.005159 | 0.004585 |
| Trusted reference review | 0.007781 | 0.007509 |
| Isolation setup | 0.175391 | 0.172360 |
| Consumer process, including interpreter start | 0.209622 | 0.209350 |
| Financial review inside consumer | 0.119414 | 0.119125 |
| Trusted consumed-inode postcheck | 0.000293 | 0.000295 |
| Launch and namespace teardown remainder | 0.042463 | 0.055602 |
| Atomic publication and acknowledgment | 0.003270 | 0.003556 |
| Complete supervisor operation | 0.448853 | 0.458636 |

Rows overlap where stated; medians must not be summed as if they were disjoint
observations. Financial review duration comes from the default consumer's
diagnostic audit; setup, wait and postcheck durations come from trusted PID1.
The producer operation also generates a trusted canonical reference so a
compromised consumer cannot publish forged but internally consistent output.

Raw values: `source312-compatibility/test_C01_WAL_backup_and_bounded_phase_cost/phase-costs.json`
under the task's Linux security evidence root. The final source acceptance run
also records phase costs under strace; those instrumented values are kept
separate. Final installed-package measurements are additional compatibility
observations, not independent samples for a pooled speed claim.

Gate 4's historical 10,000-event DELETE/FULL 15.576 s versus WAL/FULL 6.369 s,
and 25,000-event 39.989 s versus 17.961 s, used different workloads and scope.
They cannot be combined with this table or used to infer end-to-end production
benefit. Production DELETE/FULL remains unchanged; WAL adoption remains
CANDIDATE_NOT_ACCEPTED even if the opt-in boundary passes its Linux scope.

Actual process interruptions were exercised. One SIGKILL arrives after completed
export and fsync, before atomic no-replace rename. Another kills the supervisor
while a consumer and detached SIGTERM-ignoring grandchild are alive; all observed
descendants disappear and are reaped. A controlled EIO and a real destination
collision preserve previous evidence. A fresh retry succeeds and retains the
failed attempt; its measured recovery duration is in the C08 recovery record.

The namespace is ephemeral and automatically torn down. Disk evidence is
deliberately retained: deletion/reclamation cost is NOT_RUN, not zero. Hidden
abandoned work does not become a successful public review. After rename, an
acknowledgment or parent-directory fsync error can leave a complete verified
target with a failed command; no partial-complete claim is made.

SIGKILL is not physical power loss. Hardware caches, storage loss, hostile root,
other kernels/filesystems, institutional operating risk, regulatory compliance
and externally authenticated financial truth are not established.
