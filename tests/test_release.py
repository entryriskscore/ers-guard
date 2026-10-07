"""Release hygiene: the things a publish depends on. No network."""
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding='utf-8') as f:
        return f.read()


class ReleaseTests(unittest.TestCase):
    def test_one_version_everywhere(self):
        pyproject = re.search(r'(?m)^version = "([^"]+)"', read('pyproject.toml')).group(1)
        package = re.search(r"(?m)^__version__ = '([^']+)'", read('src', 'ers_guard', '__init__.py')).group(1)
        changelog = re.search(r'(?m)^## (\S+)', read('CHANGELOG.md')).group(1)
        self.assertEqual(pyproject, package)
        self.assertEqual(pyproject, changelog)                       # the newest changelog entry is this version
        self.assertRegex(pyproject, r'^\d+\.\d+\.\d+$')

    def test_readme_has_no_relative_links(self):
        # PyPI shows the README as it is: a relative link or image would be broken there.
        text = read('README.md')
        targets = re.findall(r'\]\(([^)\s]+)\)', text) + re.findall(r'(?:src|href)="([^"]+)"', text)
        self.assertTrue(targets)
        for target in targets:
            self.assertTrue(target.startswith(('https://', '#')), target)
        self.assertIn('pip install ers-guard', text)

    def test_mcp_registry_entry(self):
        entry = json.loads(read('mcp', 'server.json'))
        # the only names this repository may publish under
        self.assertRegex(entry['name'], r'^io\.github\.entryriskscore/[a-zA-Z0-9._-]+$')
        self.assertTrue(1 <= len(entry['description']) <= 100)
        self.assertTrue(1 <= len(entry['title']) <= 100)
        self.assertRegex(entry['version'], r'^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$')
        self.assertTrue(entry['websiteUrl'].startswith('https://'))
        self.assertEqual(len(entry['remotes']), 1)
        remote = entry['remotes'][0]
        self.assertEqual(remote['type'], 'streamable-http')
        self.assertEqual(remote['url'], 'https://entryriskscore.com/api/v1/mcp')
        header = remote['headers'][0]
        self.assertEqual((header['name'], header['isRequired'], header['isSecret']), ('X-API-Key', True, True))
        self.assertNotIn('value', header)                           # a key is never written into the entry
        self.assertNotIn('packages', entry)                         # hosted only: there is nothing to install


if __name__ == '__main__':
    unittest.main()
