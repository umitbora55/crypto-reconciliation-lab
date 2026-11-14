# Stage 11.1 authorized fixture changes

All 641 reviewed test identities remain. Every old test assertion AST is unchanged.
Every old test/fixture file is byte-identical except the two explicitly authorized
changes below; reversing the recorded edits restores the pinned 0.9.0 bytes.

## tests/test_release_test_scope.py

Explicit current release/scope metadata permission; all 641 old identities and assertion ASTs are retained.

Before: 7983 bytes / `9a2c8285cdd45f915be57aeb7da1d18332e929a245939b68d66fb11700189220`.

After: 7983 bytes / `614e18dffad9f86b360f1ac23fbc972cfdd03a0e99c0775c28ded85d94d06c74`.

## tests/test_provenance_verifier.py

Only the authorized independent data.js fixture serializer encodes declared PK/FK identities exactly; raw evidence, expectations and every security assertion stay unchanged.

Before: 25354 bytes / `65adec79726015ffd42d6baf4838ec37fcaf3664f23e15ac44c51171bb88d827`.

After: 26264 bytes / `391cc8e1f4a28a749e4f3b4cf2565e5bae105cdcfa0fb7a52569115b94542290`.

The scope contract contains the exact reversible replacements and pins both
function blocks for the independent `refresh` serializer. No test method or
acceptance assertion is replaced. `test_provenance_ui.py` is unchanged.

```diff
--- 0.9.0/tests/test_release_test_scope.py
+++ 0.9.1/tests/test_release_test_scope.py
@@ -16,7 +16,7 @@
 
 ROOT = Path(__file__).resolve().parents[1]
 BASELINE_PATH = 'contracts/release-tests-baseline-0.6.0.json'
-CONTRACT_PATH = 'contracts/release-test-scope-0.9.0.json'
+CONTRACT_PATH = 'contracts/release-test-scope-0.9.1.json'
 BASELINE = json.loads((ROOT / BASELINE_PATH).read_text())
 SPEC = importlib.util.spec_from_file_location('scope_release_verifier', ROOT / 'scripts/verify_release.py')
 verify = importlib.util.module_from_spec(SPEC)
@@ -35,7 +35,7 @@
     identities = list(declared_ids())
     current = ROOT / CONTRACT_PATH
     identity = ({'path':CONTRACT_PATH, 'bytes':current.stat().st_size,
-                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.9.0'}
+                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.9.1'}
                 if current.exists() else {})
     return dict(status='PASS', discovered=len(identities), executed=len(identities),
                 discovered_ids=identities, executed_ids=list(identities), scope_identity=identity,
--- 0.9.0/tests/test_provenance_verifier.py
+++ 0.9.1/tests/test_provenance_verifier.py
@@ -49,7 +49,21 @@
         assert all(expected[k] == original[k] for k in ('run_id', 'run_payload_sha256', 'configuration_digest', 'policies', 'policy_head'))
     material = {p.relative_to(bundle).as_posix(): fingerprint(p.read_bytes())
                 for p in sorted((bundle/'materials').rglob('*')) if p.is_file()}
-    value = {'run': run, 'capture': capture, 'report': report, 'materials': material}
+    # Fixture-only 0.9.1 display serialization; raw capture and every semantic
+    # assertion stay unchanged. Do not import the production view builder.
+    shown = copy.deepcopy(capture)
+    fields = {'receipts': ('id',), 'delivery_effects': ('sequence', 'core_receipt_id'),
+              'delivery_attempts': ('id', 'sequence', 'effect_sequence'), 'auth_configuration': ('id',),
+              'auth_policy_activations': ('epoch', 'previous_epoch'), 'auth_keys': ('first_epoch',),
+              'auth_decisions': ('id', 'epoch', 'sequence'),
+              'auth_delivery_links': ('sequence', 'decision_id', 'core_receipt_id'),
+              'auth_attempt_links': ('attempt_id', 'decision_id')}
+    for table, columns in fields.items():
+        for row in shown['tables'][table]:
+            for column in columns:
+                if type(row[column]) is int:
+                    row[column] = str(row[column])
+    value = {'run': run, 'capture': shown, 'report': report, 'materials': material}
     (bundle/'data.js').write_bytes(b'window.PROVENANCE_DATA = JSON.parse(' + encoded(encoded(value).decode('ascii')) + b');\n')
     manifest = load(bundle/'manifest.json')
     manifest['files'] = {p.relative_to(bundle).as_posix(): fingerprint(p.read_bytes())
```
