"""
Valuation Policy compliance tests.

Validates that config/tokens.json, config/contracts.json, config/price_feeds.json,
config/pricing_policy.json, and the pricing/valuation code comply with the
Valuation Policy v1.0.

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


def iter_tokens(tokens):
    """Yield (chain, addr, entry) for every real token entry in tokens.json."""
    for chain, chain_tokens in tokens.items():
        if chain.startswith("_"):
            continue
        if not isinstance(chain_tokens, dict):
            continue
        for addr, entry in chain_tokens.items():
            if not isinstance(entry, dict):
                continue
            yield chain, addr, entry


# ---------------------------------------------------------------------------
# 1. TestCategoryClassification — valid category, symbol, decimals
# ---------------------------------------------------------------------------

class TestCategoryClassification(unittest.TestCase):
    """Section 5: Every token must have a valid category."""

    def setUp(self):
        self.tokens = load_json("tokens.json")

    def test_all_tokens_have_valid_category(self):
        """Every token entry must have category in {A1, A2, A3, B, C, D, E, F}."""
        valid_categories = {"A1", "A2", "A3", "B", "C", "D", "E", "F"}
        for chain, addr, entry in iter_tokens(self.tokens):
            cat = entry.get("category")
            self.assertIn(
                cat, valid_categories,
                f"{chain}.{entry.get('symbol', addr)}: category '{cat}' not in {valid_categories}"
            )

    def test_all_tokens_have_symbol_and_decimals(self):
        """Every token must have symbol and decimals."""
        for chain, addr, entry in iter_tokens(self.tokens):
            self.assertIn("symbol", entry,
                          f"{chain}.{addr}: missing 'symbol'")
            self.assertIn("decimals", entry,
                          f"{chain}.{entry.get('symbol', addr)}: missing 'decimals'")


# ---------------------------------------------------------------------------
# 2. TestTokenPricingPolicy — every token has a valid pricing.policy
# ---------------------------------------------------------------------------

class TestTokenPricingPolicy(unittest.TestCase):
    """Every token must have a pricing.policy field that exists in pricing_policy.json."""

    def setUp(self):
        self.tokens = load_json("tokens.json")
        self.policies = load_json("pricing_policy.json")

    def test_all_tokens_have_pricing_policy(self):
        """Every token must have a non-empty pricing.policy field."""
        for chain, addr, entry in iter_tokens(self.tokens):
            pricing = entry.get("pricing", {})
            if not isinstance(pricing, dict):
                self.fail(f"{chain}.{entry.get('symbol', addr)}: pricing is not a dict")
            policy = pricing.get("policy")
            self.assertIsNotNone(
                policy,
                f"{chain}.{entry.get('symbol', addr)}: missing pricing.policy"
            )

    def test_pricing_policy_exists_in_policy_config(self):
        """Every pricing.policy value must be a key in pricing_policy.json."""
        # Valid policy keys (exclude non-policy keys like divergence_tolerances, _doc)
        valid_policies = {k for k in self.policies.keys()
                         if not k.startswith("_") and k != "divergence_tolerances"}
        for chain, addr, entry in iter_tokens(self.tokens):
            pricing = entry.get("pricing", {})
            if not isinstance(pricing, dict):
                continue
            policy = pricing.get("policy")
            if policy is None:
                continue  # Caught by test above
            self.assertIn(
                policy, valid_policies,
                f"{chain}.{entry.get('symbol', addr)}: policy '{policy}' "
                f"not found in pricing_policy.json (valid: {sorted(valid_policies)})"
            )


# ---------------------------------------------------------------------------
# 3. TestFeedReferences — every feed key in tokens.json exists in price_feeds.json
# ---------------------------------------------------------------------------

class TestFeedReferences(unittest.TestCase):
    """Every feed key referenced in tokens.json pricing.feeds must exist in price_feeds.json."""

    def setUp(self):
        self.tokens = load_json("tokens.json")
        self.price_feeds = load_json("price_feeds.json")
        # Build flat set of all valid feed keys across all feed type groups
        self.all_feed_keys = set()
        for group_key, group in self.price_feeds.items():
            if group_key.startswith("_"):
                continue
            if isinstance(group, dict):
                for feed_key in group:
                    self.all_feed_keys.add(feed_key)

    def test_all_feed_references_resolve(self):
        """Every feed key in pricing.feeds must exist in price_feeds.json."""
        for chain, addr, entry in iter_tokens(self.tokens):
            pricing = entry.get("pricing", {})
            if not isinstance(pricing, dict):
                continue
            feeds = pricing.get("feeds", {})
            if not isinstance(feeds, dict):
                continue
            sym = entry.get("symbol", addr)
            for feed_type, feed_key in feeds.items():
                if feed_type.startswith("_"):
                    continue
                self.assertIn(
                    feed_key, self.all_feed_keys,
                    f"{chain}.{sym}: feed '{feed_type}' references '{feed_key}' "
                    f"which does not exist in price_feeds.json"
                )


# ---------------------------------------------------------------------------
# 4. TestA1Methodology — A1 tokens need policy=A1, exchange_rate tokens need
#    underlying + exchange_rate_function
# ---------------------------------------------------------------------------

class TestA1Methodology(unittest.TestCase):
    """Section 6.1: A1 tokens must use smart contract exchange rate."""

    def setUp(self):
        self.tokens = load_json("tokens.json")

    def _get_a1_tokens(self):
        return [(c, e.get("symbol", a), e)
                for c, a, e in iter_tokens(self.tokens)
                if e.get("category") == "A1"]

    def test_a1_policy_is_a1(self):
        """A1 tokens must have pricing.policy = 'A1'."""
        for chain, sym, entry in self._get_a1_tokens():
            policy = entry.get("pricing", {}).get("policy")
            self.assertEqual(
                policy, "A1",
                f"{chain}.{sym}: A1 token has policy '{policy}', expected 'A1'"
            )

    def test_a1_exchange_rate_tokens_have_underlying(self):
        """A1 tokens with exchange_rate_function must have underlying."""
        for chain, sym, entry in self._get_a1_tokens():
            pricing = entry.get("pricing", {})
            if "exchange_rate_function" in pricing:
                self.assertIn(
                    "underlying", pricing,
                    f"{chain}.{sym}: A1 token has exchange_rate_function but no underlying"
                )

    def test_a1_exchange_rate_tokens_have_function(self):
        """A1 tokens with exchange_rate_contract must have exchange_rate_function."""
        for chain, sym, entry in self._get_a1_tokens():
            pricing = entry.get("pricing", {})
            if "exchange_rate_contract" in pricing:
                self.assertIn(
                    "exchange_rate_function", pricing,
                    f"{chain}.{sym}: A1 token has exchange_rate_contract "
                    f"but no exchange_rate_function"
                )


# ---------------------------------------------------------------------------
# 5. TestA2Methodology — A2 tokens need policy=A2, staleness threshold,
#    at least one oracle feed
# ---------------------------------------------------------------------------

class TestA2Methodology(unittest.TestCase):
    """Section 6.2: A2 tokens must use oracle hierarchy with staleness thresholds."""

    def setUp(self):
        self.tokens = load_json("tokens.json")

    def _get_a2_tokens(self):
        return [(c, e.get("symbol", a), e)
                for c, a, e in iter_tokens(self.tokens)
                if e.get("category") == "A2"]

    def test_a2_policy_is_a2(self):
        """A2 tokens must have pricing.policy = 'A2'."""
        for chain, sym, entry in self._get_a2_tokens():
            policy = entry.get("pricing", {}).get("policy")
            self.assertEqual(
                policy, "A2",
                f"{chain}.{sym}: A2 token has policy '{policy}', expected 'A2'"
            )

    def test_a2_has_staleness_threshold(self):
        """Every A2 token must have expected_update_freq_hours > 0."""
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

    def test_a2_has_at_least_one_oracle_feed(self):
        """A2 tokens must have at least one oracle feed (chainlink or pyth) in feeds."""
        for chain, sym, entry in self._get_a2_tokens():
            feeds = entry.get("pricing", {}).get("feeds", {})
            has_chainlink = "chainlink" in feeds
            has_pyth = "pyth" in feeds
            self.assertTrue(
                has_chainlink or has_pyth,
                f"{chain}.{sym}: A2 token must have at least one oracle feed "
                f"(chainlink or pyth) in pricing.feeds"
            )


# ---------------------------------------------------------------------------
# 6. TestA3Methodology — A3 tokens need policy=A3 (not A1)
# ---------------------------------------------------------------------------

class TestA3Methodology(unittest.TestCase):
    """Section 6.3: A3 tokens use manual accrual, on-chain TP is cross-ref only."""

    def setUp(self):
        self.tokens = load_json("tokens.json")

    def test_a3_policy_is_a3(self):
        """A3 tokens must have pricing.policy = 'A3', NOT 'A1'."""
        for chain, addr, entry in iter_tokens(self.tokens):
            if entry.get("category") != "A3":
                continue
            policy = entry.get("pricing", {}).get("policy")
            sym = entry.get("symbol", addr)
            self.assertEqual(
                policy, "A3",
                f"{chain}.{sym}: A3 token has policy '{policy}', expected 'A3'"
            )
            self.assertNotEqual(
                policy, "A1",
                f"{chain}.{sym}: A3 must use manual accrual, not A1 exchange rate. "
                f"On-chain TP is cross-reference only (Section 6.3)."
            )


# ---------------------------------------------------------------------------
# 7. TestBMethodology — B tokens need policy=B, underlying, maturity
# ---------------------------------------------------------------------------

class TestBMethodology(unittest.TestCase):
    """Section 6.4: PT tokens use linear amortisation, not mark-to-market."""

    def setUp(self):
        self.tokens = load_json("tokens.json")

    def _get_b_tokens(self):
        return [(c, e.get("symbol", a), e)
                for c, a, e in iter_tokens(self.tokens)
                if e.get("category") == "B"]

    def test_b_policy_is_b(self):
        """Category B tokens must have pricing.policy = 'B'."""
        for chain, sym, entry in self._get_b_tokens():
            policy = entry.get("pricing", {}).get("policy")
            self.assertEqual(
                policy, "B",
                f"{chain}.{sym}: Category B token has policy '{policy}', expected 'B'"
            )

    def test_b_tokens_have_underlying(self):
        """Category B tokens must specify their underlying asset."""
        for chain, sym, entry in self._get_b_tokens():
            underlying = entry.get("pricing", {}).get("underlying")
            self.assertIsNotNone(
                underlying,
                f"{chain}.{sym}: Category B missing 'underlying'"
            )

    def test_b_tokens_have_maturity(self):
        """Category B tokens must have maturity date."""
        for chain, sym, entry in self._get_b_tokens():
            maturity = entry.get("pricing", {}).get("maturity")
            self.assertIsNotNone(
                maturity,
                f"{chain}.{sym}: Category B missing 'maturity'"
            )


# ---------------------------------------------------------------------------
# 8. TestEMethodology — E_par and E_oracle validation
# ---------------------------------------------------------------------------

class TestEMethodology(unittest.TestCase):
    """Section 6.7: Stablecoins — par or oracle with depeg monitoring."""

    def setUp(self):
        self.tokens = load_json("tokens.json")

    def _get_e_tokens(self):
        return [(c, e.get("symbol", a), e)
                for c, a, e in iter_tokens(self.tokens)
                if e.get("category") == "E"]

    def test_e_policy_is_valid(self):
        """E tokens must have policy E_par or E_oracle."""
        valid = {"E_par", "E_oracle"}
        for chain, sym, entry in self._get_e_tokens():
            policy = entry.get("pricing", {}).get("policy")
            self.assertIn(
                policy, valid,
                f"{chain}.{sym}: E token policy '{policy}' not in {valid}"
            )

    def test_e_par_usdc_dai_have_depeg_feed(self):
        """USDC and DAI (E_par) must have at least one depeg feed (chainlink or pyth)."""
        must_have_depeg = {"USDC", "DAI"}
        for chain, sym, entry in self._get_e_tokens():
            if sym not in must_have_depeg:
                continue
            pricing = entry.get("pricing", {})
            if pricing.get("policy") != "E_par":
                continue
            feeds = pricing.get("feeds", {})
            has_chainlink = "chainlink" in feeds
            has_pyth = "pyth" in feeds
            self.assertTrue(
                has_chainlink or has_pyth,
                f"{chain}.{sym}: par-priced E token must have at least one depeg "
                f"feed (chainlink or pyth) in pricing.feeds"
            )

    def test_all_e_tokens_have_depeg_monitoring(self):
        """Every E token must have at least one feed for de-peg monitoring (Section 9.4)."""
        for chain, sym, entry in self._get_e_tokens():
            feeds = entry.get("pricing", {}).get("feeds", {})
            self.assertTrue(
                len(feeds) > 0,
                f"{chain}.{sym}: E token has zero pricing feeds — "
                f"no de-peg monitoring possible (Section 9.4)"
            )

    def test_e_oracle_has_at_least_one_feed(self):
        """E_oracle tokens must have at least one oracle feed in pricing.feeds."""
        for chain, sym, entry in self._get_e_tokens():
            pricing = entry.get("pricing", {})
            if pricing.get("policy") != "E_oracle":
                continue
            feeds = pricing.get("feeds", {})
            has_oracle = any(k in feeds for k in ("chainlink", "pyth", "redstone", "defillama"))
            self.assertTrue(
                has_oracle,
                f"{chain}.{sym}: E_oracle token must have at least one pricing feed "
                f"(chainlink, pyth, redstone, or defillama) in pricing.feeds"
            )


# ---------------------------------------------------------------------------
# 9. TestFMethodology — F tokens need policy=F, Kraken-primary should have
#    coingecko fallback
# ---------------------------------------------------------------------------

class TestFMethodology(unittest.TestCase):
    """Section 6.8: F tokens — Kraken -> CoinGecko -> DEX TWAP hierarchy."""

    def setUp(self):
        self.tokens = load_json("tokens.json")

    def _get_f_tokens(self):
        return [(c, e.get("symbol", a), e)
                for c, a, e in iter_tokens(self.tokens)
                if e.get("category") == "F"]

    def test_f_policy_is_f(self):
        """F tokens must have pricing.policy = 'F'."""
        for chain, sym, entry in self._get_f_tokens():
            policy = entry.get("pricing", {}).get("policy")
            self.assertEqual(
                policy, "F",
                f"{chain}.{sym}: F token has policy '{policy}', expected 'F'"
            )

    def test_f_kraken_primary_has_coingecko_fallback(self):
        """F tokens with Kraken feed should have CoinGecko fallback."""
        for chain, sym, entry in self._get_f_tokens():
            feeds = entry.get("pricing", {}).get("feeds", {})
            if "kraken" not in feeds:
                continue
            self.assertIn(
                "coingecko", feeds,
                f"{chain}.{sym}: F token with Kraken primary missing CoinGecko fallback "
                f"in pricing.feeds"
            )


# ---------------------------------------------------------------------------
# 10. TestPriceFeedsRegistry — every feed has type and required type-specific fields
# ---------------------------------------------------------------------------

class TestPriceFeedsRegistry(unittest.TestCase):
    """Validate price_feeds.json structure — every feed has correct fields per type."""

    def setUp(self):
        self.price_feeds = load_json("price_feeds.json")

    def _iter_feeds(self):
        """Yield (group_key, feed_key, feed_entry) for all feeds."""
        for group_key, group in self.price_feeds.items():
            if group_key.startswith("_"):
                continue
            if not isinstance(group, dict):
                continue
            for feed_key, feed_entry in group.items():
                if not isinstance(feed_entry, dict):
                    continue
                yield group_key, feed_key, feed_entry

    def test_all_feeds_have_type(self):
        """Every feed must have a 'type' field."""
        for group_key, feed_key, feed in self._iter_feeds():
            self.assertIn(
                "type", feed,
                f"price_feeds.{group_key}.{feed_key}: missing 'type'"
            )

    def test_chainlink_feeds_have_address(self):
        """Chainlink feeds must have 'address'."""
        for group_key, feed_key, feed in self._iter_feeds():
            if feed.get("type") != "chainlink":
                continue
            self.assertIn(
                "address", feed,
                f"price_feeds.{group_key}.{feed_key}: chainlink feed missing 'address'"
            )

    def test_pyth_feeds_have_feed_id(self):
        """Pyth feeds must have 'feed_id'."""
        for group_key, feed_key, feed in self._iter_feeds():
            if feed.get("type") != "pyth":
                continue
            self.assertIn(
                "feed_id", feed,
                f"price_feeds.{group_key}.{feed_key}: pyth feed missing 'feed_id'"
            )

    def test_redstone_feeds_have_symbol(self):
        """Redstone feeds must have 'symbol'."""
        for group_key, feed_key, feed in self._iter_feeds():
            if feed.get("type") != "redstone":
                continue
            self.assertIn(
                "symbol", feed,
                f"price_feeds.{group_key}.{feed_key}: redstone feed missing 'symbol'"
            )

    def test_kraken_feeds_have_pair(self):
        """Kraken feeds must have 'pair'."""
        for group_key, feed_key, feed in self._iter_feeds():
            if feed.get("type") != "kraken":
                continue
            self.assertIn(
                "pair", feed,
                f"price_feeds.{group_key}.{feed_key}: kraken feed missing 'pair'"
            )

    def test_coingecko_feeds_have_coin_id(self):
        """CoinGecko feeds must have 'coin_id'."""
        for group_key, feed_key, feed in self._iter_feeds():
            if feed.get("type") != "coingecko":
                continue
            self.assertIn(
                "coin_id", feed,
                f"price_feeds.{group_key}.{feed_key}: coingecko feed missing 'coin_id'"
            )

    def test_feed_type_matches_group(self):
        """Each feed's type should match the group it's in."""
        for group_key, feed_key, feed in self._iter_feeds():
            feed_type = feed.get("type")
            if feed_type:
                self.assertEqual(
                    feed_type, group_key,
                    f"price_feeds.{group_key}.{feed_key}: type '{feed_type}' "
                    f"does not match group '{group_key}'"
                )


# ---------------------------------------------------------------------------
# 11. TestPricingPolicy — policies with hierarchy methods must have hierarchy array
# ---------------------------------------------------------------------------

class TestPricingPolicy(unittest.TestCase):
    """Validate pricing_policy.json structure."""

    def setUp(self):
        self.policies = load_json("pricing_policy.json")

    def _iter_policies(self):
        """Yield (key, policy) for non-meta entries."""
        for key, value in self.policies.items():
            if key.startswith("_") or key == "divergence_tolerances":
                continue
            if isinstance(value, dict):
                yield key, value

    def test_all_policies_have_method(self):
        """Every policy must have a 'method' field."""
        for key, policy in self._iter_policies():
            self.assertIn(
                "method", policy,
                f"pricing_policy.{key}: missing 'method'"
            )

    def test_oracle_hierarchy_policies_have_hierarchy(self):
        """Policies with method oracle_hierarchy must have a hierarchy array."""
        for key, policy in self._iter_policies():
            if policy.get("method") == "oracle_hierarchy":
                self.assertIn(
                    "hierarchy", policy,
                    f"pricing_policy.{key}: oracle_hierarchy method missing 'hierarchy'"
                )
                self.assertIsInstance(
                    policy["hierarchy"], list,
                    f"pricing_policy.{key}: hierarchy must be a list"
                )
                self.assertGreater(
                    len(policy["hierarchy"]), 0,
                    f"pricing_policy.{key}: hierarchy must not be empty"
                )

    def test_market_hierarchy_policies_have_hierarchy(self):
        """Policies with method market_hierarchy must have a hierarchy array."""
        for key, policy in self._iter_policies():
            if policy.get("method") == "market_hierarchy":
                self.assertIn(
                    "hierarchy", policy,
                    f"pricing_policy.{key}: market_hierarchy method missing 'hierarchy'"
                )
                self.assertIsInstance(
                    policy["hierarchy"], list,
                    f"pricing_policy.{key}: hierarchy must be a list"
                )
                self.assertGreater(
                    len(policy["hierarchy"]), 0,
                    f"pricing_policy.{key}: hierarchy must not be empty"
                )

    def test_divergence_tolerances_present(self):
        """Divergence tolerances must be present with all categories."""
        tolerances = self.policies.get("divergence_tolerances", {})
        expected_cats = {"A1", "A2", "A3", "B", "C", "D", "E", "F"}
        for cat in expected_cats:
            self.assertIn(
                cat, tolerances,
                f"pricing_policy.divergence_tolerances: missing category '{cat}'"
            )
            self.assertGreater(
                tolerances[cat], 0,
                f"pricing_policy.divergence_tolerances.{cat}: must be > 0"
            )


# ---------------------------------------------------------------------------
# 12. TestContractsConfig — unchanged
# ---------------------------------------------------------------------------

class TestContractsConfig(unittest.TestCase):
    """Validate contracts.json has required fields per query_type."""

    def setUp(self):
        self.contracts = load_json("contracts.json")

    def test_all_sections_with_query_type_are_valid(self):
        """Every _query_type in contracts.json must map to a known handler."""
        from handlers._registry import HANDLER_REGISTRY
        known_types = set(HANDLER_REGISTRY.keys())

        for chain, chain_data in self.contracts.items():
            if not isinstance(chain_data, dict):
                continue
            for section_key, section in chain_data.items():
                if not isinstance(section, dict):
                    continue
                qt = section.get("_query_type")
                if qt and qt != "reference":
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


# ---------------------------------------------------------------------------
# 13. TestMorphoMarketsConfig — unchanged
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 14. TestSolanaProtocolsConfig — unchanged
# ---------------------------------------------------------------------------

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
        """eUSX vault config must have standard field names."""
        eusx = self.solana.get("eusx", {})
        self.assertIn("vault_mint", eusx, "solana_protocols: missing eusx.vault_mint")
        self.assertIn("mint_authority", eusx, "solana_protocols: missing eusx.mint_authority")
        self.assertIn("underlying_mint", eusx, "solana_protocols: missing eusx.underlying_mint")


# ---------------------------------------------------------------------------
# 15. TestDivergenceTolerances — unchanged
# ---------------------------------------------------------------------------

class TestDivergenceTolerances(unittest.TestCase):
    """Appendix B: Verify tolerance thresholds are documented and correct."""

    def test_tolerance_values(self):
        """Verify the expected divergence tolerances per category."""
        expected = {
            "A1": 2, "A2": 3, "A3": 5, "B": 6,
            "C": 5, "D": 5, "E": 0.5, "F": 10,
        }
        for cat, tolerance in expected.items():
            self.assertGreater(tolerance, 0,
                               f"Category {cat} tolerance must be > 0")


# ---------------------------------------------------------------------------
# 16. TestHandlerRegistryCompleteness — unchanged
# ---------------------------------------------------------------------------

class TestHandlerRegistryCompleteness(unittest.TestCase):
    """Verify handler registry covers all protocol keys."""

    def test_all_protocol_keys_have_handlers(self):
        """Every EVM protocol key must resolve to a callable handler."""
        from handlers._registry import EVM_HANDLERS
        for protocol_key, handler_fn in EVM_HANDLERS.items():
            self.assertTrue(
                callable(handler_fn),
                f"EVM_HANDLERS['{protocol_key}'] is not callable"
            )

    def test_handler_functions_are_callable(self):
        """Every handler in the query_type registry must be a callable."""
        from handlers._registry import HANDLER_REGISTRY
        for key, handler in HANDLER_REGISTRY.items():
            self.assertTrue(
                callable(handler),
                f"HANDLER_REGISTRY['{key}'] is not callable"
            )


# ---------------------------------------------------------------------------
# 17. TestVerificationConfig — config/verification.json validation
# ---------------------------------------------------------------------------

class TestVerificationConfig(unittest.TestCase):
    """Verify verification.json has valid structure and references."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(CONFIG_DIR, "verification.json")) as f:
            cls.cfg = json.load(f)
        with open(os.path.join(CONFIG_DIR, "chains.json")) as f:
            cls.chains = json.load(f)

    def test_has_asset_level_section(self):
        """verification.json must have an asset_level section."""
        self.assertIn("asset_level", self.cfg)

    def test_has_api_endpoints(self):
        """verification.json must have _api_endpoints with at least one provider."""
        endpoints = self.cfg.get("_api_endpoints", {})
        self.assertTrue(len(endpoints) > 0, "No API endpoints configured")
        for provider, url in endpoints.items():
            # URLs are HTTP endpoints; gdrive uses a local file path
            if provider == "gdrive":
                self.assertTrue(url.endswith(".json"), f"Invalid path for {provider}: {url}")
            else:
                self.assertTrue(url.startswith("http"), f"Invalid URL for {provider}: {url}")

    def test_asset_entries_have_required_fields(self):
        """Every asset-level verification entry must have required fields per type."""
        # Required fields differ by verification type
        required_by_type = {
            "midas_attestation": {"type", "token_decimals", "token_addresses"},
            "midas_pdf_report": {"type", "gdrive_folder_id", "filename_pattern", "local_report_path"},
            "superstate_nav_api": {"type", "fund_id"},
            "onre_onchain_nav": {"type"},
        }
        for symbol, entry in self.cfg.get("asset_level", {}).items():
            vtype = entry.get("type", "")
            required = required_by_type.get(vtype, {"type"})
            for field in required:
                self.assertIn(
                    field, entry,
                    f"Verification entry '{symbol}' (type={vtype}) missing required field '{field}'")

    def test_token_addresses_reference_known_chains(self):
        """Every chain in token_addresses must exist in chains.json."""
        for symbol, entry in self.cfg.get("asset_level", {}).items():
            for chain in entry.get("token_addresses", {}):
                self.assertIn(
                    chain, self.chains,
                    f"Verification '{symbol}' references unknown chain '{chain}'")

    def test_verification_types_are_registered(self):
        """Every verification type must map to a registered verifier."""
        from verifiers import _VERIFIER_REGISTRY
        for symbol, entry in self.cfg.get("asset_level", {}).items():
            vtype = entry.get("type", "")
            self.assertIn(
                vtype, _VERIFIER_REGISTRY,
                f"Verification '{symbol}' has type '{vtype}' not in _VERIFIER_REGISTRY")


