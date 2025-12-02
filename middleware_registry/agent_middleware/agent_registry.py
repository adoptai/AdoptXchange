# middleware_registry/agent_middleware/agent_registry.py
"""Registry for building LangChain middleware instances from MiddlewareSpec.

This module provides factories that create actual LangChain middleware instances
from MiddlewareSpec configurations. User params are merged with defaults.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple, Callable
import logging

from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    LLMToolSelectorMiddleware,
    SummarizationMiddleware,
    ToolRetryMiddleware,
    ToolCallLimitMiddleware,
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
    ModelRetryMiddleware,
    TodoListMiddleware,
)
from langgraph.checkpoint.memory import InMemorySaver

from middleware_registry.middleware_registry import MiddlewareSpec, merge_with_defaults
from middleware_registry.custom_middleware import (
    CUSTOM_MIDDLEWARE_FACTORIES,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Middleware Factory Functions
# Each factory takes merged params (user + defaults) and returns middleware
# ============================================================================

def build_tool_retry(params: Dict[str, Any]):
    """Build ToolRetryMiddleware.
    
    Params: max_retries, backoff_factor, initial_delay, max_delay, jitter, on_failure
    """
    return ToolRetryMiddleware(
        max_retries=params.get("max_retries"),
        backoff_factor=params.get("backoff_factor"),
        initial_delay=params.get("initial_delay"),
        max_delay=params.get("max_delay"),
        jitter=params.get("jitter"),
        on_failure=params.get("on_failure"),
    )


def build_tool_call_limit(params: Dict[str, Any]):
    """Build ToolCallLimitMiddleware.
    
    Params: thread_limit, run_limit, exit_behavior, tool_name (optional)
    """
    kwargs = {
        "thread_limit": params.get("thread_limit"),
        "run_limit": params.get("run_limit"),
        "exit_behavior": params.get("exit_behavior"),
    }
    if "tool_name" in params:
        kwargs["tool_name"] = params["tool_name"]
    return ToolCallLimitMiddleware(**kwargs)


def build_llm_tool_selector(params: Dict[str, Any]):
    """Build LLMToolSelectorMiddleware.
    
    Params: model (required or default), max_tools, always_include
    """
    return LLMToolSelectorMiddleware(
        model=params.get("model"),
        max_tools=params.get("max_tools"),
        always_include=params.get("always_include"),
    )


def build_summarization_middleware(params: Dict[str, Any]):
    """Build SummarizationMiddleware.
    
    Params: model, trigger, keep
    """
    return SummarizationMiddleware(
        model=params.get("model"),
        trigger=params.get("trigger"),
        keep=params.get("keep"),
    )


def build_human_in_the_loop(params: Dict[str, Any]):
    """Build HumanInTheLoopMiddleware.
    
    Params: interrupt_on
    """
    return HumanInTheLoopMiddleware(
        interrupt_on=params.get("interrupt_on", {}),
    )


def build_model_call_limit(params: Dict[str, Any]):
    """Build ModelCallLimitMiddleware.
    
    Params: thread_limit, run_limit, exit_behavior
    """
    return ModelCallLimitMiddleware(
        thread_limit=params.get("thread_limit"),
        run_limit=params.get("run_limit"),
        exit_behavior=params.get("exit_behavior"),
    )


def build_model_fallback(params: Dict[str, Any]):
    """Build ModelFallbackMiddleware.
    
    Params: fallback_models (list of model strings or model instances)
    """
    fallback_models = params.get("fallback_models", [])
    return ModelFallbackMiddleware(*fallback_models)


def build_model_retry(params: Dict[str, Any]):
    """Build ModelRetryMiddleware.
    
    Params: max_retries, backoff_factor, initial_delay
    """
    return ModelRetryMiddleware(
        max_retries=params.get("max_retries"),
        backoff_factor=params.get("backoff_factor"),
        initial_delay=params.get("initial_delay"),
    )


def build_todo_list(params: Dict[str, Any]):
    """Build TodoListMiddleware.
    
    Params: (none required)
    """
    return TodoListMiddleware()


# ============================================================================
# Middleware Registry - Maps spec keys to factory functions
# ============================================================================

# Built-in LangChain middleware factories
BUILTIN_MIDDLEWARE_FACTORIES: Dict[str, Callable[[Dict[str, Any]], Any]] = {
    "tool_retry": build_tool_retry,
    "tool_call_limit": build_tool_call_limit,
    "llm_tool_selector": build_llm_tool_selector,
    "summarization_middleware": build_summarization_middleware,
    "human_in_the_loop": build_human_in_the_loop,
    "model_call_limit": build_model_call_limit,
    "model_fallback": build_model_fallback,
    "model_retry": build_model_retry,
    "todo_list": build_todo_list,
}

# Combined registry: built-in + custom middleware
MIDDLEWARE_FACTORIES: Dict[str, Callable[[Dict[str, Any]], Any]] = {
    **BUILTIN_MIDDLEWARE_FACTORIES,
    **CUSTOM_MIDDLEWARE_FACTORIES,
}


def build_middleware_from_spec(spec: MiddlewareSpec) -> Any:
    """Build a single middleware instance from a MiddlewareSpec.
    
    User params are merged with defaults - user params override defaults.
    
    Args:
        spec: MiddlewareSpec with key and optional params
        
    Returns:
        LangChain middleware instance
        
    Raises:
        ValueError: If middleware key is unknown
    """
    factory = MIDDLEWARE_FACTORIES.get(spec.key)
    if not factory:
        raise ValueError(
            f"Unknown middleware key: '{spec.key}'. "
            f"Available: {list(MIDDLEWARE_FACTORIES.keys())}"
        )
    
    # Merge user params with defaults
    merged_params = merge_with_defaults(spec.key, spec.params)
    
    logger.debug(
        "Building middleware '%s' with params: %s",
        spec.key,
        merged_params,
    )
    
    return factory(merged_params)


def build_middleware_list(
    specs: List[MiddlewareSpec],
) -> Tuple[List[Any], Any]:
    """Build a list of middleware instances from specs.
    
    Args:
        specs: List of MiddlewareSpec to build
        
    Returns:
        Tuple of (middleware_list, checkpointer).
        Checkpointer is InMemorySaver if HITL middleware is used, else None.
    """
    middleware: List[Any] = []
    uses_hitl = False
    
    for spec in specs:
        instance = build_middleware_from_spec(spec)
        middleware.append(instance)
        
        if isinstance(instance, HumanInTheLoopMiddleware):
            uses_hitl = True
    
    # HITL requires a checkpointer
    checkpointer: Any = None
    if uses_hitl:
        checkpointer = InMemorySaver()
        logger.info("HumanInTheLoopMiddleware detected, adding InMemorySaver checkpointer")
    
    return middleware, checkpointer


def list_available_middleware() -> List[str]:
    """List all available middleware keys."""
    return list(MIDDLEWARE_FACTORIES.keys())