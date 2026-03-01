# agent_factory.py
"""Factory function for creating Adopt agents with configurable middleware.

This is the main entry point for creating agents with the middleware registry.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple, Union
import logging

from langchain.agents import create_agent

from middleware_registry.middleware_registry import MiddlewareSpec
from middleware_registry.agent_middleware.agent_registry import build_middleware_list
from capabilities_registry.capability_registry import CapabilityRegistry
from examples.action_api_samples.adopt_client import AdoptClient
from examples.action_api_samples.api_sample import (
    load_adopt_profile
)
from examples.models import ToolsConfig

logger = logging.getLogger(__name__)

async def create_adopt_agents(
    *,
    model,
    adopt_client: AdoptClient,
    tools: ToolsConfig,
    middleware: List[MiddlewareSpec] | None = None,
    system_prompt: str | None = None,
    name: str | None = None,
):
    """Create an Adopt agent with configurable middleware.
    
    This factory function creates a LangChain agent with:
    - Tools from Adopt capabilities (fetched from registry)
    - Middleware stack built from MiddlewareSpec (with defaults merged)
    - Automatic checkpointer when HITL is used
    
    Args:
        model: The LLM model to use for the agent
        adopt_client: The AdoptClient instance for API calls
        tools: Tuple of (capability_keys, profile, execution_type)
            - capability_keys: List of capability keys to load as tools
            - profile: The adopt profile configuration
            - execution_type: Adopt execution type filter (e.g., "TOOL")
        middleware: List of MiddlewareSpec for middleware.
            Each spec's params are merged with defaults.
            
            Built-in middleware:
            - tool_retry: ToolRetryMiddleware
            - tool_call_limit: ToolCallLimitMiddleware  
            - llm_tool_selector: LLMToolSelectorMiddleware
            - summarization_middleware: SummarizationMiddleware
            - human_in_the_loop: HumanInTheLoopMiddleware
            - model_call_limit: ModelCallLimitMiddleware
            - model_fallback: ModelFallbackMiddleware
            - model_retry: ModelRetryMiddleware
            - todo_list: TodoListMiddleware
            
            Custom middleware:
            - cache: CachingMiddleware
            - tool_access_control: ToolAccessControlMiddleware
            - tool_log: ToolLoggingMiddleware
            
        system_prompt: Custom system prompt for the agent
        name: Name for the agent
        
    Returns:
        A configured LangChain agent ready for invocation
        
    Example:
        ```python
        from middleware_registry import MiddlewareSpec
        from agent_factory import create_adopt_agent
        
        agent = await create_adopt_agent(
            model=bedrock_model,
            adopt_client=adopt_client,
            tools=ToolsConfig(
                ["show_all_keywords", "add_new_keywords"],
                profile,
                "TOOL"
            ),
            middleware=[
                MiddlewareSpec("tool_retry", {"max_retries": 3}),
                MiddlewareSpec("tool_call_limit", {"thread_limit": 20, "run_limit": 10}),
                MiddlewareSpec("llm_tool_selector", {"model": openai_model, "max_tools": 5}),
                MiddlewareSpec("cache", {}),
                MiddlewareSpec("tool_access_control", {"allowed_tools": ["show_all_keywords"]}),
            ],
        )
        
        # With empty params - uses all defaults
        agent = await create_adopt_agent(
            model=bedrock_model,
            adopt_client=adopt_client,
            tools=ToolsConfig(["show_all_keywords"], profile, "TOOL"),
            middleware=[
                MiddlewareSpec("llm_tool_selector", {}),  # Uses default model, max_tools=3
            ],
        )
        ```
    """
    # Unpack tools configuration
    capability_keys, execution_type = tools.capability_keys, tools.execution_type
    profile = tools.profile

    
    # Create capability registry and load tools
    registry = CapabilityRegistry(adopt_client)
    
    # Get tools from capabilities
    loaded_tools = await registry.get_tools_for_keys(
        capability_keys=capability_keys,
        profile=profile,
        execution_type=execution_type,
    )
    
    logger.info("Created %d tools for agent from capabilities: %s", len(loaded_tools), capability_keys)
    
    # Build middleware list from specs (empty list if None)
    middleware_list: List[Any] = []
    checkpointer = None
    
    if middleware:
        middleware_list, checkpointer = build_middleware_list(middleware)
        logger.info(
            "Built middleware stack with %d middleware, checkpointer=%s",
            len(middleware_list),
            type(checkpointer).__name__ if checkpointer else None,
        )
    
    # Create the agent with middleware passed directly
    agent = create_agent(
        model=model,
        tools=loaded_tools,
        system_prompt=system_prompt or "You are an Adopt agent. Use tools responsibly.",
        middleware=middleware_list,
        checkpointer=checkpointer,
        name=name,
    )
    
    return agent