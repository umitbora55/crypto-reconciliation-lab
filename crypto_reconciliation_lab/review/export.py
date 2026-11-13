"""Deterministic self-contained offline exports, with no financial execution."""
import base64
import hashlib
from importlib import resources
import json
import os
from pathlib import Path

from .. import __version__
from . import BUNDLE_FORMAT
from .adapter import MAX_SELECTION_BYTES, SIDECARS, read_selection, read_selected_sources
from .publication import new_output_directory
from .validation import ReviewError
from .viewmodel import build_run_view

MAX_HTML_BYTES = 128 * 1024 * 1024
ASSET_NAMES = ("index.html", "style.css", "app.js")


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True,
                       allow_nan=False, indent=2) + "\n").encode("utf-8")


def escaped_json_chunks(value):
    """Escape the HTML parser boundary, not just JavaScript JSON syntax."""
    encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=True,
                               allow_nan=False, separators=(",", ":"))
    for chunk in encoder.iterencode(value):
        yield chunk.replace("&", "\\u0026").replace("<", "\\u003c").replace(
            ">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def hash_bytes(data):
    return hashlib.sha256(data).hexdigest()


def csp_hash(data):
    return "'sha256-" + base64.b64encode(hashlib.sha256(data).digest()).decode("ascii") + "'"


def load_assets():
    folder = resources.files("crypto_reconciliation_lab.review").joinpath("assets")
    return {name: folder.joinpath(name).read_bytes() for name in ASSET_NAMES}


def write_html(path, bundle, assets):
    """Bound and hash HTML while writing its hidden, unpublished staging file."""
    template = assets["index.html"].decode("utf-8")
    for token in ("@@STYLE@@", "@@SCRIPT@@", "@@DATA@@", "@@CSP@@"):
        if template.count(token) != 1:
            raise ValueError("ASSET_TEMPLATE_INVALID: each export token must occur exactly once")
    policy = "; ".join(("default-src 'none'", "script-src " + csp_hash(assets["app.js"]),
                        "style-src " + csp_hash(assets["style.css"]),
                        "connect-src 'none'", "img-src 'none'", "font-src 'none'",
                        "object-src 'none'", "base-uri 'none'", "form-action 'none'"))
    template = template.replace("@@STYLE@@", assets["style.css"].decode("utf-8"))
    template = template.replace("@@SCRIPT@@", assets["app.js"].decode("utf-8"))
    template = template.replace("@@CSP@@", policy)
    prefix, suffix = template.split("@@DATA@@")
    checksum = hashlib.sha256()
    count = 0
    with Path(path).open("xb") as output:
        def write(text):
            nonlocal count
            data = text.encode("utf-8")
            count += len(data)
            if count > MAX_HTML_BYTES:
                raise ValueError("HTML_LIMIT_EXCEEDED: maximum produced HTML is 128 MiB")
            checksum.update(data)
            output.write(data)
        write(prefix)
        for chunk in escaped_json_chunks(bundle):
            write(chunk)
        write(suffix)
    return {"bytes": count, "sha256": checksum.hexdigest()}


def export_selection(selection_path, output_path):
    """Read only explicitly selected persisted runs; publish three complete files.

    The adapter owns source validation and before/after read proofs. This layer
    does not construct a Store or call ingest, reconcile, migrate or save_run.
    """
    # Preserve existing-target precedence, including a dangling symlink.
    requested = Path(output_path).expanduser().absolute()
    if os.path.lexists(requested):
        raise FileExistsError("OUTPUT_EXISTS: choose a new output directory")
    selection = read_selection(selection_path)
    destination = requested.resolve()
    # Check every source before parent mkdir or staging can occupy a sidecar.
    for source in selection.sources:
        for suffix in ("", *SIDECARS):
            protected = Path(str(source.database) + suffix).resolve()
            if destination == protected or protected in destination.parents:
                raise ReviewError("OUTPUT_SOURCE_CONFLICT",
                                  "output must not occupy a selected database or SQLite sidecar path",
                                  alias=source.alias)
    # Use the canonical path: mkdir on an unresolved x/../y can create x first.
    with new_output_directory(destination) as staging:
        selected = read_selected_sources(selection)
        runs = [build_run_view(run) for run in selected.runs]
        sources = []
        for run in runs:
            source = next((item for item in sources if item["alias"] == run["source_alias"]), None)
            if source is None:
                source = {"alias": run["source_alias"], "label": run["source_label"],
                          "schema_version": run["schema_version"], "run_ids": []}
                sources.append(source)
            source["run_ids"].append(run["run_id"])
        bundle = {"format": BUNDLE_FORMAT, "exporter_version": __version__,
                  "sources": sources, "runs": runs}
        assets = load_assets()
        html_entry = write_html(staging / "index.html", bundle, assets)
        summary = {"format": BUNDLE_FORMAT, "exporter_version": __version__,
                   "status": "COMPLETE", "run_count": len(runs), "source_count": len(sources),
                   "sources": sources, "runs": [
                       {key: run[key] for key in ("source_alias", "run_id", "rule_version",
                            "balance_at", "knowledge_at", "payload_sha256")}
                       for run in runs],
                   "integrity_meaning": "Stored payload identity matches; not source authentication or a financial verdict."}
        encoded = json_bytes(summary)
        (staging / "summary.json").write_bytes(encoded)
        manifest = {"format": BUNDLE_FORMAT, "exporter_version": __version__, "status": "COMPLETE",
                    "files": {"index.html": html_entry,
                              "summary.json": {"bytes": len(encoded), "sha256": hash_bytes(encoded)}},
                    "assets": {name: {"bytes": len(data), "sha256": hash_bytes(data)}
                               for name, data in sorted(assets.items())},
                    "sources": selected.sources,
                    "limits": {"selection_bytes": MAX_SELECTION_BYTES,
                               "selected_runs": 100, "saved_payload_bytes": 64 * 1024 * 1024,
                               "html_bytes": MAX_HTML_BYTES},
                    "manifest_scope": "File hashes exclude this manifest to avoid self-reference.",
                    "snapshot_scope": "Each source is a separate read transaction; closed quiet rollback-journal snapshots only."}
        (staging / "manifest.json").write_bytes(json_bytes(manifest))
    return manifest