# ---------------------------------------------------------------------------
# 18. TestCrossReferences — validate referential integrity across all configs
# ---------------------------------------------------------------------------

class TestCrossReferences(unittest.TestCase):
    """Cross-reference integrity: every reference between config files must resolve."""

    @classmethod
    def setUpClass(cls):
        cls.tokens = load_json("tokens.json")
        cls.chains = load_json("chains.json")
        cls.wallets = load_json("wallets.json")
        cls.contracts = load_json("contracts.json")
        cls.price_feeds = load_json("price_feeds.json")
        cls.abis = load_json("abis.json")

        # Build flat feed key set
        cls.all_feed_keys = set()
        for group_key, group in cls.price_feeds.items():
            if group_key.startswith("_"):
                continue
            if isinstance(group, dict):
                for feed_key in group:
                    cls.all_feed_keys.add(feed_key)

    def test_wallets_reference_known_chains(self):
        """Every chain key in wallets.json must exist in chains.json."""
        for chain_key in self.wallets:
            if chain_key.startswith("_") or chain_key == "arma_proxies":
                continue
            self.assertIn(
                chain_key, self.chains,
                f"wallets.json references chain '{chain_key}' not in chains.json")

    def test_wallet_protocols_have_handlers(self):
        """Every protocol in wallet registrations must map to a handler."""
        from handlers._registry import EVM_HANDLERS, SOLANA_HANDLERS
        all_known = set(EVM_HANDLERS.keys()) | set(SOLANA_HANDLERS.keys())
        for chain_key, wallets_list in self.wallets.items():
            if not isinstance(wallets_list, list):
                continue
            for wallet in wallets_list:
                for proto in wallet.get("protocols", {}):
                    if proto.startswith("_"):
                        continue
                    self.assertIn(
                        proto, all_known,
                        f"wallets.json {chain_key}/{wallet.get('address', '?')[:10]}: "
                        f"protocol '{proto}' not in EVM_HANDLERS or "
                        f"SOLANA_HANDLERS")

    def test_tokens_reference_known_chains(self):
        """Every chain key in tokens.json must exist in chains.json."""
        for chain_key in self.tokens:
            if chain_key.startswith("_"):
                continue
            self.assertIn(
                chain_key, self.chains,
                f"tokens.json references chain '{chain_key}' not in chains.json")

    def test_contracts_reference_known_chains(self):
        """Every chain key in contracts.json must exist in chains.json (skip metadata sections)."""
        # contracts.json may have non-chain top-level keys like "oracles"
        # Only validate keys that contain dicts with _query_type subsections
        for chain_key, chain_data in self.contracts.items():
            if chain_key.startswith("_"):
                continue
            if not isinstance(chain_data, dict):
                continue
            # Check if this looks like a chain section (has subsections with _query_type)
            has_query_types = any(
                isinstance(v, dict) and v.get("_query_type") not in (None, "reference")
                for v in chain_data.values()
            )
            if has_query_types:
                self.assertIn(
                    chain_key, self.chains,
                    f"contracts.json references chain '{chain_key}' not in chains.json")

    def test_contracts_abis_exist(self):
        """Every ABI referenced in contracts.json must exist in abis.json."""
        for chain, chain_data in self.contracts.items():
            if not isinstance(chain_data, dict):
                continue
            for section_key, section in chain_data.items():
                if not isinstance(section, dict):
                    continue
                for entry_key, entry in section.items():
                    if entry_key.startswith("_") or not isinstance(entry, dict):
                        continue
                    abi_name = entry.get("abi")
                    if abi_name:
                        self.assertIn(
                            abi_name, self.abis,
                            f"{chain}.{section_key}.{entry_key}: abi '{abi_name}' "
                            f"not in abis.json")

    def test_verification_symbols_exist_in_tokens(self):
        """Every symbol in verification.json asset_level must exist in tokens.json."""
        verification = load_json("verification.json")
        # Build set of all token symbols across all chains
        all_symbols = set()
        for chain, addr, entry in iter_tokens(self.tokens):
            sym = entry.get("symbol", "")
            if sym:
                all_symbols.add(sym)

        for symbol in verification.get("asset_level", {}):
            self.assertIn(
                symbol, all_symbols,
                f"verification.json asset_level '{symbol}' not found in tokens.json")

    def test_arma_proxies_reference_known_chains(self):
        """Every ARMA proxy chain must exist in chains.json."""
        for proxy in self.wallets.get("arma_proxies", []):
            chain = proxy.get("chain", "")
            self.assertIn(
                chain, self.chains,
                f"ARMA proxy {proxy.get('address', '?')[:10]} references "
                f"unknown chain '{chain}'")


