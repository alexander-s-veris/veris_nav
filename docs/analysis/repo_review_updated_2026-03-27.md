# Updated repository review (post strict-config/tests/CI changes)

Date reviewed: 2026-03-27

## Scope reviewed
- Runtime paths in `collect.py`, `protocol_queries.py`, and `pricing.py`
- New test coverage in `tests/test_config_and_pricing.py`
- CI checks in `.github/workflows/python-checks.yml`

## What improved vs prior state

1. **Config validation now supports strict mode** via `--strict-config` and can fail early on malformed registry data.
2. **Pricing dispatcher is more defensive** for malformed token entries and now avoids several KeyError/TypeError paths.
3. **Regression tests exist** for strict/non-strict config behavior and malformed pricing payloads.
4. **CI pipeline now executes tests and compile checks** on PRs.

These materially reduce operational regressions.

## Remaining high-impact gaps (prioritized)

### P1 — Provider-aware concurrency controls
`collect.py` still scales worker count with chain count in some places (`max_workers=len(evm_chains)` / `len(evm_tasks)`), which can overrun provider limits when chains increase.

**Recommendation:** Add per-chain/provider worker budgets in `chains.json` and use those budgets in `concurrent_query` call sites.

### P1 — Strict validation coverage is still partial
Current `_validate_config()` checks a useful subset, but does not enforce full schema-level validation for every config object and type shape.

**Recommendation:** Add JSON Schema (or Pydantic) validation in CI for all top-level config files.

### P2 — Pricing fallback policy is implicit in code
Fallback ordering exists but is code-distributed. It is harder to audit policy intent and freshness requirements per category.

**Recommendation:** Move fallback policy and freshness thresholds to config and emit price age metadata in outputs.

### P2 — Output schema compatibility contract
The system has rich outputs but no explicit versioning contract in every artifact.

**Recommendation:** include `schema_version` and `generator_version` in all output files to protect downstream workbook ingestion.

## Conclusion
The repo is in a better state than the previous review cycle because it now has strict validation controls, regression tests, and CI execution. The next practical step is moving from defensive runtime coding to declarative validation/policy controls so scaling to more chains/tokens stays low-change.
