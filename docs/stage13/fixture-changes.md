# Stage13 current metadata fixture exceptions

The user authorizes exactly three current release metadata expressions in two existing test files. No test method, assertion, negative mutation, process helper or schema expectation changes. The accepted source is `9db7fd80dcd32d7bada9ff7e4054eb083254da8e`. The immutable 0.10.1 test contract remains 219,024 bytes / SHA-256 `2ac30fd8f96a5223b174b899484b72aaad2982c64de6c168b34670c419aa8427`, containing 778 unique IDs and 78 files.

Each change below has an exact reversal to accepted source bytes. All old test function ASTs in these files are identical. These are metadata fixture changes, not historical behavior changes.

## tests/test_release_test_scope.py

Before: `7bc2d0337f1d757acb369785eb5ccea97d8a57a453e166428f8dd4190befde4f` (7985 bytes). After: `146c3e6357c6ffbfc1d4668c715851121ceb93004ed2dcbc409c2c2380e9a21f` (7985 bytes).

```diff
--- tests/test_release_test_scope.py (accepted 0.10.1)
+++ tests/test_release_test_scope.py (current 0.11.0)
@@ -16,7 +16,7 @@
 
 ROOT = Path(__file__).resolve().parents[1]
 BASELINE_PATH = 'contracts/release-tests-baseline-0.6.0.json'
-CONTRACT_PATH = 'contracts/release-test-scope-0.10.1.json'
+CONTRACT_PATH = 'contracts/release-test-scope-0.11.0.json'
 BASELINE = json.loads((ROOT / BASELINE_PATH).read_text())
 SPEC = importlib.util.spec_from_file_location('scope_release_verifier', ROOT / 'scripts/verify_release.py')
 verify = importlib.util.module_from_spec(SPEC)
@@ -35,7 +35,7 @@
     identities = list(declared_ids())
     current = ROOT / CONTRACT_PATH
     identity = ({'path':CONTRACT_PATH, 'bytes':current.stat().st_size,
-                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.10.1'}
+                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.11.0'}
                 if current.exists() else {})
     return dict(status='PASS', discovered=len(identities), executed=len(identities),
                 discovered_ids=identities, executed_ids=list(identities), scope_identity=identity,
```

## tests/test_provenance_maintenance_release.py

Before: `eadd3c833f8520947798f568b24a922307d95691a50274ed006aed75e6e6f51a` (5182 bytes). After: `2ca261b3c91915fde09d3663f420dbf11775aaed53c22e21ce12fff9c9b27b70` (5182 bytes).

```diff
--- tests/test_provenance_maintenance_release.py (accepted 0.10.1)
+++ tests/test_provenance_maintenance_release.py (current 0.11.0)
@@ -12,7 +12,7 @@
 
 
 def literal_controls():
-    setup = {'format': 'release-provenance-maintenance-v1', 'package_version': '0.10.1',
+    setup = {'format': 'release-provenance-maintenance-v1', 'package_version': '0.11.0',
              'f1_preservation': {'external_changed_fields': ['capture_digest'], 'raw_run_equal': True,
                                  'signed_materials_equal': True},
              'f2_authoritative_capture_unchanged': True,
```

## Historical binding composition

The new current 0.11.0 contract keeps all historical original identities and `old_text` values. Only current identities and the three authorized `new_text` endpoints are composed to the real 0.11.0 files. `restore_fixture_source` reverses each historical binding directly to its original bytes. `EXECUTION_PATH` stays at 0.10.0, `MAINTENANCE_PATH` stays at 0.9.1, and both Stage12.1 process helper pins stay unchanged. A separate pinned 0.10.1 binding preserves all 778 accepted IDs and all 78 accepted files. No caller-specific historical view or generic version regex is introduced.

The final 0.11.0 scope is authored only after the separately declared new tests are complete. Normal build and verification read pinned expectations; they never regenerate the expected roster. Actual discovery/execution, package and financial checks are recorded outside Git.
