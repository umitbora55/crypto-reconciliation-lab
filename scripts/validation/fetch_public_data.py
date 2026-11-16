#!/usr/bin/env python3
"""Bounded, opt-in acquisition of official public research inputs.

Never used by tests. Raw bytes and request evidence remain outside Git. No
credentials, impersonation, TLS bypass, retries, or unbounded pagination.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

PERIODS = (("2019-01", "2019-01-01", "2019-01-31"),
           ("2022-04", "2022-04-01", "2022-04-30"),
           ("2024-01", "2024-01-01", "2024-01-31"),
           ("2025-01", "2025-01-01", "2025-01-31"),
           ("2026-11", "2026-11-01", "2026-11-12"))
MAX_BODY = 32 * 1024 * 1024
MAX_TOTAL = 512 * 1024 * 1024
ALLOWED_HOSTS = {"fiscaldata.treasury.gov", "api.fiscaldata.treasury.gov", "www.sec.gov", "www.bis.org"}
USER_AGENT = "crypto-reconciliation-lab-public-validation/1.0 (https://github.com/umitbora55/crypto-reconciliation-lab)"


def plan():
    requests = [
        {"id": "treasury-dts-documentation", "kind": "documentation", "url": "https://fiscaldata.treasury.gov/datasets/daily-treasury-statement/operating-cash-balance"},
        {"id": "treasury-api-documentation", "kind": "documentation", "url": "https://fiscaldata.treasury.gov/api-documentation/"},
        {"id": "treasury-about", "kind": "usage-policy", "url": "https://fiscaldata.treasury.gov/about-us/"},
        {"id": "sec-ftd-documentation", "kind": "documentation", "url": "https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data"},
        {"id": "sec-website-policy", "kind": "usage-policy", "url": "https://www.sec.gov/about/website-policies"},
        {"id": "bis-pfmi", "kind": "documentation", "url": "https://www.bis.org/committees/cpmi/pfmi/overview"},
        {"id": "bis-bcbs239-2026", "kind": "documentation", "url": "https://www.bis.org/publications/implementation-principles-effective-risk-data-aggregation-and-risk-reporting-bcbs-239-principles"},
    ]
    for label, start, end in PERIODS:
        for table in ("operating_cash_balance", "deposits_withdrawals_operating_cash"):
            query = urllib.parse.urlencode({"filter": f"record_date:gte:{start},record_date:lte:{end}",
                                           "page[size]": "10000", "page[number]": "1", "sort": "record_date"})
            requests.append({"id": f"dts-{table}-{label}", "kind": "data", "table": table,
                             "period": [start, end], "unit": "million USD as published; do not scale into exact cents",
                             "url": "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/" + table + "?" + query})
    for half in ("202401a", "202501a"):
        requests.append({"id": "sec-ftd-" + half, "kind": "data", "table": "fails-to-deliver",
                         "period": half, "unit": "aggregate outstanding fail balance; quantity of shares",
                         "url": "https://www.sec.gov/files/data/fails-deliver-data/cnsfails" + half + ".zip"})
    return requests


class RestrictedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlparse(newurl)
        if target.scheme != "https" or target.hostname not in ALLOWED_HOSTS or target.username or target.password:
            raise ValueError("redirect outside explicit official host allowlist")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sec_link_evidence(path, expected_sha256, requests):
    if not path or not expected_sha256:
        raise ValueError("SEC_LINK: supply retained official landing bytes and their recorded SHA256 before downloading a ZIP")
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BODY or sha256(path) != expected_sha256:
        raise ValueError("SEC_LINK: landing evidence integrity failed")
    class LinkParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.links = set()
        def handle_starttag(self, tag, attrs):
            if tag == "a" and dict(attrs).get("href"):
                self.links.add(urllib.parse.urljoin("https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data", dict(attrs)["href"]))
    parser = LinkParser()
    parser.feed(path.read_text(encoding="utf-8"))
    if any(row["url"] not in parser.links for row in requests if row.get("table") == "fails-to-deliver"):
        raise ValueError("SEC_LINK: requested ZIP is absent from retained official landing hyperlinks")
    return {"path": str(path.resolve()), "sha256": expected_sha256, "bytes": path.stat().st_size,
            "landing_url": "https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data",
            "claim": "Links in hash-bound caller-supplied landing bytes; original capture provenance must be independently retained."}


def fetch(output, timeout=12, selected_ids=None, sec_landing_file=None, sec_landing_sha256=None):
    if os.environ.get("NO_NETWORK", "").strip().lower() in {"1", "true", "yes"}:
        raise ValueError("NO_NETWORK: direct fetch is disabled")
    output = Path(output).resolve()
    requests = [r for r in plan() if selected_ids is None or r["id"] in selected_ids]
    if not requests or (selected_ids is not None and {r["id"] for r in requests} != set(selected_ids)):
        raise ValueError("select only catalogued official request IDs")
    link_evidence = None
    if any(row.get("table") == "fails-to-deliver" for row in requests):
        link_evidence = sec_link_evidence(sec_landing_file, sec_landing_sha256, requests)
    output.mkdir(parents=True, exist_ok=False)
    (output / "raw").mkdir()
    protocol = {"format": "public-fetch-protocol-v1", "periods": PERIODS, "requests": requests,
                "max_response_bytes": MAX_BODY, "max_total_bytes": MAX_TOTAL, "timeout_seconds": timeout,
                "retries": 0, "pagination": "one explicit page of 10000 rows; total-pages checked before acceptance",
                "freeze_time_utc": datetime.now(timezone.utc).isoformat()}
    if link_evidence is not None:
        protocol["sec_link_evidence"] = link_evidence
    (output / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n")
    opener = urllib.request.build_opener(RestrictedRedirect())
    sources, total = [], 0
    for item in protocol["requests"]:
        result = dict(item, retrieved_at_utc=datetime.now(timezone.utc).isoformat(),
                      status="DATA_UNAVAILABLE", data_class="NOT_OBSERVED", license="NOT_VERIFIED",
                      redistribution="raw data excluded from Git; permission not inferred from public accessibility")
        start = time.monotonic()
        body = b""
        try:
            if total >= MAX_TOTAL:
                raise ValueError("TOTAL_DOWNLOAD_BUDGET_EXHAUSTED")
            req = urllib.request.Request(item["url"], headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
            with opener.open(req, timeout=timeout) as response:
                result["http_status"] = response.status
                result["content_type"] = response.headers.get("Content-Type")
                result["final_url"] = response.url
                body = response.read(min(MAX_BODY, MAX_TOTAL - total) + 1)
                if len(body) > MAX_BODY or total + len(body) > MAX_TOTAL:
                    body = b""
                    raise ValueError("DOWNLOAD_BUDGET_EXCEEDED")
            result.update(status="DOWNLOADED", data_class="REAL_PUBLIC" if item["kind"] == "data" else "SOURCE_DOCUMENTATION")
        except urllib.error.HTTPError as error:
            result.update(http_status=error.code, error_type=type(error).__name__, error=str(error))
            body = error.read(min(64 * 1024, max(0, MAX_TOTAL - total)))
        except (OSError, ValueError, urllib.error.URLError) as error:
            result.update(error_type=type(error).__name__, error=str(error))
        total += len(body)
        if body:
            name = "raw/" + item["id"] + ".body"
            (output / name).write_bytes(body)
            result.update(path=name, sha256=hashlib.sha256(body).hexdigest(), bytes=len(body))
        result["elapsed_seconds"] = round(time.monotonic() - start, 6)
        sources.append(result)
        print(json.dumps({key: result.get(key) for key in ("id", "status", "http_status", "bytes", "error")} ), flush=True)
    register = {"format": "public-source-register-v1", "protocol_sha256": sha256(output / "protocol.json"),
                "raw_evidence_root": str(output), "sources": sources, "downloaded_bytes": total,
                "institutional_ground_truth": "NO_PUBLIC_TRANSACTION_GROUND_TRUTH",
                "real_financial_equality": "NOT_YET_VALIDATED"}
    (output / "source-register.json").write_text(json.dumps(register, indent=2) + "\n")
    return register


def expected_requests(selected_ids=None):
    """Expected membership comes from code/caller, never the inspected evidence."""
    catalog = {row["id"]: row for row in plan()}
    if selected_ids is None:
        selected_ids = list(catalog)
    if not selected_ids or len(set(selected_ids)) != len(selected_ids) or any(key not in catalog for key in selected_ids):
        raise ValueError("EXPECTED_SCOPE: nonempty unique catalogued IDs required")
    return {key: catalog[key] for key in selected_ids}


def checked_inventory(rows, expected, label):
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError(label + ": nonempty object inventory required")
    identifiers = [row.get("id") for row in rows]
    if any(not isinstance(key, str) for key in identifiers) or len(set(identifiers)) != len(identifiers) or set(identifiers) != set(expected):
        raise ValueError(label + ": expected, unique and observed request IDs differ")
    for row in rows:
        if any(row.get(key) != value for key, value in expected[row["id"]].items()):
            raise ValueError(label + ": request identity differs from predeclared catalog")


def verify_offline(root, selected_ids=None, *, emit=True):
    root = Path(root).resolve()
    register = json.loads((root / "source-register.json").read_text())
    expected = expected_requests(selected_ids)
    if sha256(root / "protocol.json") != register.get("protocol_sha256"):
        raise ValueError("PROTOCOL_INTEGRITY: recorded protocol hash differs")
    protocol = json.loads((root / "protocol.json").read_text())
    checked_inventory(protocol.get("requests"), expected, "PROTOCOL_SCOPE")
    checked_inventory(register.get("sources"), expected, "SOURCE_SCOPE")
    for source in register["sources"]:
        if source.get("status") not in {"DOWNLOADED", "DATA_UNAVAILABLE"}:
            raise ValueError("SOURCE_STATUS: unknown acquisition outcome")
        if source["status"] == "DOWNLOADED" and "path" not in source:
            raise ValueError("SOURCE_INTEGRITY: downloaded result has no retained bytes")
        if "path" in source:
            path = (root / source["path"]).resolve()
            if not path.is_relative_to(root):
                raise ValueError("source evidence escapes root")
            if type(source.get("bytes")) is not int or source["bytes"] <= 0 or path.stat().st_size != source["bytes"] or sha256(path) != source.get("sha256"):
                raise ValueError("source hash/size mismatch: " + source["id"])
    if emit:
        print(json.dumps({"status": "PASS", "mode": "NO_NETWORK", "scope": "ACQUISITION_EVIDENCE_INTEGRITY_ONLY", "sources": len(register["sources"]), "real_financial_equalities_verified": 0}))
    return register


def selected_scope(scope, only=None):
    if only:
        if scope != "all":
            raise ValueError("use --only or --scope, not both")
        return only
    if scope == "financial":
        return [row["id"] for row in plan() if not row["id"].startswith("bis-")]
    if scope == "references":
        return [row["id"] for row in plan() if row["id"].startswith("bis-")]
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true", help="explicitly opt in to official public HTTPS requests")
    parser.add_argument("--no-network", action="store_true", help="verify existing local request evidence only")
    parser.add_argument("--only", action="append", help="fetch only named catalogued requests; may repeat")
    parser.add_argument("--scope", choices=("all", "financial", "references"), default="all", help="externally selected expected request inventory; financial is the original 17 Treasury/SEC requests")
    parser.add_argument("--sec-landing-file", type=Path, help="retained official SEC landing page containing selected ZIP hyperlinks")
    parser.add_argument("--sec-landing-sha256", help="SHA256 from the separately retained landing-page acquisition record")
    args = parser.parse_args()
    if args.fetch == args.no_network:
        parser.error("select exactly one of --fetch or --no-network")
    if args.fetch:
        fetch(args.output, selected_ids=selected_scope(args.scope, args.only), sec_landing_file=args.sec_landing_file, sec_landing_sha256=args.sec_landing_sha256)
    else:
        verify_offline(args.output, selected_ids=selected_scope(args.scope, args.only))


if __name__ == "__main__":
    main()
