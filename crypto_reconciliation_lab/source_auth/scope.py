"""Extract authority only; financial validation remains in the existing core."""
from ..admission.feed import FeedSnapshot, MAX_BYTES, MAX_LINES, MAX_LINE_BYTES
from ..admission.runtime import validate_plan, validate_stream
from .crypto import AuthError, canonical, hex_digest, identifier, sha256, strict_json

COMMON = {"kind", "source", "platform", "asset"}
FIELDS = {
    "opening": COMMON | {"scope", "balance_at", "amount"},
    "event": COMMON | {"business_day", "ref", "occurred_at", "sequence", "type", "from_investor", "to_investor", "custody", "amount"},
    "report": COMMON | {"stream", "scope", "balance_at", "version", "amount"},
    "manifest": COMMON | {"stream", "coverage_from", "coverage_to", "expected_count"},
    "correction": COMMON | {"batch_id", "correction_id", "target", "target_occurred_at", "mode", "source_ref", "reason", "replacement_amount"},
    "correction_manifest": COMMON | {"batch_id", "coverage_from", "coverage_to", "expected_count"},
}
CHANNELS = {"report": {"investor", "platform_custody", "external_custody"},
            "manifest": {"opening", "event", "investor", "platform_custody", "external_custody"}}
CAP_FIELDS = {"source", "platform", "asset", "kind", "channel"}


def snapshot_bytes(data):
    if type(data) is not bytes or not 0 < len(data) <= MAX_BYTES:
        raise AuthError("AUTH_SNAPSHOT", "nonempty bounded exact snapshot bytes required")
    if data.startswith(b"\xef\xbb\xbf") or b"\r" in data or not data.endswith(b"\n"):
        raise AuthError("AUTH_SNAPSHOT", "LF framing without BOM or CR required")
    lines = tuple(part + b"\n" for part in data[:-1].split(b"\n"))
    if not 0 < len(lines) <= MAX_LINES or any(not line[:-1].strip() or len(line) > MAX_LINE_BYTES or not line.endswith(b"\n") for line in lines):
        raise AuthError("AUTH_SNAPSHOT", "invalid line count, framing or size")
    if any(line.count(b"\n") != 1 for line in lines):
        raise AuthError("AUTH_SNAPSHOT", "exactly one LF per line required")
    return FeedSnapshot(lines, sha256(data), len(data))


def capability(value, config):
    if type(value) is not dict or set(value) != CAP_FIELDS or any(type(v) is not str for v in value.values()):
        raise AuthError("AUTH_SCOPE", "exact string capability fields required")
    source, platform, asset, kind, channel = (value[k] for k in ("source", "platform", "asset", "kind", "channel"))
    if platform != config["platform"] or asset not in config["assets"] or kind not in FIELDS:
        raise AuthError("AUTH_SCOPE", "unknown platform, asset or kind")
    channels = CHANNELS.get(kind, {"none"})
    expected_source = config["custodian"] if channel == "external_custody" else config["platform"]
    if channel not in channels or source != expected_source:
        raise AuthError("AUTH_SCOPE", "source and kind-specific channel disagree")
    return dict(value)


def capability_inventory(values, config):
    if type(values) is not list or not 0 < len(values) <= 10000:
        raise AuthError("AUTH_SCOPE", "nonempty bounded capability inventory required")
    result = [capability(value, config) for value in values]
    keys = [canonical(value) for value in result]
    if len(set(keys)) != len(keys):
        raise AuthError("AUTH_SCOPE", "duplicate capability tuple")
    return sorted(result, key=canonical)


def capabilities(snapshot, config):
    result = {}
    for line in snapshot.lines:
        envelope = strict_json(line, limit=MAX_LINE_BYTES)
        if type(envelope) is not dict or set(envelope) != {"record", "received_at"}:
            raise AuthError("AUTH_SCOPE", "exact record and received_at envelope required")
        record = envelope["record"]
        if type(record) is not dict or not COMMON <= set(record) or any(type(record[k]) is not str for k in COMMON):
            raise AuthError("AUTH_SCOPE", "missing or ambiguous authority fields")
        kind = record["kind"]
        if kind not in FIELDS or not set(record) <= FIELDS[kind]:
            raise AuthError("AUTH_SCOPE", "unknown kind or forbidden record field")
        if kind == "correction":
            target = record.get("target")
            if (type(target) is not dict or set(target) != {"kind", "source", "platform", "business_day", "ref"}
                    or any(type(value) is not str for value in target.values()) or target["kind"] != "event"
                    or target["source"] != record["source"] or target["platform"] != record["platform"]):
                raise AuthError("AUTH_SCOPE", "correction target authority is inconsistent")
        cap = {key: record[key] for key in ("source", "platform", "asset", "kind")}
        cap["channel"] = record.get("stream") if kind in CHANNELS else "none"
        cap = capability(cap, config)
        result[canonical(cap)] = cap
    if len({value["source"] for value in result.values()}) != 1:
        raise AuthError("AUTH_SCOPE", "a protected file must have one publisher")
    return [result[key] for key in sorted(result)]


def statement(value, snapshot, config):
    fields = {"format", "source", "receiver", "configuration_digest", "stream_id", "plan", "capabilities"}
    if type(value) is not dict or set(value) != fields or value["format"] != "source-admission-statement-v1":
        raise AuthError("AUTH_STATEMENT", "exact source-admission-statement-v1 fields required")
    for key in ("source", "receiver", "stream_id"):
        identifier(value[key], key)
    if not hex_digest(value["configuration_digest"]):
        raise AuthError("AUTH_STATEMENT", "invalid configuration digest")
    try:
        validate_stream(value["stream_id"])
        validate_plan(value["plan"])
    except ValueError as exc:
        raise AuthError("AUTH_STATEMENT", "invalid stream or immutable plan") from exc
    if value["plan"] != snapshot.plan:
        raise AuthError("AUTH_SNAPSHOT", "signed plan differs from exact snapshot")
    declared = capability_inventory(value["capabilities"], config)
    actual = capabilities(snapshot, config)
    if declared != actual or any(cap["source"] != value["source"] for cap in actual):
        raise AuthError("AUTH_SCOPE", "declared capabilities differ from actual snapshot scope")
    return value, actual
