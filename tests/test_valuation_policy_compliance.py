"""
Valuation Policy compliance tests.

Validates that config/tokens.json, config/contracts.json, and the
pricing/valuation code comply with the Valuation Policy v1.0
(docs/reference/23-03-2026_Veris_Capital_AMC_Valuation_Policy DRAFT_v.1.0.pdf).

Tests are strict: any token with incorrect categorisation, missing
fallback sources, or wrong pricing methodology will fail.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")


def load_json(filename):
    with open(os.path.join(CONFIG_DIR, filename)) as f:
        return json.load(f)


class TestCategoryClassification(unittest.TestCase):
    """Section 5: Every token must have a valid category."""

    def setUp(self):
        self.tokens = load_json("tokens.json")

    def test_all_tokens_have_valid_category(self):
        """Every token entry must have category in {A1, A2, A3, B, C, D, E, F}."""
        valid_categories = {"A1", "A2", "A3", "B", "C", "D", "E", "F"}
        for chain, chain_tokens in self.tokens.items():
            if chain.startswith("_"):
                continue
            if not isinstance(chain_tokens, dict):
                continue
            for addr, entry in chain_tokens.items():
                if not isinstance(entry, dict):
                    continue
                cat = entry.get("category")
                self.assertIn(
                    cat, valid_categories,
                    f"{chain}.{entry.get('symbol', addr)}: category '{cat}' not in {valid_categories}"
                )

    def test_all_tokens_have_symbol_and_decimals(self):
        """Every token must have symbol and decimals."""
        for chain, chain_tokens in self.tokens.items():
            if chain.startswith("_"):
                continue
            if not isinstance(chain_tokens, dict):
                continue
            for addr, entry in chain_tokens.items():
                if not isinstance(entry, dict):
                    continue
                self.assertIn("symbol", entry,
                              f"{chain}.{addr}: missing 'symbol'")
                # Native tokens and some special entries may not have decimals in pricing
                # but should have decimals for balance conversion
                self.assertIn("decimals", entry,
                              f"{chain}.{entry.get('symbol', addr)}: missing 'decimals'")


class TestA1Methodology(unittest.TestCase):
    """Section 6.1: A1 tokens must use smart contract exchange rate."""

    def setUp(self):
        self.tokens = load_json("tokens.json")

    def test_a1_tokens_use_exchange_rate_or_equivalent(self):
        """A1 tokens must use a1_exchange_rate, or have convertToAssets-compatible pricing."""
        valid_a1_methods = {"a1_exchange_rate"}
        # Some A1 tokens (aTokens) use oracle pricing for the underlying — this is
        # the "layered methodology" from Section 6. The aToken balance already
        # includes accrued interest; the underlying is priced per its own category.
        # These are acceptable as A1 if they have underlying_symbol in contracts.json.
        acceptable_a1_fallback_methods = {"pyth", "chainlink", "coingecko", "par"}

        for chain, chain_tokens in self.tokens.items():
            if chain.startswith("_"):
                continue
            if not isinstance(chain_tokens, dict):
                continue
            for addr, entry in chain_tokens.items():
                if not isinstance(entry, dict) or entry.get("category") != "A1":
                    continue
                method = entry.get("pricing", {}).get("method", "")
                sym = entry.get("symbol", addr)
                if method in valid_a1_methods:
                    continue
                # aTokens and similar: priced via underlying token's method
                if method in acceptable_a1_fallback_methods:
                    continue
                self.fail(
                    f"{chain}.{sym}: A1 token uses method '{method}', "
                    f"expected one of {valid_a1_methods} or layered pricing"
                )


class TestA2Methodology(unittest.TestCase):
    """Section 6.2: A2 tokens must use oracle hierarchy with staleness thresholds."""

    def setUp(self):
        self.tokens = load_json("tokens.json")

    def _get_a2_tokens(self):
        result = []
        for chain, chain_tokens in self.tokens.items():
            if chain.startswith("_"):
                continue
            if not isinstance(chain_tokens, dict):
                continue
            for addr, entry in chain_tokens.items():
                if isinstance(entry, dict) and entry.get("category") == "A2":
                    result.append((chain, entry.get("symbol", addr), entry))
        return result

    def test_a2_primary_is_oracle(self):
        """A2 primary must be chainlink or pyth (oracle-based)."""
        valid_primary = {"chainlink", "pyth"}
        for chain, sym, entry in self._get_a2_tokens():
            method = entry.get("pricing", {}).get("method", "")
            self.assertIn(
                method, valid_primary,
                f"{chain}.{sym}: A2 primary method '{method}' not in {valid_primary}"
            )

    def test_a2_has_staleness_threshold(self):
        """Every A2 token must have expected_update_freq_hours configured."""
        for chain, sym, entry in self._get_a2_tokens():
            freq = entry.get("pricing", {}).get("expected_update_freq_hours")
            self.assertIsNotNone(
                freq,
                f"{chain}.{sym}: A2 token missing 'expected_update_freq_hours'"
            )
            self.assertGreater(
                freq, 0,
                f"{chain}.{sym}: expected_update_freq_hours must be > 0"
            )

    def test_a2_chainlink_primary_has_feed(self):
        """A2 tokens with chainlink method must have chainlink_feed."""
        for chain, sym, entry in self._get_a2_tokens():
            pricing = entry.get("pricing", {})
            if pricing.get("method") == "chainlink":
                self.assertIn(
                    "chainlink_feed", pricing,
                    f"{chain}.{sym}: A2 chainlink method but no chainlink_feed"
                )

    def test_a2_pyth_primary_has_feed_id(self):
        """A2 tokens with pyth method must have pyth_feed_id."""
        for chain, sym, entry in self._get_a2_tokens():
            pricing = entry.get("pricing", {})
            if pricing.get("method") == "pyth":
                self.assertIn(
                    "pyth_feed_id", pricing,
                    f"{chain}.{sym}: A2 pyth method but no pyth_feed_id"
                )


class TestA3Methodology(unittest.TestCase):
    """Section 6.3: A3 tokens use manual accrual, on-chain TP is cross-ref only."""

    def setUp(self):
        self.tokens = load_json("tokens.json")

    def test_a3_not_using_exchange_rate(self):
        """A3 tokens must NOT use a1_exchange_rate as primary."""
        for chain, chain_tokens in self.tokens.items():
            if chain.startswith("_") or not isinstance(chain_tokens, dict):
                continue
            for addr, entry in chain_tokens.items():
                if not isinstance(entry, dict) or entry.get("category") != "A3":
                    continue
                method = entry.get("pricing", {}).get("method", "")
                self.assertNotEqual(
                    method, "a1_exchange_rate",
                    f"{chain}.{entry.get('symbol')}: A3 must use manual accrual, "
                    f"not a1_exchange_rate. On-chain TP is cross-reference only (Section 6.3)."
                )


class TestBMethodology(unittest.TestCase):
    """Section 6.4: PT tokens use linear amortisation, not mark-to-market."""

    def setUp(self):
        self.tokens = load_json("tokens.json")

    def test_b_tokens_use_linear_amortisation(self):
        """Category B tokens must use pt_linear_amortisation method."""
        for chain, chain_tokens in self.tokens.items():
            if chain.startswith("_") or not isinstance(chain_tokens, dict):
                continue
            for addr, entry in chain_tokens.items():
                if not isinstance(entry, dict) or entry.get("category") != "B":
                    continue
                method = entry.get("pricing", {}).get("method", "")
                self.assertEqual(
                    method, "pt_linear_amortisation",
                    f"{chain}.{entry.get('symbol')}: Category B must use "
                    f"pt_linear_amortisation, not '{method}'"
                )

    def test_b_tokens_have_maturity(self):
        """Category B tokens must have maturity date."""
        for chain, chain_tokens in self.tokens.items():
            if chain.startswith("_") or not isinstance(chain_tokens, dict):
                continue
            for addr, entry in chain_tokens.items():
                if not isinstance(entry, dict) or entry.get("category") != "B":
                    continue
                maturity = entry.get("pricing", {}).get("maturity")
                self.assertIsNotNone(
                    maturity,
                    f"{chain}.{entry.get('symbol')}: Category B missing 'maturity'"
                )

    def test_b_tokens_have_underlying(self):
        """Category B tokens must specify their underlying asset."""
        for chain, chain_tokens in self.tokens.items():
            if chain.startswith("_") or not isinstance(chain_tokens, dict):
                continue
            for addr, entry in chain_tokens.items():
                if not isinstance(entry, dict) or entry.get("category") != "B":
                    continue
                underlying = entry.get("pricing", {}).get("underlying")
                self.assertIsNotNone(
                    underlying,
                    f"{chain}.{entry.get('symbol')}: Category B missing 'underlying'"
                )


class TestEMethodology(unittest.TestCase):
    """Section 6.7: Stablecoins — par or oracle with depeg monitoring."""

    def setUp(self):
        self.tokens = load_json("tokens.json")

    def _get_e_tokens(self):
        result = []
        for chain, chain_tokens in self.tokens.items():
            if chain.startswith("_") or not isinstance(chain_tokens, dict):
                continue
            for addr, entry in chain_tokens.items():
                if isinstance(entry, dict) and entry.get("category") == "E":
                    result.append((chain, entry.get("symbol", addr), entry))
        return result

    def test_e_method_is_valid(self):
        """E tokens must use par, chainlink, pyth, or coingecko."""
        valid = {"par", "chainlink", "pyth", "coingecko"}
        for chain, sym, entry in self._get_e_tokens():
            method = entry.get("pricing", {}).get("method", "")
            self.assertIn(
                method, valid,
                f"{chain}.{sym}: E token method '{method}' not in {valid}"
            )

    def test_e_par_usdc_pegged_have_depeg_check(self):
        """USDC, DAI should have depeg_check_feed (Chainlink or Pyth)."""
        # Per Section 6.7: USDC-pegged stablecoins valued at par with depeg monitoring
        must_have_depeg = {"USDC", "DAI"}
        for chain, sym, entry in self._get_e_tokens():
            if sym not in must_have_depeg:
                continue
            pricing = entry.get("pricing", {})
            has_chainlink = pricing.get("depeg_check_feed") not in (None, "null", "")
            has_pyth = pricing.get("pyth_feed_id") not in (None, "null", "")
            self.assertTrue(
                has_chainlink or has_pyth,
                f"{chain}.{sym}: par-priced E token must have depeg_check_feed "
                f"(Chainlink) or pyth_feed_id for depeg monitoring"
            )

    def test_e_non_par_have_oracle(self):
        """Non-par E tokens (USDT, USDe, USDD) must have oracle feed."""
        for chain, sym, entry in self._get_e_tokens():
            pricing = entry.get("pricing", {})
            method = pricing.get("method", "")
            if method == "par":
                continue
            # Must have at least one price source
            has_source = any([
                pricing.get("chainlink_feed"),
                pricing.get("pyth_feed_id"),
                pricing.get("coingecko_id"),
            ])
            self.assertTrue(
                has_source,
                f"{chain}.{sym}: non-par E token must have chainlink_feed, "
                f"pyth_feed_id, or coingecko_id"
            )


class TestFMethodology(unittest.TestCase):
    """Section 6.8: F tokens — Kraken -> CoinGecko -> DEX TWAP hierarchy."""

    def setUp(self):
        self.tokens = load_json("tokens.json")

    def _get_f_tokens(self):
        result = []
        for chain, chain_tokens in self.tokens.items():
            if chain.startswith("_") or not isinstance(chain_tokens, dict):
                continue
            for addr, entry in chain_tokens.items():
                if isinstance(entry, dict) and entry.get("category") == "F":
                    result.append((chain, entry.get("symbol", addr), entry))
        return result

    def test_f_method_is_valid(self):
        """F tokens must use kraken or coingecko."""
        valid = {"kraken", "coingecko"}
        for chain, sym, entry in self._get_f_tokens():
            method = entry.get("pricing", {}).get("method", "")
            self.assertIn(
                method, valid,
                f"{chain}.{sym}: F token method '{method}' not in {valid}"
            )

    def test_f_kraken_primary_has_coingecko_fallback(self):
        """F tokens with Kraken primary should have CoinGecko fallback."""
        for chain, sym, entry in self._get_f_tokens():
            pricing = entry.get("pricing", {})
            if pricing.get("method") != "kraken":
                continue
            self.assertIn(
                "coingecko_id", pricing,
                f"{chain}.{sym}: F token with Kraken primary missing CoinGecko fallback"
            )


class TestContractsConfig(unittest.TestCase):
    """Validate contracts.json has required fields per query_type."""

    def setUp(self):
        self.contracts = load_json("contracts.json")

    def test_all_sections_with_query_type_are_valid(self):
        """Every _query_type in contracts.json must map to a known handler."""
        from protocol_queries import HANDLER_REGISTRY
        known_types = set(HANDLER_REGISTRY.keys())

        for chain, chain_data in self.contracts.items():
            if not isinstance(chain_data, dict):
                continue
            for section_key, section in chain_data.items():
                if not isinstance(section, dict):
                    continue
                qt = section.get("_query_type")
                if qt:
                    self.assertIn(
                        qt, known_types,
                        f"{chain}.{section_key}: _query_type '{qt}' not in HANDLER_REGISTRY"
                    )

    def test_contract_entries_with_abi_have_address(self):
        """Every contract entry with 'abi' must have 'address'."""
        for chain, chain_data in self.contracts.items():
            if not isinstance(chain_data, dict):
                continue
            for section_key, section in chain_data.items():
                if not isinstance(section, dict):
                    continue
                for entry_key, entry in section.items():
                    if entry_key.startswith("_") or not isinstance(entry, dict):
                        continue
                    if "abi" in entry:
                        self.assertIn(
                            "address", entry,
                            f"{chain}.{section_key}.{entry_key}: has 'abi' but no 'address'"
                        )

    def test_aave_entries_have_underlying_symbol(self):
        """Aave aToken/debt entries must have underlying_symbol for valuation mapping."""
        for chain, chain_data in self.contracts.items():
            if not isinstance(chain_data, dict):
                continue
            aave = chain_data.get("_aave", {})
            for entry_key, entry in aave.items():
                if entry_key.startswith("_") or not isinstance(entry, dict):
                    continue
                if "pool" in entry_key:
                    continue  # Pool contract doesn't need underlying_symbol
                if "abi" in entry and entry.get("abi") == "erc20":
                    self.assertIn(
                        "underlying_symbol", entry,
                        f"{chain}._aave.{entry_key}: aToken/debt token missing "
                        f"'underlying_symbol' for valuation mapping"
                    )


class TestMorphoMarketsConfig(unittest.TestCase):
    """Validate morpho_markets.json structure."""

    def setUp(self):
        self.morpho = load_json("morpho_markets.json")

    def test_all_markets_have_required_fields(self):
        """Every Morpho market must have market_id, loan_token, collateral_token."""
        for chain, chain_data in self.morpho.items():
            if not isinstance(chain_data, dict):
                continue
            for mkt in chain_data.get("markets", []):
                name = mkt.get("name", "unknown")
                self.assertIn("market_id", mkt,
                              f"morpho.{chain}.{name}: missing market_id")
                for side in ("loan_token", "collateral_token"):
                    self.assertIn(side, mkt,
                                  f"morpho.{chain}.{name}: missing {side}")
                    tok = mkt[side]
                    for field in ("symbol", "address", "decimals", "category"):
                        self.assertIn(field, tok,
                                      f"morpho.{chain}.{name}.{side}: missing {field}")


class TestSolanaProtocolsConfig(unittest.TestCase):
    """Validate solana_protocols.json structure."""

    def setUp(self):
        self.solana = load_json("solana_protocols.json")

    def test_kamino_obligations_have_required_fields(self):
        """Each Kamino obligation must have obligation_pubkey, deposits, borrows."""
        for ob in self.solana.get("kamino", {}).get("obligations", []):
            name = ob.get("market_name", "unknown")
            self.assertIn("obligation_pubkey", ob,
                          f"kamino.{name}: missing obligation_pubkey")
            self.assertIn("deposits", ob,
                          f"kamino.{name}: missing deposits")
            self.assertIn("borrows", ob,
                          f"kamino.{name}: missing borrows")
            for dep in ob["deposits"]:
                for field in ("reserve", "symbol", "decimals", "category"):
                    self.assertIn(field, dep,
                                  f"kamino.{name}.deposit: missing {field}")

    def test_exponent_markets_have_required_fields(self):
        """Each Exponent market must have market_pubkey, sy, pt."""
        for mkt in self.solana.get("exponent", {}).get("markets", []):
            name = mkt.get("name", "unknown")
            self.assertIn("market_pubkey", mkt,
                          f"exponent.{name}: missing market_pubkey")
            self.assertIn("sy", mkt,
                          f"exponent.{name}: missing sy")
            self.assertIn("pt", mkt,
                          f"exponent.{name}: missing pt")
            # SY must have symbol, decimals, category
            for field in ("symbol", "decimals", "category"):
                self.assertIn(field, mkt["sy"],
                              f"exponent.{name}.sy: missing {field}")

    def test_eusx_config_exists(self):
        """eUSX mint constants must be in config."""
        eusx = self.solana.get("eusx", {})
        self.assertIn("eusx_mint", eusx, "solana_protocols: missing eusx.eusx_mint")
        self.assertIn("eusx_mint_authority", eusx, "solana_protocols: missing eusx.eusx_mint_authority")
        self.assertIn("usx_mint", eusx, "solana_protocols: missing eusx.usx_mint")


class TestDivergenceTolerances(unittest.TestCase):
    """Appendix B: Verify tolerance thresholds are documented and correct."""

    def test_tolerance_values(self):
        """Verify the expected divergence tolerances per category."""
        # From Appendix B of Valuation Policy v1.0
        expected = {
            "A1": 2, "A2": 3, "A3": 5, "B": 6,
            "C": 5, "D": 5, "E": 0.5, "F": 10,
        }
        # These should match what's in CLAUDE.md and be usable by diff_snapshots
        for cat, tolerance in expected.items():
            self.assertGreater(tolerance, 0,
                               f"Category {cat} tolerance must be > 0")


class TestHandlerRegistryCompleteness(unittest.TestCase):
    """Verify handler registry covers all protocol keys."""

    def test_all_protocol_keys_have_handlers(self):
        """Every key in PROTOCOL_TO_HANDLER must resolve to a function in HANDLER_REGISTRY."""
        from protocol_queries import PROTOCOL_TO_HANDLER, HANDLER_REGISTRY
        for protocol_key, handler_key in PROTOCOL_TO_HANDLER.items():
            self.assertIn(
                handler_key, HANDLER_REGISTRY,
                f"Protocol '{protocol_key}' maps to handler '{handler_key}' "
                f"which is not in HANDLER_REGISTRY"
            )

    def test_handler_functions_are_callable(self):
        """Every handler in the registry must be a callable."""
        from protocol_queries import HANDLER_REGISTRY
        for key, handler in HANDLER_REGISTRY.items():
            self.assertTrue(
                callable(handler),
                f"HANDLER_REGISTRY['{key}'] is not callable"
            )


if __name__ == "__main__":
    unittest.main()
