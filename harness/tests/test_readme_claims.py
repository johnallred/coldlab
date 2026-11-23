"""The README's countable claims, enforced.

Ported from the fieldguide, for the same reason: a number in a README rots the
moment someone adds a test, and a rotted number is worse than no number
because it teaches a reader not to trust the rest of the file.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def count_tests() -> int:
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=str(ROOT / "harness" / "tests"),
                            top_level_dir=str(ROOT))

    def walk(item):
        if isinstance(item, unittest.TestSuite):
            for child in item:
                yield from walk(child)
        else:
            yield item

    return sum(1 for _ in walk(suite))


class TestReadmeClaims(unittest.TestCase):
    def setUp(self):
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")

    def test_discovery_actually_found_the_tests(self):
        # Guards the guard: a broken import would make the count 0 and the
        # claim trivially satisfiable.
        self.assertGreater(count_tests(), 40)

    def test_test_count_matches(self):
        claimed = re.findall(r"(\d+)\s+tests", self.readme)
        self.assertTrue(claimed, "README states no test count")
        actual = count_tests()
        for number in claimed:
            self.assertEqual(
                int(number), actual,
                f"README says {number} tests, discovery finds {actual}",
            )

    def test_readme_does_not_claim_the_harness_is_unwritten(self):
        self.assertNotIn("What does not exist yet\n\nThe harness", self.readme)


if __name__ == "__main__":
    unittest.main()
