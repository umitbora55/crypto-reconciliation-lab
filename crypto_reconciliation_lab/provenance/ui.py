"""Deterministic offline view; exporting a page never asserts verification."""
import json
from importlib.resources import files


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def render_page(run, report, capture, material_inventory):
    """Return fixed local assets and a safely parsed, immutable data member.

    The independent verifier checks these bytes without importing this renderer.
    Material identities cover only original materials, never this view or itself.
    """
    materials = {name: value for name, value in material_inventory.items()
                 if name.startswith("materials/")}
    payload = {"run": run, "capture": capture, "report": report, "materials": materials}
    encoded = _canonical(payload).decode("ascii")
    data = b"window.PROVENANCE_DATA = JSON.parse(" + _canonical(encoded) + b");\n"
    resources = files("crypto_reconciliation_lab.provenance").joinpath("assets")
    result = {name: resources.joinpath(name).read_bytes()
              for name in ("index.html", "app.js", "style.css")}
    result["data.js"] = data
    return result
