"""Offline process-transcript regressions; these tests launch no workers."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from test_recorded_execution_release_gate import (
    gate, synthetic_process_evidence, load, save, ORIGIN, KILLS, RACES, SAME,
)


class ProcessRequestBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'transcripts'
        synthetic_process_evidence(self.root)

    def check(self):
        return gate.validate_execution_process_evidence(self.root, package_origin=ORIGIN, isolated=False)

    def folder(self, name):
        return self.root / (name + '-fixture')

    def change(self, path, key, value):
        original = path.read_bytes()
        row = load(path)
        row[key] = value
        save(path, row)
        return original

    def rejects(self):
        with self.assertRaisesRegex(ValueError, 'EXECUTION_PROCESS: (request|ACK) binding'):
            self.check()

    def test_complete_fixed_transcript_is_accepted(self):
        result = self.check()
        self.assertEqual((result['status'], result['test_count'], result['process_count']), ('PASS', 8, 27))

    def test_relative_recorded_paths_are_compared_to_remote_cwd_without_stat(self):
        for path in self.root.rglob('*-request.json'):
            row = load(path)
            row['db'] = '../' + row['db'].removeprefix('/test-only/')
            save(path, row)
            process_path = path.with_name(path.name.replace('-request.json', '-process.json'))
            process = load(process_path)
            process['cwd'] = '/test-only/work'
            save(process_path, process)
        self.assertEqual(self.check()['status'], 'PASS')

    def test_policy_after_cut_unrelated_contender_database_is_rejected(self):
        path = self.folder('test_separate_process_policy_after_cut_cannot_mix_with_first_context') / 'writer-contender-request.json'
        self.change(path, 'db', '/test-only/another-policy.sqlite3')
        self.rejects()

    def test_admission_after_cut_unrelated_contender_database_is_rejected(self):
        path = self.folder('test_separate_process_admission_after_cut_cannot_mix_with_first_context') / 'writer-contender-request.json'
        self.change(path, 'db', '/test-only/another-admission.sqlite3')
        self.rejects()

    def test_database_binding_applies_to_other_roles_and_families(self):
        cases = [
            (next(iter(KILLS)) + '-fixture/fresh', 'interrupted'),
            (next(iter(KILLS)) + '-fixture/existing', 'retry'),
            ('test_separate_process_policy_before_cut_is_wholly_present-fixture', 'writer-before-cut'),
            ('test_separate_process_admission_before_cut_is_wholly_present-fixture', 'execution'),
            ('test_separate_process_policy_after_cut_cannot_mix_with_first_context-fixture', 'execution-holder'),
            ('test_separate_process_admission_after_cut_cannot_mix_with_first_context-fixture', 'writer-after-cut'),
            ('test_separate_process_policy_after_cut_cannot_mix_with_first_context-fixture', 'later-execution'),
            (SAME + '-fixture', 'first-process'),
            (SAME + '-fixture', 'second-process'),
            (SAME + '-fixture', 'second-process-retry'),
        ]
        for folder, role in cases:
            with self.subTest(folder=folder, role=role):
                path = self.root / folder / (role + '-request.json')
                original = self.change(path, 'db', '/test-only/different.sqlite3')
                try:
                    self.rejects()
                finally:
                    path.write_bytes(original)

    def test_wrong_action_cannot_claim_another_worker_role(self):
        cases = [
            (next(iter(KILLS)) + '-fixture/fresh', 'interrupted', 'policy'),
            ('test_separate_process_policy_before_cut_is_wholly_present-fixture', 'writer-before-cut', 'recorded'),
            ('test_separate_process_admission_after_cut_cannot_mix_with_first_context-fixture', 'writer-contender', 'policy'),
            (SAME + '-fixture', 'second-process', 'admission'),
        ]
        for folder, role, action in cases:
            with self.subTest(folder=folder, role=role):
                path = self.root / folder / (role + '-request.json')
                original = self.change(path, 'action', action)
                try:
                    self.rejects()
                finally:
                    path.write_bytes(original)

    def test_cut_and_request_identity_bind_interrupted_or_busy_children(self):
        for folder, role, key, value in [
            (next(iter(KILLS)) + '-fixture/fresh', 'interrupted', 'balance_at', '2026-11-11T23:59:59Z'),
            (SAME + '-fixture', 'second-process', 'knowledge_at', '2026-11-14T01:00:00Z'),
            (SAME + '-fixture', 'second-process', 'request_id', 'different-request'),
        ]:
            with self.subTest(role=role, key=key):
                path = self.root / folder / (role + '-request.json')
                original = self.change(path, key, value)
                try:
                    self.rejects()
                finally:
                    path.write_bytes(original)

    def test_ack_database_request_id_and_cuts_must_match_request(self):
        path = self.folder(SAME) / 'second-process-retry-process.json'
        original = path.read_bytes()
        for flag, value in [
            ('--db', '/test-only/unrelated-ack.sqlite3'),
            ('--request-id', 'another-ack-request'),
            ('--balance-at', '2026-11-11T23:59:59Z'),
            ('--knowledge-at', '2026-11-14T01:00:00Z'),
        ]:
            with self.subTest(flag=flag):
                row = json.loads(original)
                ack = next(m for m in row['messages'] if m['type'] == 'RESULT')['ack']
                ack['argv'][ack['argv'].index(flag) + 1] = value
                save(path, row)
                try:
                    self.rejects()
                finally:
                    path.write_bytes(original)

    def test_ack_duplicate_binding_option_is_rejected(self):
        path = self.folder(SAME) / 'second-process-retry-process.json'
        row = load(path)
        ack = next(m for m in row['messages'] if m['type'] == 'RESULT')['ack']
        ack['argv'].extend(['--db', '/test-only/second-db.sqlite3'])
        save(path, row)
        self.rejects()

    def test_result_identity_and_cut_cannot_disagree_with_request_even_when_ack_matches(self):
        path = self.folder('test_separate_process_policy_before_cut_is_wholly_present') / 'execution-process.json'
        original = path.read_bytes()
        for key in ('request_id', 'balance_at', 'knowledge_at'):
            with self.subTest(key=key):
                row = json.loads(original)
                event = next(m for m in row['messages'] if m['type'] == 'RESULT')
                result = event['result']
                if key == 'request_id':
                    result[key] = 'different-result'
                else:
                    result['request'][key] = '2026-11-14T01:00:00Z'
                    result['context']['request'][key] = '2026-11-14T01:00:00Z'
                    result['financial_result'][key] = '2026-11-14T01:00:00Z'
                event['ack']['stdout'] = json.dumps(result)
                save(path, row)
                try:
                    self.rejects()
                finally:
                    path.write_bytes(original)

    def test_post_cut_writer_must_repeat_the_same_admission_or_policy_request(self):
        for action, key, value in [
            ('admission', 'snapshot', '/test-only/other.jsonl'),
            ('admission', 'envelope', '/test-only/other-envelope.json'),
            ('policy', 'expected_epoch', 9),
            ('policy', 'expected_hash', 'f'*64),
            ('policy', 'policy', {'epoch': 3}),
        ]:
            with self.subTest(action=action, key=key):
                path = self.folder('test_separate_process_' + action + '_after_cut_cannot_mix_with_first_context') / 'writer-after-cut-request.json'
                original = self.change(path, key, value)
                try:
                    self.rejects()
                finally:
                    path.write_bytes(original)

    def test_ambiguous_relative_cwd_is_not_a_remote_path_identity(self):
        path = self.folder('test_separate_process_policy_after_cut_cannot_mix_with_first_context') / 'writer-contender-process.json'
        self.change(path, 'cwd', 'relative-directory')
        self.rejects()

    def test_before_cut_policy_result_must_match_requested_epoch_and_payload(self):
        path = self.folder('test_separate_process_policy_before_cut_is_wholly_present') / 'writer-before-cut-request.json'
        for key, value in [('expected_epoch', 9), ('policy', {'epoch': 3})]:
            with self.subTest(key=key):
                original = self.change(path, key, value)
                try:
                    self.rejects()
                finally:
                    path.write_bytes(original)

