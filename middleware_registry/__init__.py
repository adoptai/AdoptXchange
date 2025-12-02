# middleware_registry/__init__.py
"""Middleware Registry - Lego-block style middleware selection for agents.

Usage:
    from middleware_registry import MiddlewareSpec
    from middleware_registry.agent_factory import create_adopt_agent
    
    agent = await create_adopt_agent(
        model=bedrock_model,
        adopt_client=adopt_client,
        profile=profile,
        capability_keys=["show_all_keywords", "add_new_keywords"],
        middleware=[
            MiddlewareSpec("tool_retry", {"max_retries": 3}),
            MiddlewareSpec("llm_tool_selector", {"model": openai_model, "max_tools": 5}),
            MiddlewareSpec("human_in_the_loop", {"interrupt_on": {"add_new_keywords": True}}),
        ],
    )
"""

from middleware_registry.middleware_registry import (
    MiddlewareSpec,
    get_default_config,
    merge_with_defaults,
    DEFAULT_CONFIGS,
)
from middleware_registry.agent_middleware.agent_registry import (
    build_middleware_list,
    build_middleware_from_spec,
    list_available_middleware,
    MIDDLEWARE_FACTORIES,
)

__all__ = [
    # Core types
    "MiddlewareSpec",
    "get_default_config",
    "merge_with_defaults",
    "DEFAULT_CONFIGS",
    # Middleware building
    "build_middleware_list",
    "build_middleware_from_spec",
    "list_available_middleware",
    "MIDDLEWARE_FACTORIES",
]