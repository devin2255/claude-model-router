"""Tests for configuration module."""
import unittest
from claude_model_router.config import deep_merge, normalize_value


class TestConfig(unittest.TestCase):
    def test_deep_merge(self):
        base = {"a": 1, "b": {"c": 2}}
        override = {"b": {"d": 3}}
        result = deep_merge(base, override)
        self.assertEqual(result["a"], 1)
        self.assertEqual(result["b"]["c"], 2)
        self.assertEqual(result["b"]["d"], 3)

    def test_normalize_value(self):
        self.assertEqual(normalize_value("test"), "test")
        self.assertEqual(normalize_value("  test  "), "test")
        self.assertEqual(normalize_value(None, "default"), "default")
        self.assertEqual(normalize_value("", "default"), "default")


if __name__ == "__main__":
    unittest.main()
