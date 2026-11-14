# Stage 10 narrow fixture changes

The task explicitly permits current-release metadata and necessary narrow setup changes. No old test identity is removed, no assertion is deleted, and no financial expected value changes. The 472-ID baseline is pinned to `contracts/release-test-scope-0.7.1.json` (SHA-256 `2e21ae9f60ec7163af140d9f8e2eb91f33d3492e6b3edb1b3b4a86430a736a7e`). The ordinary verifier never derives or updates its expected roster.

The independent historical helper `tests/source_auth_legacy_fixtures.py` freezes the actual Stage 4 DDL from accepted commit `c49f1a1752caf3083bedc8aa797e77023c3db7d4`. It starts from the existing independent schema-3 fixture and constructs the real schema-4 objects. It does not invoke current migrations or manufacture a schema-4 version marker on a schema-5 layout.

## tests/test_corrections.py

The migration postcondition names the current schema target 5; all old columns, IDs, saved payload and restore assertions are retained.

Before: 28654 bytes, SHA-256 `d233406aaebe9aa699de29c3ac86149d3c1967570eb3a39790296a127f70cd40`. After: 28654 bytes, SHA-256 `9c0c123105965bbe78ab4835801d87225807ff9524655f250c27e1e4f0dc0cf4`.

## tests/test_receipt_index.py

Fresh and migrated current-target metadata now names additive schema 5; the deliberately unsupported future-version fixture becomes 6. All corruption rejection and preserved-row assertions stay intact.

Before: 18912 bytes, SHA-256 `9a3be65e59e5c53f9799de137cf5d07bfe7478d52776fba6420ab56eebc0e585`. After: 18918 bytes, SHA-256 `0f2f036a91a6a2c88ef4d6f797ff1cd6181098ccff2a4b69917c0c07d3aab0d3`.

## tests/test_admission_migrations.py

Current migration-target metadata becomes 5; only the named historical schema-4 fixture setup uses independently frozen schema-4 DDL, preserving all historical assertions.

Before: 14580 bytes, SHA-256 `203bba92c1a5d4f923738989ee0326712b2c1b70b98002337a2268f803637bb2`. After: 14669 bytes, SHA-256 `b2056652dffbf442b813ee0a3c1a4fd792d0c97968ddc1f3cd643bef6d404561`.

## tests/test_release_test_scope.py

The current fixed-roster fixture points to 0.8.0; historical independent baseline and all acceptance/rejection assertions remain unchanged.

Before: 7983 bytes, SHA-256 `555a058ff68c9a80922230c566a27b8f8eba2b6d6a27bc43a2d51780dcc7d37e`. After: 7983 bytes, SHA-256 `d0843e930098b2c0a40612e7479cd2a71be2514bb370676201a66fe9270dc10b`.

## tests/test_admission_maintenance_release.py

The old report_fixture exception fixture is loaded from its pinned historical 0.7.1 contract, so its original rejection tests retain their exact meaning after the new ancestry step.

Before: 3931 bytes, SHA-256 `948bf180b8cca24c06292a0bfd835f61214763c936fea293b6635a87c37c6cee`. After: 4013 bytes, SHA-256 `1880fddbdbc45f2176c9eecb033152d4ba2cb1283a63839fe348bd76f4615a7c`.

## Exact permitted diff

