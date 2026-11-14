# Signed snapshot profile v1

This application profile uses DSSE 1.0.2 PAE and Ed25519 supplied by the optional
`cryptography==50.0.2` dependency. It does not implement cryptographic primitives,
PKI, certificate discovery, freshness or general multi-signature DSSE support.

The payload type is
`application/vnd.crypto-reconciliation.source-admission.v1+json`. One envelope
contains one signature and a nonempty ASCII key ID. The ID only locates an
operator-installed historical public key; it does not grant authority. Envelope
extensions are ignored and cannot supply trust. The closed statement fields are
`format`, `source`, `receiver`, `configuration_digest`, `stream_id`, `plan`, and
`capabilities`; format is `source-admission-statement-v1`. The complete existing
`admission-plan-v1` binds hash, byte count, line count and framing. Capabilities are
exact `{source, platform, asset, kind, channel}` tuples; there are no wildcards.

The envelope is bounded to 128 KiB and its decoded payload to 64 KiB. JSON is
strict UTF-8, rejects duplicate keys, nonfinite numbers, lone surrogates, more than
32 levels and more than 20,000 nodes. Integer identity fields reject booleans.
Base64 is strict and signatures are exactly 64 bytes; public keys are 32 bytes.
Diagnostics contain fixed safe ASCII messages instead of hostile source text.

The receiver snapshots a finite feed once: at most 16 MiB, 10,000 LF-terminated
lines and 65,536 bytes per line; no BOM, CR or empty lines. The same immutable
memory bytes provide the plan, scope and delivery bodies. Verification uses the
exact decoded payload bytes, never reserialized JSON. The parsed object is local
to that verified byte sequence. Files are not reopened after verification. These
bounds and local stat checks do not protect against a malicious database owner.

## Authority fields by kind

Every record requires string `kind`, `source`, `platform` and `asset`. Only the
existing kind-specific field names are accepted. Report and manifest require a
string `stream`. Corrections require an exact event target with matching source
and platform; the asset belongs to the correction envelope, not its target.

| Kind | Channel | Required source |
| --- | --- | --- |
| opening | none, including external opening scope | configured platform |
| event | none; stream/balance_at are forbidden | configured platform |
| report | investor, platform_custody, external_custody | custodian only for external_custody |
| manifest | opening, event, investor, platform_custody, external_custody | custodian only for external_custody |
| correction | none | configured platform |
| correction_manifest | none | configured platform |

The extracted set must equal the signed capability inventory. A file has exactly
one publisher. Missing/ambiguous authority is rejected before the first write.
Financial amount and time validity remain the existing core's responsibility;
a clearly authorized invalid amount can therefore produce an INVALID receipt.
A signature does not make source-provided received_at a trustworthy clock, nor
prove that a reported custody amount is correct. Reconciliation remains explicit.

Public RFC 8032 vectors and literal PAE examples are independent crypto tests.
Demo signing seeds are conspicuously TEST-ONLY fixtures, not operational secrets.

## Technical sources

Accessed 14 November 2026: [DSSE protocol 1.0.2](https://github.com/dsse-lf/dsse/blob/master/protocol.md)
and [envelope 1.0.2](https://github.com/dsse-lf/dsse/blob/master/envelope.md) define
PAE and exact payload bytes; [RFC 8032 section 7.1](https://www.rfc-editor.org/rfc/rfc8032#section-7.1)
supplies public Ed25519 vectors. The [cryptography Ed25519 API](https://cryptography.io/en/stable/hazmat/primitives/asymmetric/ed25519/)
provides the implementation. Version 50.0.2 was actually installed locally with
cffi 2.1.1 and pycparser 3.12. The closed statement, receiver binding, capability
tuples, limits and policy epochs are this prototype's design decisions; they are
not institutional or regulatory requirements derived from those standards.

## Primary technical sources

- [DSSE protocol 1.0.2](https://github.com/dsse-lf/dsse/blob/master/protocol.md): PAE framing; this application's closed statement is a separate design choice.
- [DSSE envelope](https://github.com/dsse-lf/dsse/blob/master/envelope.md): verified decoded payload bytes and untrusted key ID hints.
- [RFC 8032, section 7.1](https://www.rfc-editor.org/rfc/rfc8032.txt): public Ed25519 test vectors, January 2017. Vector values are copied as independent constants in tests.
- [cryptography Ed25519 API](https://cryptography.io/en/stable/hazmat/primitives/asymmetric/ed25519/): library-provided key, sign and verify operations.

The selected sources were checked during the 14 November 2026 implementation.
Source claims concern the signing protocol and primitive; local policy, replay,
bounds and capability rules above are explicitly application design assumptions.
