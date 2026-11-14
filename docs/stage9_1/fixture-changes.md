# Stage 9.1 authorized fixture changes

All 451 historical test identities and their financial/operational assertions remain. The 0.7.0 contract and immutable task baseline remain unchanged. Only the exact changes below are permitted. Normal verification loads the pinned 0.7.1 contract; it does not regenerate this roster.

## tests/test_admission_release.py

Replace only the named synthetic verifier fixture with complete coherent v2 evidence; all seven existing test methods and assertions stay byte-identical. The fixture is not an actual process run.

Original: 5083 bytes, SHA-256 `8f9ed34059ca677aa21824e4514a6e6b7533fca2676f8f800937130567da5daa`.
Current: 4101 bytes, SHA-256 `61ca0e801c8dad63d12d76348679baeb35dee975fcf583329b770ddf9e1265ce`.

```diff
--- 0.7.0/tests/test_admission_release.py
+++ 0.7.1/tests/test_admission_release.py
@@ -13,24 +13,12 @@


 def report_fixture(scope):
-    """A small declared verifier input; actual process runs have separate evidence."""
-    rows = []
-    for name in scope['scenario_ids']:
-        processes = []
-        if name in scope['crash_barriers']:
-            processes.append({'barrier': scope['crash_barriers'][name], 'barrier_reached': True,
-                              'exit_code': -9, 'sender_result': 'UNKNOWN'})
-        if name in scope['writer_scenarios']:
-            processes.extend({'pid': pid, 'joined': True, 'exit_code': 0} for pid in (101, 102))
-        rows.append({'id': name, 'status': 'PASS', 'checks': [{'passed': True}], 'processes': processes})
-    return {'format': 'admission-recovery-v1', 'status': 'PASS',
-            'planned_scenario_ids': list(scope['scenario_ids']), 'executed_scenario_ids': list(scope['scenario_ids']),
-            'schedule_sha256': 'a' * 64, 'scenarios': rows,
-            'negative_control': {'status': 'EXPECTED_FAILURE', 'models': [
-                {'name': 'premature_ack', 'observed_status': 'FAIL'},
-                {'name': 'empty_cursor', 'observed_status': 'FAIL'}]},
-            'environment': {'python': 'fixture', 'interpreter': '/fixture/python', 'import_origin': '/fixture/package',
-                            'sqlite': 'fixture', 'platform': 'fixture', 'journal_mode': 'delete', 'synchronous': 2}}
+    """Synthetic complete verifier input; never evidence of an executed process."""
+    import json
+    value = json.loads((ROOT / 'tests/fixtures/admission-semantic-report-v2.json').read_text())
+    if not value['fixture_notice'].startswith('SYNTHETIC VERIFIER INPUT.'):
+        raise ValueError('fixture provenance missing')
+    return value


 class AdmissionReleaseTests(unittest.TestCase):
```

## tests/test_release_test_scope.py

Bind the same success/omission/identity tests to the current fixed release contract.

Original: 7983 bytes, SHA-256 `66ad85f8bfbee58be4efa64d88ce9e1ae259ac004896a2a0b58ef2174360196b`.
Current: 7983 bytes, SHA-256 `555a058ff68c9a80922230c566a27b8f8eba2b6d6a27bc43a2d51780dcc7d37e`.

```diff
--- 0.7.0/tests/test_release_test_scope.py
+++ 0.7.1/tests/test_release_test_scope.py
@@ -16,7 +16,7 @@

 ROOT = Path(__file__).resolve().parents[1]
 BASELINE_PATH = 'contracts/release-tests-baseline-0.6.0.json'
-CONTRACT_PATH = 'contracts/release-test-scope-0.7.0.json'
+CONTRACT_PATH = 'contracts/release-test-scope-0.7.1.json'
 BASELINE = json.loads((ROOT / BASELINE_PATH).read_text())
 SPEC = importlib.util.spec_from_file_location('scope_release_verifier', ROOT / 'scripts/verify_release.py')
 verify = importlib.util.module_from_spec(SPEC)
@@ -35,7 +35,7 @@
     identities = list(declared_ids())
     current = ROOT / CONTRACT_PATH
     identity = ({'path':CONTRACT_PATH, 'bytes':current.stat().st_size,
-                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.7.0'}
+                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.7.1'}
                 if current.exists() else {})
     return dict(status='PASS', discovered=len(identities), executed=len(identities),
                 discovered_ids=identities, executed_ids=list(identities), scope_identity=identity,
```

## Scope and enforcement

The fixed release contains 472 identities in 44 test/fixture files: the original 451 plus 21 explicitly declared additions.

The special exception accepts only the top-level `report_fixture(scope)` function in `tests/test_admission_release.py`. Original/current file and block hashes are pinned. Reversing that one block must reconstruct every original byte. A changed test assertion, additional top-level code or another function/path cannot be authorized by this exception. Ordinary metadata exceptions remain single-line replacements.

The immutable originals and exact raw unified diffs are retained in the external task evidence. No old test method, financial literal, assertion or operational expectation is removed.
