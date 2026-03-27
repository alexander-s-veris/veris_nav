import unittest
from unittest.mock import patch
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pricing
import protocol_queries as pq


class PricingDefensiveTests(unittest.TestCase):
    def setUp(self):
        pricing._price_cache.clear()

    def test_get_price_handles_missing_fields(self):
        result = pricing.get_price({})
        self.assertEqual(result["price_source"], "unavailable")
        self.assertEqual(str(result["price_usd"]), "0")
        self.assertIn("UNKNOWN", result["notes"])


class StrictConfigValidationTests(unittest.TestCase):
    def _bad_contracts(self):
        return {
            "ethereum": {
                "_vaults": {
                    "_query_type": "erc4626",
                    "broken_vault": {"abi": "erc4626"},
                }
            }
        }

    def test_validate_config_warns_when_not_strict(self):
        pq.set_config_validation(False)
        with patch("protocol_queries._load_contracts_cfg", return_value=self._bad_contracts()), \
             patch("protocol_queries._load_morpho_cfg", return_value={}), \
             patch("protocol_queries._load_solana_cfg", return_value={}), \
             patch("builtins.print") as mock_print:
            pq._validate_config()

        warning_lines = [args[0] for args, _ in mock_print.call_args_list if args]
        self.assertTrue(any("WARNING: Config validation found" in line for line in warning_lines))

    def test_validate_config_raises_when_strict(self):
        pq.set_config_validation(True)
        with patch("protocol_queries._load_contracts_cfg", return_value=self._bad_contracts()), \
             patch("protocol_queries._load_morpho_cfg", return_value={}), \
             patch("protocol_queries._load_solana_cfg", return_value={}):
            with self.assertRaises(ValueError) as ctx:
                pq._validate_config()

        self.assertIn("has 'abi' but no 'address'", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
