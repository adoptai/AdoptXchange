# middleware_registry/middleware_registry/__init__.py
"""Shared middleware types and specs with default configurations."""
from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class MiddlewareSpec:
    """Specification for a middleware component.
    
    Args:
        key: The middleware identifier (e.g., "tool_retry", "human_in_the_loop", "llm_tool_selector")
        params: Configuration parameters for the middleware. Missing params use defaults.
    
    Example:
        MiddlewareSpec("tool_retry", {"max_retries": 3})
        MiddlewareSpec("llm_tool_selector", {"model": openai_model, "max_tools": 5})
        MiddlewareSpec("summarization_middleware", {})  # Uses all defaults
    """
    key: str
    params: Dict[str, Any] = field(default_factory=dict)


# Default configurations for all supported middleware
# These match the LangChain middleware constructor defaults
DEFAULT_CONFIGS: Dict[str, Dict[str, Any]] = {
    # =========================================================================
    # Built-in LangChain Middleware
    # =========================================================================
    
    # ToolRetryMiddleware defaults
    "tool_retry": {
        "max_retries": 3,
        "backoff_factor": 2.0,
        "initial_delay": 1.0,
        "max_delay": 60.0,
        "jitter": True,
        "on_failure": "return_message",
    },
    # ToolCallLimitMiddleware defaults
    "tool_call_limit": {
        "thread_limit": 20,
        "run_limit": 10,
        "exit_behavior": "continue",
    },
    # LLMToolSelectorMiddleware defaults
    "llm_tool_selector": {
        "model": "gpt-4o-mini",
        "max_tools": 3,
        "always_include": [],
    },
    # SummarizationMiddleware defaults
    "summarization_middleware": {
        "model": "gpt-4o-mini",
        "trigger": ("tokens", 4000),
        "keep": ("messages", 20),
    },
    # HumanInTheLoopMiddleware defaults
    "human_in_the_loop": {
        "interrupt_on": {},
    },
    # ModelCallLimitMiddleware defaults
    "model_call_limit": {
        "thread_limit": 10,
        "run_limit": 5,
        "exit_behavior": "end",
    },
    # ModelFallbackMiddleware defaults
    "model_fallback": {
        "fallback_models": ["gpt-4o-mini", "claude-3-5-sonnet-20241022"],
    },
    # ModelRetryMiddleware defaults
    "model_retry": {
        "max_retries": 3,
        "backoff_factor": 2.0,
        "initial_delay": 1.0,
    },
    # TodoListMiddleware defaults
    "todo_list": {},
    
    # =========================================================================
    # Custom Middleware (from custom_middleware.py)
    # =========================================================================
    
    # ToolLoggingMiddleware defaults
    "tool_log": {
        "verbose": True,
        "log_args": True,
    },
    # CachingMiddleware defaults
    "cache": {
        "ttl_seconds": None,
        "max_size": 1000,
    },
    # ToolAccessControlMiddleware defaults
    "tool_access_control": {
        "allowed_tools": [],
        "block_message": None,
    },
    # RateLimitMiddleware defaults
    "rate_limit": {
        "max_calls_per_minute": 60,
        "max_calls_per_tool": 20,
    },
}


def get_default_config(key: str) -> Dict[str, Any]:
    """Get default configuration for a middleware key."""
    return DEFAULT_CONFIGS.get(key, {}).copy()


def merge_with_defaults(key: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Merge user params with defaults. User params override defaults."""
    defaults = get_default_config(key)
    defaults.update(params)
    return defaults