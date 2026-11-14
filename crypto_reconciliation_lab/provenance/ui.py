"""Deterministic offline view; exporting a page never asserts verification."""
import json
from importlib.resources import files


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _display_capture(capture):
    """Derive lossless SQL identity labels before any JavaScript JSON parse.

    Authoritative capture bytes and numeric SQL types remain unchanged. All
    physical PK/FK columns, including bounded sequence/epoch relations, use
    decimal strings consistently in this derived display projection only.
    """
    identities = {
        "receipts": {"id"}, "delivery_effects": {"sequence", "core_receipt_id"},
        "delivery_attempts": {"id", "sequence", "effect_sequence"}, "auth_configuration": {"id"},
        "auth_policy_activations": {"epoch", "previous_epoch"}, "auth_keys": {"first_epoch"},
        "auth_decisions": {"id", "epoch", "sequence"},
        "auth_delivery_links": {"sequence", "decision_id", "core_receipt_id"},
        "auth_attempt_links": {"attempt_id", "decision_id"},
    }
    result = dict(capture)
    if "tables" in capture:
        result["tables"] = {
            table: [{key: str(value) if key in identities.get(table, ()) and type(value) is int else value
                     for key, value in row.items()} for row in rows]
            for table, rows in capture["tables"].items()
        }
    return result


def render_page(run, report, capture, material_inventory):
    """Return fixed local assets and a safely parsed, immutable data member.

    The independent verifier checks these bytes without importing this renderer.
    Material identities cover only original materials, never this view or itself.
    """
    materials = {name: value for name, value in material_inventory.items()
                 if name.startswith("materials/")}
    payload = {"run": run, "capture": _display_capture(capture), "report": report, "materials": materials}
    encoded = _canonical(payload).decode("ascii")
    data = b"window.PROVENANCE_DATA = JSON.parse(" + _canonical(encoded) + b");\n"
    resources = files("crypto_reconciliation_lab.provenance").joinpath("assets")
    result = {name: resources.joinpath(name).read_bytes()
              for name in ("index.html", "app.js", "style.css")}
    result["data.js"] = data
    return result
