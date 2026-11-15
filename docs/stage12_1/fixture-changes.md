# Stage12.1 fixture and scope preservation

All 729 reviewed test identities and every existing test method AST remain unchanged. The only changed old files are two current version metadata fixtures and the two named synthetic process setup helpers. Reversing the exact replacements restores each whole 0.10.0 file byte-for-byte. Earlier nine schema/setup permissions remain finite; this repair grants no additional schema fixture edits.

## tests/test_provenance_maintenance_release.py

Stage12.1 authorizes only the two complete synthetic process setup helpers or exact current release metadata. All old test method ASTs remain identical.

Before: `91ed1ff943823ebe5929ce2450e05977286a8f786dd668c54ced0364be147b97` (5182 bytes). After: `eadd3c833f8520947798f568b24a922307d95691a50274ed006aed75e6e6f51a` (5182 bytes).

```diff
--- 
+++ 
@@ -12,7 +12,7 @@
 
 
 def literal_controls():
-    setup = {'format': 'release-provenance-maintenance-v1', 'package_version': '0.10.0',
+    setup = {'format': 'release-provenance-maintenance-v1', 'package_version': '0.10.1',
              'f1_preservation': {'external_changed_fields': ['capture_digest'], 'raw_run_equal': True,
                                  'signed_materials_equal': True},
              'f2_authoritative_capture_unchanged': True,
```

## tests/test_recorded_execution_release_gate.py

Stage12.1 authorizes only the two complete synthetic process setup helpers or exact current release metadata. All old test method ASTs remain identical.

Before: `9206d1d70364abb6a70d7f66459ac1f04658da04bdb2d0c3431f54dd54e88af5` (15260 bytes). After: `00f3cf19fc89e9d0c3ad26806cc06ebcc3dd20fedba9278507d98dea84cbe61a` (16905 bytes).

```diff
--- 
+++ 
@@ -64,10 +64,15 @@
 
 
 def literal_result(request='request', *, replayed=False, protected=False, receipts=30, epoch=None, second=False):
+    cuts = {'balance_at': '2026-11-12T23:59:59.000000Z', 'knowledge_at': '2026-11-13T01:00:00.000000Z'}
+    stable = {'format': 'recorded-execution-v1', 'db_scope': 'local-request-registry',
+              'configuration_digest': 'd'*64, 'rule_version': 'stage2-v2',
+              'profile': 'all-known-receipts-v1', **cuts}
     tables = {'records': [{'id': i} for i in range(30)], 'receipts': [{'id': i} for i in range(receipts)],
               'delivery_effects': [{} for _ in range(receipts)] if protected else [],
               'auth_decisions': [{} for _ in range(receipts)] if protected else []}
     context = {'schema_version': 6, 'scope': {'complete': True}, 'tables': tables,
+               'request_id': request, 'request': stable,
                'counts': {k: len(v) for k, v in tables.items()},
                'selected_evidence': {str(i): {} for i in range(60)},
                'observed_policy_head': {'epoch': epoch} if epoch else None,
@@ -77,18 +82,31 @@
                           'source_signature_verification': 'NOT_PERFORMED', 'run_actor_authorization': 'NOT_DEFINED'}}
     return {'status': 'RECORDED', 'request_id': request, 'replayed': replayed,
             'run_id': 'a'*64, 'execution_id': ('c' if second else 'b')*64,
-            'context': context, 'financial_result': literal_financial()}
+            'request': stable, 'context': context, 'financial_result': {**literal_financial(), **cuts}}
 
 
 def synthetic_process_evidence(root):
     """Hand-authored UNIT TEST ONLY evidence; no subprocess execution implied."""
     next_pid = 1000
     def child(directory, name, *, result=None, barrier=None, counts=None, exit_code=0,
-              error=None, begin=False, killed=False, request_id='request'):
+              error=None, begin=False, killed=False, request_id='request', action='recorded'):
         nonlocal next_pid
         next_pid += 1
         pid = next_pid
-        request = {'action': 'recorded', 'request_id': request_id, 'fixture_role': 'SYNTHETIC_UNIT_TEST_TRANSCRIPT'}
+        database = '/test-only/databases/' + directory.relative_to(root).as_posix() + '/source.sqlite3'
+        request = {'action': action, 'db': database, 'fixture_role': 'SYNTHETIC_UNIT_TEST_TRANSCRIPT'}
+        if action == 'recorded':
+            request.update(request_id=result['request_id'] if result is not None else request_id,
+                           balance_at='2026-11-12T23:59:59.000000Z', knowledge_at='2026-11-13T01:00:00.000000Z')
+        elif action == 'admission':
+            request.update(snapshot=database + '.jsonl', envelope=database + '.envelope.json', busy_timeout_ms=100)
+        else:
+            request.update(policy={'epoch': 2, 'fixture_role': 'SYNTHETIC_UNIT_TEST_POLICY'},
+                           expected_epoch=1, expected_hash='e'*64, busy_timeout_ms=100)
+        if barrier:
+            request['barrier'] = barrier['point']
+        if begin:
+            request['observe_begin'] = True
         save(directory/(name+'-request.json'), request)
         settings = {'journal_mode': 'delete', 'synchronous': 2, 'busy_timeout': 250}
         messages = [{'type': 'READY', 'pid': pid, 'origin': ORIGIN, 'interpreter': '/test-only/python',
@@ -102,7 +120,9 @@
         if result is not None:
             event = {'type': 'RESULT', 'pid': pid, 'result': result, 'counts': DURABLE}
             if result.get('status') == 'RECORDED':
-                event['ack'] = {'exit_code': 0, 'argv': ['reconcile-recorded'], 'stdout': json.dumps(result)}
+                event['ack'] = {'exit_code': 0, 'argv': ['reconcile-recorded', '--db', database,
+                               '--balance-at', request['balance_at'], '--knowledge-at', request['knowledge_at'],
+                               '--request-id', request['request_id'], '--busy-timeout-ms', '250'], 'stdout': json.dumps(result)}
             messages.append(event)
         row = {'pid': pid, 'exit_code': exit_code, 'joined': True, 'forced_timeout_cleanup': False,
                'started_at': 'TEST_ONLY_NOT_AN_EXECUTION', 'cwd': '/test-only',
@@ -127,19 +147,20 @@
                  'after_retry_counts': DURABLE, 'retry_replayed': committed, 'retry_execution_id': retry['execution_id']})
     for name, (action, timing) in RACES.items():
         directory = root/(name+'-fixture')
-        written = {'status': 'COMPLETE'} if action == 'admission' else {'epoch': 2}
-        second = literal_result(protected=True, receipts=31 if action == 'admission' else 30, epoch=1 if action == 'admission' else 2, second=True)
+        written = {'status': 'COMPLETE'} if action == 'admission' else {
+            'epoch': 2, 'payload': {'epoch': 2, 'fixture_role': 'SYNTHETIC_UNIT_TEST_POLICY'}}
+        second = literal_result('second-cut', protected=True, receipts=31 if action == 'admission' else 30, epoch=1 if action == 'admission' else 2, second=True)
         if timing == 'before':
-            child(directory, 'writer-before-cut', result=written)
+            child(directory, 'writer-before-cut', result=written, action=action)
             child(directory, 'execution', result=second)
         else:
-            first = literal_result(protected=True, epoch=1)
+            first = literal_result('first-cut', protected=True, epoch=1)
             child(directory, 'execution-holder', result=first, barrier={'point': 'execution_after_begin', 'in_transaction': True})
             if action == 'admission':
-                child(directory, 'writer-contender', result={'status': 'RETRYABLE_BUSY', 'responses': [], 'rejection': {'durable': False}}, begin=True)
+                child(directory, 'writer-contender', result={'status': 'RETRYABLE_BUSY', 'responses': [], 'rejection': {'durable': False}}, begin=True, action=action)
             else:
-                child(directory, 'writer-contender', error='SQLITE_BUSY', exit_code=2, begin=True)
-            child(directory, 'writer-after-cut', result=written)
+                child(directory, 'writer-contender', error='SQLITE_BUSY', exit_code=2, begin=True, action=action)
+            child(directory, 'writer-after-cut', result=written, action=action)
             child(directory, 'later-execution', result=second)
             save(directory/'cut-observation.json', {'action': action, 'busy_is_not_commit': True,
                  'first_execution_id': first['execution_id'], 'second_execution_id': second['execution_id'],
```

