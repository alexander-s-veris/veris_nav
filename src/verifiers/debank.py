"""
DeBank portfolio-level verifier.

Tier 1: Wallet aggregate — our total vs DeBank total_balance (deduplicated).
Tier 2: Token detail — unified DeBank view matched against our positions.

Unified DeBank view = all_token_list + protocol entries NOT already
represented in token_list (dedup by pool.controller ∈ token contracts).

API: pro-openapi.debank.com/v1, auth via AccessKey header.
"""
