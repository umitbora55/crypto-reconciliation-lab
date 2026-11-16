#!/usr/bin/env python3
"""Deterministic NO_NETWORK import of manually downloaded official-file bytes.

Integrity checks establish correspondence to the supplied manifest, not that the
operator's claimed URL/download time is independently authenticated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from validation_lab.gate2_public_data import sec_zip_text
from validation_lab.public_data import fiscal_api_rows

MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 500 * 1024 * 1024
HOSTS = {"api.fiscaldata.treasury.gov", "fiscaldata.treasury.gov", "www.sec.gov", "www.bis.org"}
FILE_FIELDS = {"source_id", "file_name", "source_url", "downloaded_at_utc", "publication_vintage", "kind", "sha256", "bytes", "usage_terms"}


def strict_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("DUPLICATE_MANIFEST_KEY")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def import_files(manifest_path, input_root, output):
    manifest_path, input_root, output = Path(manifest_path), Path(input_root).resolve(), Path(output)
    if manifest_path.stat().st_size > 1024 * 1024:
        raise ValueError("MANIFEST_SIZE_LIMIT")
    raw_manifest = manifest_path.read_bytes()
    manifest = strict_json(raw_manifest)
    if set(manifest) != {"format", "capture_method", "files"} or manifest["format"] != "official-file-import-v1" or manifest["capture_method"] != "USER_DOWNLOADED_OFFICIAL_BYTES":
        raise ValueError("MANIFEST_SCHEMA")
    files = manifest["files"]
    if not isinstance(files, list) or not 1 <= len(files) <= 20:
        raise ValueError("NONEMPTY_BOUNDED_INVENTORY_REQUIRED")
    seen_ids, seen_names, retained, total = set(), set(), [], 0
    for row in files:
        if not isinstance(row, dict) or set(row) != FILE_FIELDS:
            raise ValueError("FILE_ENTRY_SCHEMA")
        source_id, name = row["source_id"], row["file_name"]
        if not isinstance(source_id, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", source_id) or source_id in seen_ids:
            raise ValueError("SOURCE_ID_DOMAIN_OR_DUPLICATE")
        if not isinstance(name, str) or Path(name).name != name or name in ("", ".", "..") or "\\" in name or name in seen_names:
            raise ValueError("SOURCE_PATH_DOMAIN_OR_DUPLICATE")
        seen_ids.add(source_id); seen_names.add(name)
        path = input_root / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(input_root):
            raise ValueError("SOURCE_NOT_REGULAR_CONTAINED_FILE")
        parsed = urlparse(row["source_url"])
        if parsed.scheme != "https" or parsed.hostname not in HOSTS or parsed.username or parsed.password or parsed.fragment or parsed.port not in (None, 443):
            raise ValueError("SOURCE_URL_DOMAIN")
        downloaded = datetime.fromisoformat(row["downloaded_at_utc"].replace("Z", "+00:00"))
        if downloaded.utcoffset() != timedelta(0):
            raise ValueError("UTC_DOWNLOAD_TIMESTAMP_REQUIRED")
        if not isinstance(row["publication_vintage"], str) or not row["publication_vintage"] or not isinstance(row["usage_terms"], str) or not row["usage_terms"]:
            raise ValueError("VINTAGE_AND_TERMS_REQUIRED_USE_UNKNOWN_IF_UNVERIFIED")
        if type(row["bytes"]) is not int or not 0 < row["bytes"] <= MAX_FILE_BYTES or path.stat().st_size != row["bytes"]:
            raise ValueError("SOURCE_SIZE")
        if not isinstance(row["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
            raise ValueError("SOURCE_SHA256_DOMAIN")
        body = path.read_bytes()
        if len(body) != row["bytes"] or hashlib.sha256(body).hexdigest() != row["sha256"]:
            raise ValueError("SOURCE_INTEGRITY")
        total += len(body)
        if total > MAX_TOTAL_BYTES:
            raise ValueError("TOTAL_SOURCE_SIZE")
        if row["kind"] == "treasury_api_json":
            rows = fiscal_api_rows(body.decode("utf-8"))
            structural = {"rows": len(rows), "status": "PAGINATION_STRUCTURE_ONLY"}
        elif row["kind"] == "sec_ftd_zip":
            _, member = sec_zip_text(body)
            structural = {"member": member, "status": "ZIP_TRAILERS_ONLY"}
        elif row["kind"] == "official_document":
            structural = {"status": "BYTES_ONLY_NOT_CONTENT_AUTHENTICATION"}
        else:
            raise ValueError("UNSUPPORTED_KIND")
        retained.append((row, body, structural))
    output.mkdir(parents=True, exist_ok=False)
    (output / "raw").mkdir()
    with (output / "supplied-manifest.json").open("xb") as stream:
        stream.write(raw_manifest)
    results = []
    for row, body, structural in retained:
        name = row["source_id"] + "-" + row["file_name"]
        with (output / "raw" / name).open("xb") as stream:
            stream.write(body)
        results.append({**row, "retained_path": "raw/" + name, "structural_check": structural})
    result = {"format": "official-file-import-result-v1", "status": "INTEGRITY_VERIFIED_ORIGIN_USER_ATTESTED",
              "network_requests": 0, "capture_method": manifest["capture_method"], "manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(),
              "files": results, "bytes": total, "real_financial_equalities_verified": 0,
              "independent_origin_authentication": "NOT_ESTABLISHED", "institutional_trust": "NOT_ESTABLISHED"}
    with (output / "import-result.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = import_files(args.manifest, args.input_root, args.output)
    print(json.dumps({"status": result["status"], "files": len(result["files"]), "bytes": result["bytes"], "network_requests": 0}))


if __name__ == "__main__":
    main()
