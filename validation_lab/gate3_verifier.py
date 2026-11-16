"""Finite Gate 3 evidence guards; not an institutional source authenticator.

Caller-selected hashes, row identities and LAB trust facts must come from the
reviewed external catalog, never from the candidate under review. Historical
Gate 2 parsers remain byte-identical. These guards do not change stage2-v2.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re

from validation_lab import gate2_public_data, identity_reference, public_data


def require(condition, reason):
    if not condition:
        raise ValueError("GATE3_EVIDENCE: " + reason)


def verify_raw(raw_bytes, expected_sha256):
    """Check an externally selected immutable byte corpus, including presence."""
    require(type(raw_bytes) is bytes and 0 < len(raw_bytes) <= 64 * 1024 * 1024,
            "RAW_BYTES_ABSENT_OR_LIMIT")
    require(type(expected_sha256) is str and
            re.fullmatch("[0-9a-f]{64}", expected_sha256) is not None,
            "EXTERNAL_PIN_FORMAT")
    require(hashlib.sha256(raw_bytes).hexdigest() == expected_sha256,
            "EXTERNAL_CORPUS_PIN_MISMATCH")


def verify_treasury(rows, detail, record_date, *, raw_bytes,
                    expected_raw_sha256, expected, field="open_today_bal",
                    publication_vintage="UNKNOWN"):
    """Bind decoded rows and mapping claims to one reviewed modern raw corpus.

An unavailable publication vintage remains UNKNOWN. Retrieval time cannot
establish a publication version. Literal source identities are supplied by the
external catalog; a matching equation alone cannot authenticate selected rows.
"""
    verify_raw(raw_bytes, expected_raw_sha256)
    decoded = public_data.fiscal_api_rows(raw_bytes)
    require(rows == decoded, "DECODED_ROWS_DIFFER_FROM_RAW")
    require(record_date == expected["date"] and record_date >= "2022-04-18",
            "REVIEWED_MODERN_DATE_REQUIRED")
    require(field == expected["field"] == "open_today_bal",
            "WRONG_POST_TRANSITION_FIELD")
    require(publication_vintage == expected["publication_vintage"] == "UNKNOWN",
            "UNSUPPORTED_PUBLICATION_VINTAGE")
    selected = [r for r in rows if r.get("record_date") == record_date]
    require(len(selected) == 4, "EXACT_FOUR_SELECTED_ROWS_REQUIRED")
    observed = [(r.get("src_line_nbr"), r.get("account_type"),
                 r.get("open_today_bal")) for r in selected]
    require(observed == list(zip(expected["lines"], expected["accounts"],
                                 expected["amounts"])),
            "EXTERNAL_ROW_IDENTITY_OR_VALUE_MISMATCH")
    require(all(r.get("table_nbr") == "I" and
                r.get("sub_table_name") == "Cash Balance Details" and
                r.get("close_today_bal") == "null" for r in selected),
            "REVIEWED_TRANSITION_SCHEMA_MISMATCH")
    result = gate2_public_data.direct_day(rows, detail, record_date)
    require(result["residual_million_usd"] == expected["expected_residual"],
            "EXTERNAL_LITERAL_ARITHMETIC_MISMATCH")
    require(all(c["equal_to_table_i"] for c in
                result["table_ii_cross_checks"].values()),
            "TABLE_II_CONTROL_MISMATCH")
    return result


def verify_sec(raw_bytes, url, landing_bytes, *, expected_raw_sha256,
               expected_url, candidate_text=None):
    """Keep exact official link, byte corpus and decoded body together.

Existing source symbol-bound violations are disclosed as warnings. They are
neither dropped nor relabelled as natural financial fraud. The corpus pin
rejects any newly substituted identity or symbol independently of format.
"""
    verify_raw(raw_bytes, expected_raw_sha256)
    require(url == expected_url and
            url in gate2_public_data.official_sec_links(landing_bytes),
            "REVIEWED_OFFICIAL_LINK_REQUIRED")
    text, metadata = gate2_public_data.sec_zip_text(raw_bytes)
    require(candidate_text is None or candidate_text == text,
            "DECODED_SEC_ROWS_DIFFER_FROM_RAW")
    profile = public_data.ftd_profile(text)
    require(profile["status"] == "VALID_WITHIN_DECLARED_CHECKS",
            "SEC_FORMAT_OR_DUPLICATE_IDENTITY")
    warnings = []
    for line, row in enumerate(csv.DictReader(io.StringIO(text), delimiter="|"), 2):
        if not 1 <= len(row["SYMBOL"]) <= 10:
            warnings.append({"line": line, "settlement_date": row["SETTLEMENT DATE"],
                             "cusip": row["CUSIP"], "symbol": row["SYMBOL"],
                             "reason": "OFFICIAL_DICTIONARY_SYMBOL_LENGTH"})
    return {**profile, "symbol_bound_warnings": warnings, "trailer": metadata["trailer"],
            "source_authenticity": "NOT_CRYPTOGRAPHICALLY_ATTESTED"}


def verify_identity(envelope, events, candidate_context, expected_context):
    """Reject context replacement before checking a LAB signature.

The external context is still LAB-issued, not independent institutional truth.
The caller is responsible for obtaining it separately from the candidate.
"""
    require(isinstance(expected_context, identity_reference.TrustContext) and
            candidate_context == expected_context, "EXTERNAL_TRUST_CONTEXT_MISMATCH")
    return identity_reference.verify_reference(envelope, events, expected_context)


def verify_benchmark(record, expected_mode, expected_bindings, evidence_root):
    """Use the independent raw-record arithmetic and timing consistency audit."""
    from scripts.validation.audit_gate3_comparison import audit
    require(expected_mode == "full" and record.get("mode") == expected_mode,
            "EXTERNAL_BENCHMARK_SCOPE_MISMATCH")
    require(record.get("bindings") == expected_bindings,
            "EXTERNAL_BENCHMARK_SOURCE_MISMATCH")
    return audit(record, evidence_root)
