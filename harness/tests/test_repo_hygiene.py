"""Nothing identifying may be committed to this public repository.

The account id was scrubbed by hand once, and that hand scrub missed the three
organization identifiers sitting in the same line of health/health.jsonl,
because a hand scrub finds what you thought to look for. This finds what you
did not.

Pair this with harness/redact.py: that stops new records carrying identifiers,
and this stops anything else doing so.
"""

import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "cdk.out", ".cdk.staging",
             "node_modules", ".pytest_cache", ".mypy_cache"}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".ico"}

#: AWS's documentation placeholder, and the replacements redact.py writes.
ALLOWED = {"111122223333", "o-exampleorgid", "p-examplepolicyid",
           "AKIAIOSFODNN7EXAMPLE", "AIDAEXAMPLEPRINCIPALID"}

PATTERNS = {
    "AWS account id": re.compile(r"\b\d{12}\b"),
    "Organizations id": re.compile(r"\bo-[a-z0-9]{10,34}\b"),
    "access key id": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "IAM unique id": re.compile(r"\b(?:AIDA|AROA|AIPA|ANPA|AGPA)[A-Z0-9]{16,}\b"),
}


def text_files():
    """Every text file in the repo, pruning build and environment trees.

    os.walk with in-place pruning rather than rglob: rglob descends into
    .venv and cdk.out and filters afterwards, which took eight seconds.
    """
    for directory, subdirs, names in os.walk(ROOT):
        subdirs[:] = [d for d in subdirs if d not in SKIP_DIRS]
        for name in names:
            path = Path(directory) / name
            if path.suffix.lower() in SKIP_SUFFIXES:
                continue
            try:
                yield path, path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue


class TestNoIdentifiers(unittest.TestCase):
    def test_it_is_actually_reading_the_repo(self):
        # Guards the guard: an empty sweep passes every assertion below.
        names = {p.name for p, _ in text_files()}
        self.assertIn("README.md", names)
        self.assertIn("health.jsonl", names)

    def test_no_identifiers_outside_the_allowed_placeholders(self):
        found = []
        for path, text in text_files():
            for label, pattern in PATTERNS.items():
                for match in set(pattern.findall(text)) - ALLOWED:
                    found.append(
                        f"{path.relative_to(ROOT)}: {label} {match!r}")
        self.assertEqual(found, [], "identifiers in a public repository:\n  "
                                   + "\n  ".join(sorted(found)))


if __name__ == "__main__":
    unittest.main()