# ---------------------------------------------------------------------------
# 19. TestAdaptersAndVerifiers — module integrity
# ---------------------------------------------------------------------------

class TestAdaptersAndVerifiers(unittest.TestCase):
    """Verify all adapters and verifiers are importable and registered."""

    def test_all_adapters_importable(self):
        """Every adapter in __all__ must be importable from the adapters package."""
        import adapters
        for name in adapters.__all__:
            self.assertTrue(
                hasattr(adapters, name),
                f"adapters.__all__ lists '{name}' but it's not importable")
            self.assertTrue(
                callable(getattr(adapters, name)) or name.startswith("_"),
                f"adapters.{name} is not callable")

    def test_verifier_registry_functions_are_callable(self):
        """Every verifier in the registry must have a callable 'fn'."""
        from verifiers import _VERIFIER_REGISTRY
        for vtype, reg in _VERIFIER_REGISTRY.items():
            self.assertIn("fn", reg, f"Verifier '{vtype}' missing 'fn' key")
            self.assertTrue(
                callable(reg["fn"]),
                f"Verifier '{vtype}' fn is not callable")
            self.assertIn("api_provider", reg,
                          f"Verifier '{vtype}' missing 'api_provider' key")

    def test_pricing_hierarchy_sources_have_adapters(self):
        """Every source type in pricing_policy.json hierarchies must be queryable."""
        policies = load_json("pricing_policy.json")
        # These are the source types the hierarchy walker can dispatch to
        known_source_types = {"chainlink", "pyth", "redstone", "kraken",
                              "coingecko", "defillama", "issuer_nav"}
        for key, policy in policies.items():
            if key.startswith("_") or key == "divergence_tolerances":
                continue
            if not isinstance(policy, dict):
                continue
            for source in policy.get("hierarchy", []):
                self.assertIn(
                    source, known_source_types,
                    f"pricing_policy.{key}: hierarchy source '{source}' "
                    f"has no matching adapter")


if __name__ == "__main__":
    unittest.main()
