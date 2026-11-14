# Stage 10.2 release metadata and preservation

Only current release metadata changes from 0.8.1 to 0.8.2. All 564 previously reviewed test identities, assertion/fail ASTs and fixture semantics remain unchanged. The two named old test files have exactly three permitted expressions changed below.

The historical `BASELINE_*` anchor remains 0.7.1 (64,724 bytes; SHA-256 `2e21ae9f60ec7163af140d9f8e2eb91f33d3492e6b3edb1b3b4a86430a736a7e`). `PREVIOUS_*` remains 0.8.0 (80,521 bytes; SHA-256 `7dc06a3a89c2756f1574479cd288cec1bef65fe13925bfa5703a3be829311ec5`). The additional `REVIEWED_*` binding pins 0.8.1 (88,456 bytes; SHA-256 `eaff707f9241792ee5041dae82821f5dd79589468849d8c7e38155590c7f531a`) and preserves its complete 564-ID/file inventory independently of ordinary discovery.

The current contract's `additions` remains relative to the historical 472-test baseline: all 92 inherited additions plus the new regression identities. Inherited exceptions retain their original hashes; current metadata expressions and current hashes advance. The existing 0.7.1/0.8.0/0.8.1 contract files themselves remain byte-identical. A one-shot external authoring script consumes the separately reviewed new roster; normal gates only validate that fixed inventory.

Package version, build version, scope helper identity and wheel reader default become 0.8.2. New docs and scope enter the source allowlist and sdist. No dependency pin, workflow, schema 5, stage2-v2, recovery v2 or auth v1 resource changes.

## tests/test_release_test_scope.py

Original: 7983 bytes; SHA-256 `e7c5d3537a0fcdacfd1065949b6fbbc0dba14178badf314af743479868f34413`. Current: 7983 bytes; SHA-256 `757c4478f9a021c377cc96843ffda08c781f1424214abd22bd8f0722ea46b549`.

## tests/test_source_auth_release.py

Original: 6238 bytes; SHA-256 `19c2d620c270f3265c20293ca355c58be52135ae71fd6f54c16d5471affcbe42`. Current: 6238 bytes; SHA-256 `dc575e0b6bf28973af611215aba2285ad8bcd498441591851f59e2a19e22b16e`.

## Exact old-test diff

```diff
--- 0.8.1/tests/test_release_test_scope.py
+++ 0.8.2/tests/test_release_test_scope.py
@@ -16,7 +16,7 @@
 
 ROOT = Path(__file__).resolve().parents[1]
 BASELINE_PATH = 'contracts/release-tests-baseline-0.6.0.json'
-CONTRACT_PATH = 'contracts/release-test-scope-0.8.1.json'
+CONTRACT_PATH = 'contracts/release-test-scope-0.8.2.json'
 BASELINE = json.loads((ROOT / BASELINE_PATH).read_text())
 SPEC = importlib.util.spec_from_file_location('scope_release_verifier', ROOT / 'scripts/verify_release.py')
 verify = importlib.util.module_from_spec(SPEC)
@@ -35,7 +35,7 @@
     identities = list(declared_ids())
     current = ROOT / CONTRACT_PATH
     identity = ({'path':CONTRACT_PATH, 'bytes':current.stat().st_size,
-                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.8.1'}
+                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.8.2'}
                 if current.exists() else {})
     return dict(status='PASS', discovered=len(identities), executed=len(identities),
                 discovered_ids=identities, executed_ids=list(identities), scope_identity=identity,
--- 0.8.1/tests/test_source_auth_release.py
+++ 0.8.2/tests/test_source_auth_release.py
@@ -67,7 +67,7 @@
                         verify.wheel_manifest(archive)
 
     def test_auth_contract_and_pins_are_required_source_inputs(self):
-        required = {'requirements-auth.txt', 'contracts/release-test-scope-0.8.1.json',
+        required = {'requirements-auth.txt', 'contracts/release-test-scope-0.8.2.json',
                     'contracts/source-auth-scope-v1.json',
                     'crypto_reconciliation_lab/source_auth/experiment_scope_v1.json'}
         self.assertLessEqual(required, build.REQUIRED)
```

Reversing only these replacements restores the complete 0.8.1 files byte for byte. No assertion, expected financial value or fixture setup changes. The release preflight reverses the reviewed-release exceptions as well as the retained historical exception chains.
