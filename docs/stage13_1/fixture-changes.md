# Stage13.1 exact metadata fixture changes

Only six current-release metadata literals in three existing test files change. All test method bodies, behavior assertions, original anchor identities and process fixture pins remain unchanged. These edits were explicitly authorized by the task.

The independent feasibility evidence is reproduced by exact count-one replacement and byte-for-byte reversal against reviewed head `0ecf194c80d82f363b1868585787361abab84f57`. This proof is metadata preservation, not a rerun of the independent review or a financial result.

## tests/test_release_test_scope.py

Before: `146c3e6357c6ffbfc1d4668c715851121ceb93004ed2dcbc409c2c2380e9a21f` (7985 bytes). After: `f27874ac936495e5ab3ddefbbcc05894b3d5c28955dade66b78ff3c8e925763c` (7985 bytes).

Exact reversal: **PASS**. Test-method AST preservation: **PASS**.

Count: **1**.

```text
old_text: CONTRACT_PATH = 'contracts/release-test-scope-0.11.0.json'
new_text: CONTRACT_PATH = 'contracts/release-test-scope-0.11.1.json'
```

Count: **1**.

```text
old_text:                  'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.11.0'}
new_text:                  'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.11.1'}
```

## tests/test_provenance_maintenance_release.py

Before: `2ca261b3c91915fde09d3663f420dbf11775aaed53c22e21ce12fff9c9b27b70` (5182 bytes). After: `896cb5dd6dce20ac1200fa46f03ea2a220ab94f7f282e1c8ae5d10749dd2e4d0` (5182 bytes).

Exact reversal: **PASS**. Test-method AST preservation: **PASS**.

Count: **1**.

```text
old_text:     setup = {'format': 'release-provenance-maintenance-v1', 'package_version': '0.11.0',
new_text:     setup = {'format': 'release-provenance-maintenance-v1', 'package_version': '0.11.1',
```

## tests/test_execution_replay_scope.py

Before: `059cc426fecd89a845c7875280ee79cba774e84c0c6fb600492b7a490369d66e` (7201 bytes). After: `28a64d50490b91140cda38f53559831c19e9b254f15bdf7ca7fc955c884fe60d` (7201 bytes).

Exact reversal: **PASS**. Test-method AST preservation: **PASS**.

Count: **1**.

```text
old_text: "CONTRACT_PATH = 'contracts/release-test-scope-0.11.0.json'"
new_text: "CONTRACT_PATH = 'contracts/release-test-scope-0.11.1.json'"
```

Count: **1**.

```text
old_text: "                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.11.0'}"
new_text: "                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.11.1'}"
```

Count: **1**.

```text
old_text: "    setup = {'format': 'release-provenance-maintenance-v1', 'package_version': '0.11.0',"
new_text: "    setup = {'format': 'release-provenance-maintenance-v1', 'package_version': '0.11.1',"
```

## Historical scope composition

The immutable 0.11.0 scope stays at 245,263 bytes, SHA-256 `3bbd2f2252947c90395f69161849ce790fc183a80f3ecf63075d48b18080cdb1`, 858 test identities and 89 test/fixture files. A separate `replay_release` binding carries exactly these three files and six expressions. The original 0.10.1 `execution_repair_release` remains two files and three composed expressions; every original `old_text`, hash and historical path set stays unchanged.

`restore_fixture_source` restores each historical source directly from current bytes. The old `version_regex` negative retains `old_text=0.10.1`, `new_text=0.11.0`; it is not a current metadata fixture and is untouched. No generic version replacement permission, caller-specific historical view, or normal-verification roster generation is introduced.

The new 0.11.1 current roster is authored once after the final new tests are complete. Actual command records and the six-change reversal proof are retained outside Git under `stage13_1-output/release-preparation`.
