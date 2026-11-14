"""Offline view serialization boundaries; actual browser behavior is separately QA'd."""
from html.parser import HTMLParser
import json
import unittest

from crypto_reconciliation_lab.provenance.ui import render_page


class Elements(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.elements = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


class ProvenanceUiTests(unittest.TestCase):
    def test_hostile_strings_and_proto_keys_remain_json_data(self):
        run = {"__proto__": {"polluted": True}, "reason": '</script><img src=x onerror="window.BAD=1">',
               "unicode": "\u2028\u2029 Türkçe", "findings": []}
        generated = render_page(run, {"run_id": "r"}, {"tables": {}}, {})
        wrapper = generated["data.js"].decode("ascii")
        prefix, suffix = "window.PROVENANCE_DATA = JSON.parse(", ");\n"
        self.assertTrue(wrapper.startswith(prefix))
        self.assertTrue(wrapper.endswith(suffix))
        # Both decoding boundaries must be valid strict JSON, never executable
        # object-literal text. In particular __proto__ remains a normal own key.
        payload = json.loads(json.loads(wrapper[len(prefix):-len(suffix)]))
        self.assertEqual(payload["run"], run)
        self.assertEqual(set(payload), {"run", "report", "capture", "materials"})
        self.assertNotIn(run["reason"].encode(), generated["index.html"])

    def test_local_resources_and_csp_have_no_network_or_inline_script_requirement(self):
        generated = render_page({}, {}, {}, {})
        elements = Elements(generated["index.html"].decode()).elements
        scripts = [attrs for tag, attrs in elements if tag == "script"]
        self.assertEqual([r.get("src") for r in scripts], ["data.js", "app.js"])
        self.assertTrue(all("defer" in r for r in scripts))
        csp = next(attrs["content"] for tag, attrs in elements if tag == "meta" and attrs.get("http-equiv") == "Content-Security-Policy")
        self.assertIn("connect-src 'none'", csp)
        self.assertIn("script-src 'self'", csp)
        self.assertNotIn("unsafe-inline", csp)
        for _, attrs in elements:
            for key in ("href", "src"):
                self.assertFalse(attrs.get(key, "").startswith(("http:", "https:", "//")))

    def test_exported_view_does_not_claim_source_verification(self):
        generated = render_page({}, {"status": "VERIFIED_FOR_CAPTURE"}, {}, {})
        page = generated["index.html"].decode()
        self.assertIn("CREATED · source verification NOT_PERFORMED", page)
        self.assertIn("Run creation authorization cut:", page)
        self.assertIn("NOT_RECORDED", page)
        self.assertNotIn("VERIFIED_FOR_CAPTURE", page)
        self.assertEqual(set(generated), {"index.html", "app.js", "style.css", "data.js"})

    def test_data_member_only_inventories_raw_materials_and_fixed_assets_stay_fixed(self):
        inventory = {"materials/snapshots/" + "a" * 64 + ".jsonl": {"bytes": 2, "sha256": "b" * 64},
                     "index.html": {"bytes": 3, "sha256": "c" * 64}, "manifest.json": {"bytes": 5, "sha256": "d" * 64}}
        first = render_page({}, {}, {}, inventory)
        second = render_page({"findings": ["different"]}, {}, {}, {})
        payload = json.loads(json.loads(first["data.js"].decode()[len("window.PROVENANCE_DATA = JSON.parse("):-3]))
        self.assertEqual(set(payload["materials"]), {"materials/snapshots/" + "a" * 64 + ".jsonl"})
        for name in ("index.html", "app.js", "style.css"):
            self.assertEqual(first[name], second[name])


if __name__ == "__main__":
    unittest.main()
