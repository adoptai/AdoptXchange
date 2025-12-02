# middleware_registry/agent_middleware/__init__.py
"""Agent middleware package - re-exports from middleware_registry."""
from middleware_registry.middleware_registry import (
    MiddlewareSpec,
    get_default_config,
    merge_with_defaults,
)

__all__ = ["MiddlewareSpec", "get_default_config", "merge_with_defaults"]