```diff
--- baseline/tests/test_corrections.py
+++ current/tests/test_corrections.py
@@ -458,7 +458,7 @@
         self.assertEqual(result['before_digest'], result['after_digest'])
         db = sqlite3.connect(self.path)
         self.assert_legacy(db)
-        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 4)
+        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 5)
         self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
         db.close()
         store = Store(self.path)
--- baseline/tests/test_receipt_index.py
+++ current/tests/test_receipt_index.py
@@ -54,7 +54,7 @@
     def test_fresh_index_is_exactly_one_nonunique_binary_ascending_column(self):
         store = self.fresh()
         validate_current(store.db)
-        self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], 4)
+        self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], 5)
         listed = {r[1]: r for r in store.db.execute('PRAGMA index_list(receipts)')}
         self.assertEqual(set(listed), {'receipts_time', INDEX_NAME})
         self.assertEqual(tuple(listed[INDEX_NAME][2:]), (0, 'c', 0))
@@ -103,7 +103,7 @@
                 migrate_connection(db, fail)
             self.assertEqual(application_snapshot(db), before, point)
         self.assertTrue(migrate_connection(db))
-        self.assertEqual(db.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall(), [(2,), (3,), (4,)])
+        self.assertEqual(db.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall(), [(2,), (3,), (4,), (5,)])
         self.assertEqual(db.execute('SELECT description FROM schema_migrations WHERE version=2').fetchone()[0],
                          'Add immutable correction groups/effects; retain all Stage 1 columns')
         assert_preserved(db, before)
@@ -157,7 +157,7 @@
                 path = self.path / (case + '.sqlite3')
                 store = Store(path, self.config)
                 if case == 'future':
-                    store.db.execute('PRAGMA user_version=5')
+                    store.db.execute('PRAGMA user_version=6')
                 else:
                     store.db.execute('DROP INDEX receipts_hash_lookup')
                     if case == 'wrong_index':
--- baseline/tests/test_admission_migrations.py
+++ current/tests/test_admission_migrations.py
@@ -113,13 +113,13 @@
         self.assertTrue(before['correction_effects'])
         self.assertTrue(migrate_connection(db))
         validate_current(db)
-        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 4)
+        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 5)
         self.assertLessEqual(objects, set(db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master')))
         after = old_rows(db)
         for name, rows in before.items():
             actual = [row for row in after[name] if row[0] <= 3] if name == 'schema_migrations' else after[name]
             self.assertEqual(actual, rows, name)
-        self.assertEqual(db.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall(), [(2,), (3,), (4,)])
+        self.assertEqual(db.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall(), [(2,), (3,), (4,), (5,)])
         self.assertEqual(set(fixture['run_ids']), {row[0] for row in after['runs']})
         self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
         self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
@@ -159,7 +159,7 @@
         backup_bytes = saved.read_bytes()
         report = migrate_database(path, self.root / 'backups')
         self.assertEqual(report['from_version'], 3)
-        self.assertEqual(report['schema_version'], 4)
+        self.assertEqual(report['schema_version'], 5)
         self.assertEqual(report['before_digest'], report['after_digest'])
         for field in ('all_old_columns_equal', 'all_old_tables_equal', 'all_old_objects_equal',
                       'copy_rollback_verified', 'copy_restore_verified', 'idempotency_verified'):
@@ -175,7 +175,8 @@
         path = self.root / 'historical.sqlite3'
         db, fixture = schema3_history(path)
         expected = dict(db.execute('SELECT id,payload FROM runs'))
-        migrate_connection(db)
+        from source_auth_legacy_fixtures import install_historical_schema4
+        install_historical_schema4(db)
         db.close()
         before = path.read_bytes()
         selected = Selection((SourceSelection('history', path, tuple(fixture['run_ids']), 'History', {}),))
--- baseline/tests/test_release_test_scope.py
+++ current/tests/test_release_test_scope.py
@@ -16,7 +16,7 @@
 
 ROOT = Path(__file__).resolve().parents[1]
 BASELINE_PATH = 'contracts/release-tests-baseline-0.6.0.json'
-CONTRACT_PATH = 'contracts/release-test-scope-0.7.1.json'
+CONTRACT_PATH = 'contracts/release-test-scope-0.8.0.json'
 BASELINE = json.loads((ROOT / BASELINE_PATH).read_text())
 SPEC = importlib.util.spec_from_file_location('scope_release_verifier', ROOT / 'scripts/verify_release.py')
 verify = importlib.util.module_from_spec(SPEC)
@@ -35,7 +35,7 @@
     identities = list(declared_ids())
     current = ROOT / CONTRACT_PATH
     identity = ({'path':CONTRACT_PATH, 'bytes':current.stat().st_size,
-                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.7.1'}
+                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.8.0'}
                 if current.exists() else {})
     return dict(status='PASS', discovered=len(identities), executed=len(identities),
                 discovered_ids=identities, executed_ids=list(identities), scope_identity=identity,
--- baseline/tests/test_admission_maintenance_release.py
+++ current/tests/test_admission_maintenance_release.py
@@ -15,7 +15,7 @@
 
 class AdmissionMaintenanceReleaseTests(unittest.TestCase):
     def fixture_exception(self):
-        scope = scope_gate.load_test_scope(ROOT)
+        scope = scope_gate.checked_document(ROOT, scope_gate.BASELINE_PATH, scope_gate.BASELINE_BYTES, scope_gate.BASELINE_SHA256)
         return deepcopy(next(row for row in scope['fixture_exceptions']
                              if row.get('kind') == 'report-fixture-function-v1'))
 
```

The current contract stores these exact reversible edits. Reversal must recover each pinned baseline file byte for byte; changes outside the listed edits fail the release gate. New test sources and the independent historical helper have separate fixed file identities in the contract.