## tests/test_release_test_scope.py

Stage12.1 authorizes only the two complete synthetic process setup helpers or exact current release metadata. All old test method ASTs remain identical.

Before: `f6d5feaf085ddc751d8625a8b77a764c8a7ee400a028c97481d1bd213becc8a5` (7985 bytes). After: `7bc2d0337f1d757acb369785eb5ccea97d8a57a453e166428f8dd4190befde4f` (7985 bytes).

```diff
--- 
+++ 
@@ -16,7 +16,7 @@
 
 ROOT = Path(__file__).resolve().parents[1]
 BASELINE_PATH = 'contracts/release-tests-baseline-0.6.0.json'
-CONTRACT_PATH = 'contracts/release-test-scope-0.10.0.json'
+CONTRACT_PATH = 'contracts/release-test-scope-0.10.1.json'
 BASELINE = json.loads((ROOT / BASELINE_PATH).read_text())
 SPEC = importlib.util.spec_from_file_location('scope_release_verifier', ROOT / 'scripts/verify_release.py')
 verify = importlib.util.module_from_spec(SPEC)
@@ -35,7 +35,7 @@
     identities = list(declared_ids())
     current = ROOT / CONTRACT_PATH
     identity = ({'path':CONTRACT_PATH, 'bytes':current.stat().st_size,
-                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.10.0'}
+                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.10.1'}
                 if current.exists() else {})
     return dict(status='PASS', discovered=len(identities), executed=len(identities),
                 discovered_ids=identities, executed_ids=list(identities), scope_identity=identity,
```

The separate pinned 0.10.0 scope remains 186212 bytes / SHA-256 80ab84b011000db8b710b267e850963ec2da0a15063ee516896f14119d5ef8ec. Ordinary validation never authors a new expected roster. Expected/discovered/executed unique identities must be equal, with zero skips/xfails/errors/failures. Synthetic transcript fixtures are not real process evidence.
