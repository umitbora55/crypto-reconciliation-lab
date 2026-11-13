"""Strict synthetic wire contract. All quantities remain decimal text."""
import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Context, Decimal, localcontext

RULE_VERSION = "stage2-v2"
CONTEXT = Context(prec=64, Emin=-64, Emax=64)
for signal in CONTEXT.traps:
    CONTEXT.traps[signal] = True
STREAMS = ("opening", "event", "investor", "platform_custody", "external_custody")


def dumps(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(dumps(value).encode()).hexdigest()


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value
    ):
        raise ValueError("timezone-aware ISO 8601 timestamp required (microsecond maximum)")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical(value):
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if value == 0 else text


def amount(value, places, positive=False):
    if not isinstance(value, str) or not re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", value):
        raise ValueError("amount must be finite plain decimal text")
    if len(value) > 64 or ("." in value and len(value.split(".")[1]) > places):
        raise ValueError("excess decimal precision or input length")
    with localcontext(CONTEXT):
        number = Decimal(value)
        if number < 0 or (positive and number == 0) or number >= Decimal("1e40"):
            raise ValueError("amount outside permitted range [0, 1e40); events must be positive")
        return canonical(+number)


def integer(value, minimum=0):
    if type(value) is not int or value < minimum or value > 2**31 - 1:
        raise ValueError("bounded non-negative integer required")
    return value


def config_validate(config):
    required = {"platform", "custodian", "investors", "assets", "opening_at"}
    if not isinstance(config, dict) or set(config) != required:
        raise ValueError("configuration fields do not match contract")
    c = json.loads(dumps(config))
    if not isinstance(c["investors"], list) or not isinstance(c["assets"], dict):
        raise ValueError("investors must be a list and assets a precision mapping")
    ids = [c["platform"], c["custodian"], *c["investors"]]
    if (not c["investors"] or not c["assets"]
            or any(not isinstance(x, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", x) for x in ids)
            or len(ids) != len(set(ids))
            or {"platform", "external", "*"} & set(c["investors"])):
        raise ValueError("distinct, nonempty platform, custodian and investor identifiers required")
    for name, places in c["assets"].items():
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name) or type(places) is not int or not 0 <= places <= 18:
            raise ValueError("asset precision must be an integer from 0 to 18")
    c["opening_at"] = timestamp(c["opening_at"])
    c["investors"] = sorted(c["investors"])
    return c


def normalize(raw, config):
    if not isinstance(raw, dict):
        raise ValueError("record must be an object")
    r = dict(raw)
    kind = r.get("kind")
    if kind in ("correction", "correction_manifest"):
        from .correction_model import normalize_correction
        return normalize_correction(r, config)
    common = {"kind", "source", "platform", "asset"}
    fields = {
        "opening": {"scope", "balance_at", "amount"},
        "event": {"business_day", "ref", "occurred_at", "sequence", "type", "from_investor", "to_investor", "custody", "amount"},
        "report": {"stream", "scope", "balance_at", "version", "amount"},
        "manifest": {"stream", "coverage_from", "coverage_to", "expected_count"},
    }
    if not isinstance(kind, str) or kind not in fields or set(r) != common | fields[kind]:
        raise ValueError("unknown kind, missing fields or unsupported extra fields")
    if not isinstance(r["asset"], str) or r["asset"] not in config["assets"] or r["platform"] != config["platform"]:
        raise ValueError("unknown asset or platform")
    stream = r.get("stream", kind)
    external = stream == "external_custody"
    if r["source"] != (config["custodian"] if external else config["platform"]):
        raise ValueError("unexpected source for stream")
    base = [r["source"], r["platform"]]
    if kind == "event":
        if r["type"] not in ("deposit", "withdrawal", "transfer"):
            raise ValueError("UNSUPPORTED_EVENT_TYPE: inline correction/reversal event types are not supported; use a correction envelope")
        r["occurred_at"] = timestamp(r["occurred_at"])
        if r["occurred_at"] <= config["opening_at"]:
            raise ValueError("event must follow opening snapshot")
        if r["business_day"] != r["occurred_at"][:10]:
            raise ValueError("business_day must equal UTC economic date")
        if not isinstance(r["ref"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", r["ref"]):
            raise ValueError("invalid event reference")
        r["sequence"] = integer(r["sequence"])
        sender, recipient = r["from_investor"], r["to_investor"]
        if r["type"] == "deposit":
            valid = sender is None and recipient in config["investors"] and r["custody"] in ("platform", "external")
        elif r["type"] == "withdrawal":
            valid = recipient is None and sender in config["investors"] and r["custody"] in ("platform", "external")
        else:
            valid = sender in config["investors"] and recipient in config["investors"] and sender != recipient and r["custody"] is None
        if not valid:
            raise ValueError("invalid event participants or customer custody location")
        key = [kind, *base, r["business_day"], r["ref"]]
    elif kind == "manifest":
        if stream not in STREAMS:
            raise ValueError("invalid manifest stream")
        r["coverage_from"] = timestamp(r["coverage_from"])
        r["coverage_to"] = timestamp(r["coverage_to"])
        if r["coverage_from"] > r["coverage_to"]:
            raise ValueError("inverted manifest coverage")
        r["expected_count"] = integer(r["expected_count"])
        key = [kind, *base, stream, r["asset"], r["coverage_from"], r["coverage_to"]]
    else:
        r["balance_at"] = timestamp(r["balance_at"])
        if kind == "opening":
            valid = r["scope"] in [*config["investors"], "platform", "external"] and r["balance_at"] == config["opening_at"]
        else:
            r["version"] = integer(r["version"], 1)
            valid = ((stream == "investor" and r["scope"] in config["investors"])
                     or (stream == "platform_custody" and r["scope"] == "platform")
                     or (stream == "external_custody" and r["scope"] == "external"))
        if not valid:
            raise ValueError("invalid report/opening scope or opening time")
        key = [kind, *base, stream, r["asset"], r["scope"], r["balance_at"]]
        if kind == "report":
            key.append(r["version"])
    if kind != "manifest":
        r["amount"] = amount(r["amount"], config["assets"][r["asset"]], kind == "event")
    return r, dumps(key)
