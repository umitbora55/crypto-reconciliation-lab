"""Bounded DSSE application profile using the library's Ed25519 implementation."""
import base64
import binascii
import hashlib
import json
import math
import re

PAYLOAD_TYPE = "application/vnd.crypto-reconciliation.source-admission.v1+json"
MAX_ENVELOPE = 128 * 1024
MAX_PAYLOAD = 64 * 1024


class AuthError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(code + ": " + message)


def require_auth():
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
    except ImportError as exc:
        raise AuthError("AUTH_DEPENDENCY", "install the optional auth extra (cryptography==50.0.2)") from exc
    return Ed25519PrivateKey, Ed25519PublicKey, InvalidSignature


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def strict_json(data, *, limit=MAX_PAYLOAD):
    if type(data) is not bytes or not 0 < len(data) <= limit:
        raise AuthError("AUTH_JSON", "JSON bytes are empty or exceed the size limit")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise AuthError("AUTH_JSON", "duplicate JSON key")
            result[key] = value
        return result
    def nonfinite(_):
        raise AuthError("AUTH_JSON", "nonfinite JSON number")
    def floating(value):
        result = float(value)
        if not math.isfinite(result):
            nonfinite(value)
        return result
    try:
        value = json.loads(data.decode("utf-8", errors="strict"), object_pairs_hook=unique,
                           parse_constant=nonfinite, parse_float=floating)
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, AuthError):
            raise
        raise AuthError("AUTH_JSON", "invalid UTF-8 or JSON") from exc
    stack, nodes = [(value, 0)], 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if depth > 32 or nodes > 20000:
            raise AuthError("AUTH_JSON", "JSON structural limit exceeded")
        if type(item) is str:
            if any(0xD800 <= ord(character) <= 0xDFFF for character in item):
                raise AuthError("AUTH_JSON", "lone surrogate is forbidden")
        elif type(item) is dict:
            stack.extend((child, depth + 1) for pair in item.items() for child in pair)
        elif type(item) is list:
            stack.extend((child, depth + 1) for child in item)
    return value


def identifier(value, name="identifier", *, limit=128):
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0," + str(limit - 1) + r"}", value) is None:
        raise AuthError("AUTH_FIELDS", "invalid ASCII " + name)
    return value


def hex_digest(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def pae(payload_type, payload):
    if type(payload_type) is not str or type(payload) is not bytes:
        raise AuthError("AUTH_FIELDS", "PAE requires a text type and exact payload bytes")
    encoded = payload_type.encode("utf-8")
    return b"DSSEv1 " + str(len(encoded)).encode("ascii") + b" " + encoded + b" " + str(len(payload)).encode("ascii") + b" " + payload


def public_key(seed):
    private, _, _ = require_auth()
    if type(seed) is not bytes or len(seed) != 32:
        raise AuthError("AUTH_KEY", "Ed25519 seed must be 32 bytes")
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    return private.from_private_bytes(seed).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def fingerprint(key):
    if type(key) is not bytes or len(key) != 32:
        raise AuthError("AUTH_KEY", "Ed25519 public key must be 32 bytes")
    return sha256(key)


def verify_signature(key, message, signature):
    _, public, invalid = require_auth()
    if type(key) is not bytes or len(key) != 32 or type(signature) is not bytes or len(signature) != 64:
        raise AuthError("AUTH_SIGNATURE", "invalid Ed25519 key or signature length")
    try:
        public.from_public_bytes(key).verify(signature, message)
    except (invalid, ValueError) as exc:
        raise AuthError("AUTH_SIGNATURE", "Ed25519 signature verification failed") from exc


def sign_statement(statement, seed, key_id):
    private, _, _ = require_auth()
    identifier(key_id, "key ID")
    public_key(seed)  # Validate the test/producer seed through the same library.
    payload = canonical(statement)
    if len(payload) > MAX_PAYLOAD:
        raise AuthError("AUTH_FIELDS", "statement exceeds the size limit")
    signature = private.from_private_bytes(seed).sign(pae(PAYLOAD_TYPE, payload))
    return canonical({"payloadType": PAYLOAD_TYPE, "payload": base64.b64encode(payload).decode("ascii"),
                      "signatures": [{"keyid": key_id, "sig": base64.b64encode(signature).decode("ascii")}]})


def _base64(value, limit):
    if type(value) is not str or not value.isascii():
        raise AuthError("AUTH_ENVELOPE", "Base64 must be ASCII text")
    try:
        result = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise AuthError("AUTH_ENVELOPE", "invalid Base64") from exc
    if not result or len(result) > limit or base64.b64encode(result).decode("ascii") != value:
        raise AuthError("AUTH_ENVELOPE", "noncanonical or oversized Base64")
    return result


def parse_envelope(data):
    envelope = strict_json(data, limit=MAX_ENVELOPE)
    if type(envelope) is not dict or envelope.get("payloadType") != PAYLOAD_TYPE:
        raise AuthError("AUTH_ENVELOPE", "unsupported payload type")
    signatures = envelope.get("signatures")
    if type(signatures) is not list or len(signatures) != 1 or type(signatures[0]) is not dict:
        raise AuthError("AUTH_ENVELOPE", "exactly one signature is required")
    item = signatures[0]
    key_id = identifier(item.get("keyid"), "key ID")
    payload = _base64(envelope.get("payload"), MAX_PAYLOAD)
    signature = _base64(item.get("sig"), 64)
    if len(signature) != 64:
        raise AuthError("AUTH_SIGNATURE", "Ed25519 signature must be 64 bytes")
    return payload, key_id, signature

# Explicit dependency preflight shared by CLI and portable demo.
require_crypto = require_auth
