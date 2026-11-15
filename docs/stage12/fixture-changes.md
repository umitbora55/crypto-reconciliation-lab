# Stage12 authorized fixture changes

All 661 accepted test identities remain. Old behavior and financial assertions are
preserved. Only current schema/version metadata literals and genuine historical
schema-5 fixture initialization change. Reversing every listed replacement
restores each complete pinned 0.9.1 file byte-for-byte. The future-version
negative fixture moves 6 → 7 because 6 is now an explicitly supported schema.

## tests/review_fixtures.py

Only explicitly authorized current schema/version metadata or genuine historical schema-5 setup; financial and behavior assertions are preserved.

Before: 3683 bytes / `e4754bc7deacbb92a248ced3e180dcde535c2003debaffbe2ff745f057590aaf`.

After: 3735 bytes / `1992dd7b9b912930c675071ee48ca6861bcff000e28c71232947c50107c513ca`.

```json
[
  {
    "old_text": "def create_source(folder, edge=False):",
    "new_text": "def create_source(folder, edge=False, *, target_schema=None):",
    "count": 1
  },
  {
    "old_text": "    store = Store(database, config)",
    "new_text": "    store = Store(database, config, target_schema=target_schema)",
    "count": 1
  }
]
```

## tests/test_admission_migrations.py

Only explicitly authorized current schema/version metadata or genuine historical schema-5 setup; financial and behavior assertions are preserved.

Before: 14669 bytes / `b2056652dffbf442b813ee0a3c1a4fd792d0c97968ddc1f3cd643bef6d404561`.

After: 14675 bytes / `a2339189b2a6c07f59e5f5a95487d2842b5811fa504658eb942ce94af7f9761c`.

```json
[
  {
    "old_text": "        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 5)",
    "new_text": "        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 6)",
    "count": 1
  },
  {
    "old_text": "        self.assertEqual(db.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall(), [(2,), (3,), (4,), (5,)])",
    "new_text": "        self.assertEqual(db.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall(), [(2,), (3,), (4,), (5,), (6,)])",
    "count": 1
  },
  {
    "old_text": "        self.assertEqual(report['schema_version'], 5)",
    "new_text": "        self.assertEqual(report['schema_version'], 6)",
    "count": 1
  }
]
```

## tests/test_corrections.py

Only explicitly authorized current schema/version metadata or genuine historical schema-5 setup; financial and behavior assertions are preserved.

Before: 28654 bytes / `9c0c123105965bbe78ab4835801d87225807ff9524655f250c27e1e4f0dc0cf4`.

After: 28654 bytes / `4d4fb96f33653c0fcbab2f8e27ee15f4784e22a2e47d8803d804f482c1b97daf`.

```json
[
  {
    "old_text": "        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 5)",
    "new_text": "        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 6)",
    "count": 1
  }
]
```

## tests/test_provenance_export.py

Only explicitly authorized current schema/version metadata or genuine historical schema-5 setup; financial and behavior assertions are preserved.

Before: 12045 bytes / `6cc980aac5f35c957514a47cea40cbfd8c93ad5cb75884bca82ebd7e97a9c534`.

After: 12062 bytes / `d09a7958385af91c35a04b6be37fe59d9360d3cfc7d16796e375152af76834d3`.

```json
[
  {
    "old_text": "        self.db, self.run_id = create_source(self.root / 'fixture')",
    "new_text": "        self.db, self.run_id = create_source(self.root / 'fixture', target_schema=5)",
    "count": 1
  }
]
```

## tests/test_provenance_maintenance_release.py

Only explicitly authorized current schema/version metadata or genuine historical schema-5 setup; financial and behavior assertions are preserved.

Before: 5181 bytes / `6ea66577e00fb08e616c08171acbe1ae06c33a346b13d785bbd8462649c16d26`.

After: 5182 bytes / `91ed1ff943823ebe5929ce2450e05977286a8f786dd668c54ced0364be147b97`.

