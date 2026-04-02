"""
Auto-registration decorators for protocol handlers.

Separate module to avoid circular imports -- handler files import utilities
from handlers/__init__.py, so the registries live here instead.

Usage:
    @register_evm_handler("credit_coop")
    def query_creditcoop(w3, chain, wallet, block_number, block_ts): ...

    @register_solana_handler("kamino", display_name="Kamino")
    def query_kamino_obligations(wallet, block_ts): ...
"""

import importlib
import os

# protocol_key -> handler_fn (flattened, no intermediate handler_key)
EVM_HANDLERS = {}

# protocol_key -> [(display_name, handler_fn), ...]
SOLANA_HANDLERS = {}

# query_type -> handler_fn (for contracts.json _query_type validation)
HANDLER_REGISTRY = {}

# protocol_key -> display name (for output formatting)
DISPLAY_NAMES = {}


def register_evm_handler(*protocol_keys, query_type=None, display_name=None):
    """Register an EVM handler for one or more protocol keys.

    Args:
        *protocol_keys: Protocol keys from wallets.json (e.g. "credit_coop").
        query_type: Optional contracts.json _query_type value. If provided,
                    the handler is also added to HANDLER_REGISTRY for
                    config validation.
        display_name: Human-readable protocol name for output (e.g. "Credit Coop").
                      Applied to the first protocol key only.
    """
    def decorator(fn):
        for key in protocol_keys:
            if key in EVM_HANDLERS:
                raise ValueError(
                    f"Duplicate EVM handler registration for '{key}': "
                    f"{fn.__name__} vs {EVM_HANDLERS[key].__name__}")
            EVM_HANDLERS[key] = fn
        if query_type:
            HANDLER_REGISTRY[query_type] = fn
        if display_name:
            DISPLAY_NAMES[protocol_keys[0]] = display_name
        return fn
    return decorator


def register_solana_handler(protocol_key, display_name, output_name=None):
    """Register a Solana handler under a protocol key.

    Multiple handlers can share a protocol key (e.g. exponent has LP + YT).

    Args:
        protocol_key: Protocol key from wallets.json (e.g. "kamino").
        display_name: Human-readable name for logging (e.g. "Exponent LP").
        output_name: Protocol name for CSV/JSON output. Defaults to display_name.
                     Only the first handler registered for a key sets this.
    """
    def decorator(fn):
        if protocol_key not in SOLANA_HANDLERS:
            SOLANA_HANDLERS[protocol_key] = []
        SOLANA_HANDLERS[protocol_key].append((display_name, fn))
        # First handler registered for this key sets the output display name
        if protocol_key not in DISPLAY_NAMES:
            DISPLAY_NAMES[protocol_key] = output_name or display_name
        return fn
    return decorator


_discovered = False


def discover_handlers():
    """Import all handler modules to trigger decorator registration.

    Called once from handlers/__init__.py after utilities are defined.
    Fails fast on import error -- a missing handler is a NAV error.
    """
    global _discovered
    if _discovered:
        return
    _discovered = True

    handlers_dir = os.path.dirname(__file__)
    skip = {"__init__.py", "_registry.py"}

    for filename in sorted(os.listdir(handlers_dir)):
        if not filename.endswith(".py") or filename in skip:
            continue
        module_name = f"handlers.{filename[:-3]}"
        importlib.import_module(module_name)
