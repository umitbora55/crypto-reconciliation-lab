# Reproduce the protected snapshot boundary

This opt-in command does not modify `review-export`, financial calculations,
schema 6, package version 0.11.1, or the production DELETE/FULL default.
Use the final task commit and the separate evidence archive. The archive includes
the fixed synthetic custody_difference snapshot, raw observations and failed
attempts. Never run these commands on production or old evidence directories.

## Supported trust scope

The recorded host is Lima `crl-wal`, Ubuntu ARM64, kernel 7.3.0-10-generic,
ext4. System `/usr/bin/python3` is 3.14.8 / SQLite 3.53.4. Producer and installed
package gates also run on isolated Python 3.12.13 / SQLite 3.53.1. The isolated
consumer deliberately uses the trusted system interpreter, so a Python 3.12
supervisor run is not a claim of a Python 3.12 consumer runtime.

Required Linux facilities: root supervisor, private mount/PID/network/IPC/UTS
namespaces, tmpfs/procfs, openat2, no-replace renameat2, memfd content seals,
capability drop, no_new_privs, seccomp, O_NOATIME and fsync. Missing protection
fails closed. Runtime files must be root-owned and not writable by group/other.
The root filesystem must permit the audited path traversal: mount crossings are
rejected. No silent fallback for macOS, remote filesystems or restricted containers.

The trusted producer UID's complete namespace is trusted. Source files must be
single-link regular files, with trusted ancestors and no group/other write bits.
Do not chmod the historical WAL fixture to make it pass. Use a new authorized
producer database in a private directory. During WAL backup the trusted writer
may append transactions, but must not rename/unlink its database or sidecars.

## Install an isolated wheel

From the checked-out task branch, with Python 3.12 or 3.14:

```sh
python3 -m venv /var/tmp/crl-build
/var/tmp/crl-build/bin/python -m pip install -r requirements-build.txt
/var/tmp/crl-build/bin/python scripts/build_release.py --help
# The canonical verifier builds an sdist and a wheel from that sdist, then
# installs the wheel into its own non-editable, separate environment.
/var/tmp/crl-build/bin/python scripts/verify_release.py \
  --profile full --financial --output /var/tmp/crl-release-new
```

Use `/var/tmp/crl-release-new/environment/bin/python` for the commands below.
Root execution of a package assumes the administrator has verified and trusts
that package's bytes. No dependency or interpreter installer runs inside the
consumer namespace.

## Review the fixed closed snapshot

Set `EVIDENCE` to the extracted delivery directory. Copy only the supplied
synthetic fixture into a fresh root-owned input directory; leave the original
reference unchanged. Replace the paths if they already exist.

```sh
sudo install -d -m 700 /var/tmp/crl-input-new /var/tmp/crl-output-new
sudo install -m 600 "$EVIDENCE/custody_difference.sqlite3" \
  /var/tmp/crl-input-new/snapshot.sqlite3
sudo /var/tmp/crl-release-new/environment/bin/python -I -B \
  -m crypto_reconciliation_lab.protected_snapshot \
  --kind snapshot --source /var/tmp/crl-input-new/snapshot.sqlite3 \
  --expected-sha256 1a37873cd1ec44a2e498baedb26c71250fb15afa0cc85e65c21cb35cc3669133 \
  --run-id db050c7ea9ce4aec4f0a99ea47ecd3e32d30b2d10ec209ff31c12e8cc139115b \
  --run-label 'Initial knowledge' --output /var/tmp/crl-output-new/review
```

Success publishes exactly `index.html`, `summary.json`, `manifest.json`, and
prints a JSON proof. Root-only `.protected-work-*` directories preserve producer,
canonical reference, process and trusted namespace attestations. They are
intentionally retained after both success and failure. They are not review output.
Existing targets, including dangling links, are never replaced. A CLI rejection
exits 2. After the atomic rename, an fsync/acknowledgment error can leave a complete
verified bundle despite a nonzero exit; inspect the target and retained proof.

For an authorized live WAL producer, use `--kind wal`, a new private source,
the intended run ID, and omit the snapshot hash option. The command uses SQLite
Online Backup, closes both database connections, verifies a distinct DELETE
snapshot, and transfers only a read-only sealed anchor. It never enables WAL on
the supplied database. `--producer-uid UID` explicitly trusts that UID's source
namespace; 65534 is rejected because it is the consumer UID.

