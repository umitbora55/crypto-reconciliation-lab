# Stage 11 fixture and release integration changes

The user explicitly permits narrow current-version/scope fixture metadata changes.
Only `tests/test_release_test_scope.py` changes: its current contract path and the
current release identity returned by `successful_result`. These are fixture
metadata expressions, outside every test assertion. Historical release and
schema fixtures are unchanged. `tests/test_source_auth_release.py` still requires
the preserved 0.8.2 contract and is byte-identical to the accepted source.

Accepted main: `6cb02dee2c2b36bd53d79c2a80dbc7ed6ae90b3f`.

| File | Before bytes / SHA-256 | After bytes / SHA-256 |
|---|---|---|
| `tests/test_release_test_scope.py` | `7983 / 757c4478f9a021c377cc96843ffda08c781f1424214abd22bd8f0722ea46b549` | `7983 / 9a2c8285cdd45f915be57aeb7da1d18332e929a245939b68d66fb11700189220` |

```diff
--- accepted-0.8.2/tests/test_release_test_scope.py
+++ stage11-0.9.0/tests/test_release_test_scope.py
@@ -16,7 +16,7 @@
 
 ROOT = Path(__file__).resolve().parents[1]
 BASELINE_PATH = 'contracts/release-tests-baseline-0.6.0.json'
-CONTRACT_PATH = 'contracts/release-test-scope-0.8.2.json'
+CONTRACT_PATH = 'contracts/release-test-scope-0.9.0.json'
 BASELINE = json.loads((ROOT / BASELINE_PATH).read_text())
 SPEC = importlib.util.spec_from_file_location('scope_release_verifier', ROOT / 'scripts/verify_release.py')
 verify = importlib.util.module_from_spec(SPEC)
@@ -35,7 +35,7 @@
     identities = list(declared_ids())
     current = ROOT / CONTRACT_PATH
     identity = ({'path':CONTRACT_PATH, 'bytes':current.stat().st_size,
-                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.8.2'}
+                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.9.0'}
                 if current.exists() else {})
     return dict(status='PASS', discovered=len(identities), executed=len(identities),
                 discovered_ids=identities, executed_ids=list(identities), scope_identity=identity,
```

Reversing the two exact one-occurrence replacements reproduces every original
byte. Every assertion-call AST in the accepted test files is unchanged; all
other accepted test/fixture files are byte-identical. The accepted contract's
575 test IDs remain a separately pinned ancestor. This preservation inspection
is not a claim that the baseline suite was rerun. Real command output and the
complete old/new file inventory are retained outside Git in
`stage11-output/metadata/fixture-preservation.json`.

The release scope keeps the existing 0.6.0, 0.6.1, 0.7.0, 0.7.1, 0.8.0 and 0.8.1
anchors and adds a distinct accepted 0.8.2 binding. Ordinary verification cannot
regenerate the current expected roster. New test IDs and exact file identities
are frozen in the 0.9.0 contract after focused validation.

The authored 0.9.0 roster contains **641 discovered IDs**: the accepted 575 plus
66 new IDs, in 59 test/fixture files. Its 111648-byte contract has SHA-256
`111f1975957662efe1f73083be03a608f37b055fcf9b61da51c129da40e5a4f5`.
Discovery and file preflight establish this expected roster; they do not claim
that the full suite has executed. The final release gate records expected,
discovered and actually executed identities separately.

Package metadata advances to 0.9.0. The source allowlist adds only the new
contract, Stage 11 Markdown and provenance module/local UI resources. The
existing release profiles gain bounded provenance CLI checks. CI artifact
retention adds only the new compact report/verification records; jobs, matrix,
permissions, triggers, dependency pins and financial-matrix selection stay intact.
