"""Independent public RFC 8032 vectors and hostile profile inputs."""
import base64
import json
import unittest
from crypto_reconciliation_lab.source_auth.crypto import (AuthError, PAYLOAD_TYPE, canonical,
    pae, parse_envelope, public_key, sign_statement, strict_json, verify_signature)
from crypto_reconciliation_lab.source_auth.fixtures import CONFIG, TEST_KEYS, signed, small_records, snapshot
from crypto_reconciliation_lab.source_auth.scope import capabilities, snapshot_bytes, statement


class SourceAuthCryptoTests(unittest.TestCase):
    def test_rfc8032_public_empty_message_vector(self):
        # RFC 8032 section 7.1 TEST 1: expected signature is independent of our signer.
        public = bytes.fromhex('d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a')
        signature = bytes.fromhex('e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155'
                                  '5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b')
        verify_signature(public, b'', signature)
        self.assertEqual(public_key(bytes.fromhex(TEST_KEYS['P1-old'][0])), public)
        with self.assertRaisesRegex(AuthError, 'AUTH_SIGNATURE'):
            verify_signature(public, b'changed', signature)

    def test_rfc8032_public_one_byte_vector_and_wrong_key(self):
        public = bytes.fromhex('3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c')
        signature = bytes.fromhex('92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da'
                                  '085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00')
        verify_signature(public, b'\x72', signature)
        with self.assertRaises(AuthError):
            verify_signature(bytes.fromhex(TEST_KEYS['P1-old'][1]), b'\x72', signature)
        for wrong in (signature[:-1], signature + b'x'):
            with self.subTest(size=len(wrong)), self.assertRaises(AuthError):
                verify_signature(public, b'\x72', wrong)

    def test_literal_pae_counts_bytes_and_separates_type(self):
        self.assertEqual(pae('text/plain', b'hello'), b'DSSEv1 10 text/plain 5 hello')
        self.assertEqual(pae('x', b''), b'DSSEv1 1 x 0 ')
        self.assertEqual(pae('é', b'\x00\xff'), b'DSSEv1 2 \xc3\xa9 2 \x00\xff')
        self.assertNotEqual(pae('a b', b'c'), pae('a', b'b c'))

    def test_strict_json_rejects_duplicates_surrogates_nonfinite_depth(self):
        for bad in (b'{"x":1,"x":2}', b'{"\\ud800":1}', b'"\\udfff"', b'NaN', b'Infinity',
                    b'1e999', b'\xff', b'[' * 34 + b'0' + b']' * 34):
            with self.subTest(data=bad), self.assertRaises(AuthError) as error:
                strict_json(bad)
            self.assertTrue(str(error.exception).isascii())
        self.assertEqual(strict_json(b'{"finite":0.1}'), {'finite': 0.1})

    def test_profile_rejects_bad_base64_multiple_signature_and_payload_type(self):
        good = json.loads(signed(snapshot(small_records())))
        for field, value in (('payload', '***'), ('payloadType', 'text/plain'), ('signatures', []),
                             ('signatures', good['signatures'] * 2), ('payload', True)):
            bad = dict(good, **{field: value})
            with self.subTest(field=field, value=value), self.assertRaises(AuthError):
                parse_envelope(canonical(bad))
        bad = dict(good, signatures=[dict(good['signatures'][0], sig=base64.b64encode(b'x'*63).decode())])
        with self.assertRaises(AuthError):
            parse_envelope(canonical(bad))

    def test_verified_payload_keeps_exact_bytes_not_canonical_reconstruction(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        exact = b'{ "z" : 1, "a": 2 }'
        signature = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(TEST_KEYS['P1-old'][0])).sign(pae(PAYLOAD_TYPE, exact))
        wire = canonical({'payloadType':PAYLOAD_TYPE,'payload':base64.b64encode(exact).decode(),
                          'signatures':[{'keyid':'P1-old','sig':base64.b64encode(signature).decode()}],
                          'untrusted_public_key':'cannot grant authority'})
        payload, keyid, sig = parse_envelope(wire)
        self.assertEqual(payload, exact)
        self.assertEqual(keyid, 'P1-old')
        verify_signature(bytes.fromhex(TEST_KEYS['P1-old'][1]), pae(PAYLOAD_TYPE, payload), sig)
        with self.assertRaises(AuthError):
            verify_signature(bytes.fromhex(TEST_KEYS['P1-old'][1]), pae(PAYLOAD_TYPE, canonical(strict_json(payload))), sig)

    def test_statement_rejects_bool_integer_unknown_fields_and_false_scope(self):
        data = snapshot(small_records())
        snap = snapshot_bytes(data)
        value = strict_json(parse_envelope(signed(data))[0])
        for field in ('input_bytes', 'planned_lines'):
            bad = {**value, 'plan': {**value['plan'], field: True}}
            with self.subTest(field=field), self.assertRaises(AuthError):
                statement(bad, snap, CONFIG)
        for bad in ({**value,'extra':1}, {**value,'source':True}, {**value,'capabilities':[]}):
            with self.assertRaises(AuthError):
                statement(bad, snap, CONFIG)

    def test_snapshot_limits_and_required_single_publisher(self):
        for data in (b'', b'{}', b'{}\r\n', b'\xef\xbb\xbf{}\n', b' \n', b'x'*65536+b'\n', b'{}\n'*10001):
            with self.subTest(size=len(data)), self.assertRaises(AuthError):
                snapshot_bytes(data)
        records = small_records()
        records.append({'record':{'kind':'report','source':'C1','platform':'P1','asset':'ASSET_A',
                                  'stream':'external_custody'},'received_at':'bad'})
        with self.assertRaisesRegex(AuthError, 'one publisher'):
            capabilities(snapshot_bytes(snapshot(records)), CONFIG)
