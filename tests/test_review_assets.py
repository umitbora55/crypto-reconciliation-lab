"""Packaged offline UI resource and executable-surface regression checks.

These checks are not browser validation. The separate Playwright command records
real file:// rendering, interactions, network behavior and downloaded bytes.
"""
from html.parser import HTMLParser
from importlib.resources import files
import re
import unittest


class ResourceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class ReviewAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = files('crypto_reconciliation_lab.review').joinpath('assets')
        cls.html = folder.joinpath('index.html').read_text(encoding='utf-8')
        cls.css = folder.joinpath('style.css').read_text(encoding='utf-8')
        cls.script = folder.joinpath('app.js').read_text(encoding='utf-8')

    def test_packaged_template_has_exact_embedding_slots_and_no_remote_resources(self):
        for marker in ('@@STYLE@@', '@@SCRIPT@@', '@@DATA@@', '@@CSP@@'):
            self.assertEqual(self.html.count(marker), 1, marker)
        parser = ResourceParser()
        parser.feed(self.html)
        for tag, attrs in parser.tags:
            self.assertNotIn(tag, {'iframe', 'object', 'embed', 'img', 'link'})
            for key, value in attrs.items():
                self.assertFalse(key.lower().startswith('on'), (tag, key))
                if key in {'href', 'src', 'action', 'formaction'}:
                    self.assertTrue(value.startswith('#'), (tag, key, value))
        scripts = [attrs for tag, attrs in parser.tags if tag == 'script']
        self.assertEqual(len(scripts), 2)
        self.assertEqual(scripts[0].get('type'), 'application/json')
        self.assertTrue(all('src' not in attrs for attrs in scripts))

    def test_script_has_no_executable_data_or_network_api(self):
        forbidden = r'\b(?:innerHTML|outerHTML|insertAdjacentHTML|eval|Function|fetch|XMLHttpRequest|WebSocket|Worker|serviceWorker)\b'
        self.assertIsNone(re.search(forbidden, self.script))
        self.assertNotRegex(self.script, r'\b(?:setTimeout|setInterval)\s*\(\s*[\'\"]')
        self.assertNotRegex(self.script, r'\bimport\s*\(')

    def test_financial_text_is_not_coerced_or_rounded_in_browser(self):
        self.assertNotRegex(self.script, r'\b(?:Number|parseFloat|parseInt|BigInt)\s*\(')
        self.assertNotRegex(self.script, r'\.\s*(?:toFixed|toPrecision|toExponential)\s*\(')
        self.assertNotRegex(self.script, r'JSON\s*\.\s*stringify\s*\(')
        self.assertNotRegex(self.script, r'\bnew\s+Date\s*\(')

    def test_css_uses_local_system_fonts_and_no_external_loads(self):
        self.assertNotRegex(self.css, r'(?i)@import\b|@font-face\b|url\s*\(')
        self.assertNotRegex(self.css, r'https?://|//cdn\.')


if __name__ == '__main__':
    unittest.main()
