# Stage 10.1 release metadata and preservation

Only the current release metadata changes from 0.8.0 to 0.8.1. The 540 previously reviewed test identities and all assertion ASTs remain unchanged. The original 0.8.0 contract remains byte-identical (80,521 bytes; SHA-256 `7dc06a3a89c2756f1574479cd288cec1bef65fe13925bfa5703a3be829311ec5`).

The historical `BASELINE_PATH` remains the 0.7.1 contract with its existing byte/hash identity. The new current contract separately binds 0.8.0, preserves its 540 identities and file inventory, and records just the two explicitly permitted reversible metadata exceptions below. Ordinary gates validate the fixed inventory and never regenerate expected identities from discovery or execution.

Package metadata, the build version/current-scope allowlist, scope helper identity, and the wheel reader's default version become 0.8.1. New maintenance documents and the new fixed scope are included in both the source allowlist and sdist. Runtime dependencies, workflow behavior, schema 5, stage2-v2, recovery v2 and auth v1 resource bytes are unchanged.

## tests/test_release_test_scope.py

Only current 0.8.1 contract/release fixture metadata; all existing assertion ASTs and tested behavior are unchanged.

Original: 7983 bytes; SHA-256 `d0843e930098b2c0a40612e7479cd2a71be2514bb370676201a66fe9270dc10b`. Current: 7983 bytes; SHA-256 `e7c5d3537a0fcdacfd1065949b6fbbc0dba14178badf314af743479868f34413`.

## tests/test_source_auth_release.py

Only current 0.8.1 contract/release fixture metadata; all existing assertion ASTs and tested behavior are unchanged.

Original: 6238 bytes; SHA-256 `ad19b5d877e9749a08fde94745db0621242160a05364729e1112470e306802ba`. Current: 6238 bytes; SHA-256 `19c2d620c270f3265c20293ca355c58be52135ae71fd6f54c16d5471affcbe42`.

## Exact old-test diff

```diff
--- 0.8.0/tests/test_release_test_scope.py
+++ 0.8.1/tests/test_release_test_scope.py
@@ -16,7 +16,7 @@
 
 ROOT = Path(__file__).resolve().parents[1]
 BASELINE_PATH = 'contracts/release-tests-baseline-0.6.0.json'
-CONTRACT_PATH = 'contracts/release-test-scope-0.8.0.json'
+CONTRACT_PATH = 'contracts/release-test-scope-0.8.1.json'
 BASELINE = json.loads((ROOT / BASELINE_PATH).read_text())
 SPEC = importlib.util.spec_from_file_location('scope_release_verifier', ROOT / 'scripts/verify_release.py')
 verify = importlib.util.module_from_spec(SPEC)
@@ -35,7 +35,7 @@
     identities = list(declared_ids())
     current = ROOT / CONTRACT_PATH
     identity = ({'path':CONTRACT_PATH, 'bytes':current.stat().st_size,
-                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.8.0'}
+                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.8.1'}
                 if current.exists() else {})
     return dict(status='PASS', discovered=len(identities), executed=len(identities),
                 discovered_ids=identities, executed_ids=list(identities), scope_identity=identity,
--- 0.8.0/tests/test_source_auth_release.py
+++ 0.8.1/tests/test_source_auth_release.py
@@ -67,7 +67,7 @@
                         verify.wheel_manifest(archive)
 
     def test_auth_contract_and_pins_are_required_source_inputs(self):
-        required = {'requirements-auth.txt', 'contracts/release-test-scope-0.8.0.json',
+        required = {'requirements-auth.txt', 'contracts/release-test-scope-0.8.1.json',
                     'contracts/source-auth-scope-v1.json',
                     'crypto_reconciliation_lab/source_auth/experiment_scope_v1.json'}
         self.assertLessEqual(required, build.REQUIRED)
```

Reversing these replacements must restore the complete original 0.8.0 files. No assertion, financial expected value or fixture setup changes. The separate 0.8.0 preservation binding is checked in the release preflight in addition to the historical 0.7.1 ancestry.