```json
[
  {
    "old_text": "    setup = {'format': 'release-provenance-maintenance-v1', 'package_version': '0.9.1',",
    "new_text": "    setup = {'format': 'release-provenance-maintenance-v1', 'package_version': '0.10.0',",
    "count": 1
  }
]
```

## tests/test_provenance_verifier.py

Only explicitly authorized current schema/version metadata or genuine historical schema-5 setup; financial and behavior assertions are preserved.

Before: 26264 bytes / `391cc8e1f4a28a749e4f3b4cf2565e5bae105cdcfa0fb7a52569115b94542290`.

After: 26281 bytes / `e5f0298e18101f822ce525405c9d2ea8ab28e5c240d92864fd79ef57b30b3fb7`.

```json
[
  {
    "old_text": "        store = Store(database, CONFIG)",
    "new_text": "        store = Store(database, CONFIG, target_schema=5)",
    "count": 1
  }
]
```

## tests/test_receipt_index.py

Only explicitly authorized current schema/version metadata or genuine historical schema-5 setup; financial and behavior assertions are preserved.

Before: 18918 bytes / `0f2f036a91a6a2c88ef4d6f797ff1cd6181098ccff2a4b69917c0c07d3aab0d3`.

After: 18924 bytes / `3d64e7d35f3643cfd2d75f9e9030027436f00d9c5cfe1878313d2c0c4ba751fd`.

```json
[
  {
    "old_text": "        self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], 5)",
    "new_text": "        self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], 6)",
    "count": 1
  },
  {
    "old_text": "        self.assertEqual(db.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall(), [(2,), (3,), (4,), (5,)])",
    "new_text": "        self.assertEqual(db.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall(), [(2,), (3,), (4,), (5,), (6,)])",
    "count": 1
  },
  {
    "old_text": "                    store.db.execute('PRAGMA user_version=6')",
    "new_text": "                    store.db.execute('PRAGMA user_version=7')",
    "count": 1
  }
]
```

## tests/test_release_test_scope.py

Only explicitly authorized current schema/version metadata or genuine historical schema-5 setup; financial and behavior assertions are preserved.

Before: 7983 bytes / `614e18dffad9f86b360f1ac23fbc972cfdd03a0e99c0775c28ded85d94d06c74`.

After: 7985 bytes / `f6d5feaf085ddc751d8625a8b77a764c8a7ee400a028c97481d1bd213becc8a5`.

```json
[
  {
    "old_text": "CONTRACT_PATH = 'contracts/release-test-scope-0.9.1.json'",
    "new_text": "CONTRACT_PATH = 'contracts/release-test-scope-0.10.0.json'",
    "count": 1
  },
  {
    "old_text": "                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.9.1'}",
    "new_text": "                 'sha256':hashlib.sha256(current.read_bytes()).hexdigest(), 'release':'0.10.0'}",
    "count": 1
  }
]
```

## tests/test_source_auth_migrations.py

Only explicitly authorized current schema/version metadata or genuine historical schema-5 setup; financial and behavior assertions are preserved.

Before: 6808 bytes / `760dce83418595a3e09fe3ab75184447d543f1854c84ed322b281775cb6482e5`.

After: 6811 bytes / `e9efe805dfb83078c48e479cccae685204a2888fcb775b9a0d550ec73a38486a`.

```json
[
  {
    "old_text": "            self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], 5)",
    "new_text": "            self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], 6)",
    "count": 1
  },
  {
    "old_text": "            self.assertEqual([r[0] for r in store.db.execute('SELECT version FROM schema_migrations ORDER BY version')], [2, 3, 4, 5])",
    "new_text": "            self.assertEqual([r[0] for r in store.db.execute('SELECT version FROM schema_migrations ORDER BY version')], [2, 3, 4, 5, 6])",
    "count": 1
  }
]
```

Historical scope files are unchanged. The new 0.10.0 scope retains every prior
anchor and adds a separate byte-pinned 0.9.1 binding. Its current-fixture
validator contains a finite exact-expression whitelist; it does not grant
permission to change an arbitrary assertion, mock a schema validator, or create
a fake downgraded database.