## C01–C08 security suite

Run from the final source checkout on the local Linux VM. Dependencies for the
tests include `strace`, `util-linux`, `acl` and `attr`. The test runner imports the
package from the explicit source root, preregisters exact test identities and
hashes, then records outcomes and full input/output inventories. It creates real
mounts only within its private outer mount namespace. Set the fixture override
to the supplied synthetic file; never use a live database as this fixture.

```sh
sudo env CRL_SNAPSHOT_FIXTURE=/var/tmp/crl-input-new/snapshot.sqlite3 \
  unshare --mount --propagation private /usr/bin/python3 -B \
  scripts/validation/run_protected_tests.py \
  --repo "$PWD" --output /var/tmp/crl-security-new
```

For a kernel access trace, wrap that command with:

```sh
sudo strace -ff -qq --decode-pids=pidns -s 240 \
  -o /var/tmp/crl-trace-new \
  -e trace=memfd_create,openat,openat2,readlink,readlinkat,mount,umount2,unshare,clone,clone3,execve,close_range,fcntl,renameat2,prctl,chroot,setresuid,setresgid,setgroups \
  env CRL_SNAPSHOT_FIXTURE=/var/tmp/crl-input-new/snapshot.sqlite3 \
  unshare --mount --propagation private /usr/bin/python3 -B \
  scripts/validation/run_protected_tests.py \
  --repo "$PWD" --output /var/tmp/crl-security-traced-new
```

To run the same suite against a wheel, invoke its environment Python with `-I`
from outside the checkout, pass the absolute runner path and `--installed`.
The script keeps the test source explicit while package import comes from the
installed environment. The installed interpreter must be traversable by UID
65534 for external non-root attack subprocesses; private source and output
directories remain root-only. The consumer itself always receives a private
copied system runtime.

## Independent readers and regressions

```sh
python scripts/validation/protected_regression.py financial \
  --snapshot /path/to/original/snapshot-delete.sqlite3 \
  --wal /path/to/original/evidence.sqlite3 --output /var/tmp/crl-finance-new
python scripts/validation/protected_regression.py source-matrix \
  --repo "$PWD" --python /absolute/path/to/python3.12 \
  --output /var/tmp/crl-source-matrix-new
python scripts/validation/protected_regression.py release --repo "$PWD" \
  --reports /path/full312/verification.json /path/full314/verification.json \
  --output /var/tmp/crl-independent-release-new.json
sudo python3 -I scripts/validation/audit_protected_evidence.py \
  --repo "$PWD" --baseline /path/to/unchanged-gate4-checkout \
  --run /path/to/final-security-run \
  --run /path/to/installed312-security-run \
  --run /path/to/installed314-security-run \
  --fixture /path/to/reference/snapshot-delete.sqlite3 \
  --pidns-trace /path/to/targeted-PID-mapped-trace \
  --output /var/tmp/crl-independent-security-new.json
```

The financial reader uses O_NOATIME and queries only new inspection copies. Its
raw WAL copies are test-reader inputs, never the protected producer handoff.
Run the canonical full profile separately on both Python versions. It checks the
exact 875 historical test identities in source and installed modes, all 373 fixed
financial references, and the 69-case/162-evaluation installed matrix. The source
matrix command complements that with the source import path. Core and auth-only
profiles preserve optional dependency boundaries. The frozen main ML experiment
is not regenerated or trained.

The new tests/docs/helpers ship in Git and the evidence archive. The historical
sdist allowlist remains unchanged; all seven new package modules enter the wheel
automatically. Existing tests, contracts, financial references and Gate 4 files
remain byte-identical. Final commit CI and archive hashes are external delivery
observations so they do not create a self-referential source/CI commit loop.

## Interruption and retention

C08 kills an actual supervisor with an active consumer and detached grandchild;
a separate observer records and reaps the whole process tree. A second actual
SIGKILL occurs after real export and fsync but before renameat2. Controlled EIO
and output-creation collisions preserve prior evidence. Recovery uses a fresh
owned attempt and retains the original failure. No automated deletion of evidence
is performed; disk reclamation is an explicit administrator action after archival.
Namespace teardown is measured separately. Physical power loss, hostile host
root, other architectures and institutional authentication remain unproved.
