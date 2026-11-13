"""Synthetic correction wire format; not an official KVMKS contract."""
import re
from datetime import date
from .model import amount, dumps, integer, timestamp


class CorrectionError(ValueError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(f"{code}: {detail}")


def fail(code, detail):
    raise CorrectionError(code, detail)


def identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value) is not None


def event_key(target):
    return dumps(["event", target["source"], target["platform"], target["business_day"], target["ref"]])


def normalize_correction(raw, config):
    r = dict(raw)
    kind = r["kind"]
    common = {"kind", "source", "platform", "asset", "batch_id"}
    if r.get("source") != config["platform"] or r.get("platform") != config["platform"]:
        fail("CORRECTION_PLATFORM_MISMATCH", "corrections must come from the configured platform")
    if not isinstance(r.get("asset"), str) or r["asset"] not in config["assets"]:
        fail("UNKNOWN_CORRECTION_ASSET", "unknown asset")
    if not identifier(r.get("batch_id")):
        fail("INVALID_CORRECTION_BATCH_ID", "batch_id is required")
    if kind == "correction_manifest":
        if "version" in r:
            fail("UNSUPPORTED_MANIFEST_REVISION", "correction batches are immutable")
        if set(r) != common | {"coverage_from", "coverage_to", "expected_count"}:
            fail("INVALID_CORRECTION_MANIFEST", "unexpected or missing fields")
        r["coverage_from"], r["coverage_to"] = timestamp(r["coverage_from"]), timestamp(r["coverage_to"])
        if r["coverage_from"] >= r["coverage_to"]:
            fail("INVALID_CORRECTION_COVERAGE", "coverage must be a nonempty (from,to] economic interval")
        r["expected_count"] = integer(r["expected_count"])
        return r, dumps([kind, r["source"], r["platform"], r["asset"], r["batch_id"]])
    mode = r.get("mode")
    if mode not in ("VOID", "REPLACE"):
        fail("UNSUPPORTED_CORRECTION_MODE", "only full VOID or amount-only REPLACE is supported")
    if "reverse_amount" in r or "partial_amount" in r:
        fail("UNSUPPORTED_PARTIAL_REVERSAL", "reverse effects are derived from the original event")
    if mode == "VOID" and "replacement_amount" in r:
        fail("VOID_WITH_REPLACEMENT_AMOUNT", "VOID must omit replacement_amount")
    fields = common | {"correction_id", "target", "target_occurred_at", "mode", "source_ref", "reason"}
    if mode == "REPLACE":
        fields.add("replacement_amount")
    if set(r) != fields:
        fail("UNSUPPORTED_CORRECTION_FIELDS", "only amount replacement is supported; all required envelope fields must be supplied")
    if not identifier(r["correction_id"]) or not identifier(r["source_ref"]):
        fail("INVALID_CORRECTION_REFERENCE", "correction_id and source_ref must be identifiers")
    if not isinstance(r["reason"], str) or not r["reason"].strip() or len(r["reason"]) > 500:
        fail("INVALID_CORRECTION_REASON", "a nonempty reason of at most 500 characters is required")
    target = r["target"]
    if not isinstance(target, dict):
        fail("INVALID_CORRECTION_TARGET", "target must be a complete original event key")
    if target.get("kind") == "correction":
        if target.get("correction_id") == r["correction_id"]:
            fail("SELF_REFERENCE", "a correction cannot target itself")
        fail("UNSUPPORTED_CORRECTION_CHAIN", "correction targets and cycles are unsupported")
    if target.get("kind") == "opening":
        fail("UNSUPPORTED_OPENING_REVISION", "opening balances are immutable")
    if set(target) != {"kind", "source", "platform", "business_day", "ref"} or target["kind"] != "event":
        fail("INVALID_CORRECTION_TARGET", "only a full original event key is permitted")
    if target["source"] != r["source"] or target["platform"] != r["platform"]:
        fail("TARGET_PLATFORM_MISMATCH", "target must belong to the same source/platform")
    if not identifier(target["ref"]):
        fail("INVALID_CORRECTION_TARGET", "invalid event reference")
    try:
        date.fromisoformat(target["business_day"])
        r["target_occurred_at"] = timestamp(r["target_occurred_at"])
    except (ValueError, TypeError):
        fail("INVALID_TARGET_TIME", "target economic time and business day must be valid")
    if target["business_day"] != r["target_occurred_at"][:10]:
        fail("TARGET_DAY_MISMATCH", "target key day must equal asserted UTC economic date")
    if r["target_occurred_at"] <= config["opening_at"]:
        fail("UNSUPPORTED_OPENING_HORIZON", "only events strictly after the immutable opening may be corrected")
    if mode == "REPLACE":
        try:
            r["replacement_amount"] = amount(r["replacement_amount"], config["assets"][r["asset"]], positive=True)
        except (ValueError, TypeError):
            fail("INVALID_REPLACEMENT_AMOUNT", "positive decimal text within asset precision is required")
    return r, dumps([kind, r["source"], r["platform"], r["correction_id"]])
