"""Factory for dynamically creating LangChain tools from Adopt capabilities."""

from langchain_core.tools import tool, ToolException
from typing import Dict, Any, List, Callable
from examples.models import AdoptAction
from examples.action_api_samples.api_sample import run_action_by_id


def sanitize_tool_name(title: str) -> str:
    """Convert action title to valid Python identifier.
    
    Examples:
        'Create a New Segment' -> 'create_a_new_segment'
        'View Campaigns with Filters' -> 'view_campaigns_with_filters'
    
    Args:
        title: The action title to sanitize
        
    Returns:
        A valid Python identifier suitable for use as a tool name
    """
    name = title.lower()
    # Replace spaces and hyphens with underscores
    name = name.replace(' ', '_').replace('-', '_')
    # Remove any non-alphanumeric characters except underscores
    name = ''.join(c for c in name if c.isalnum() or c == '_')
    # Ensure it doesn't start with a number
    if name and name[0].isdigit():
        name = 'tool_' + name
    return name


def create_adopt_tool(capability: AdoptAction, profile: Dict[str, Any]) -> Callable:
    """Dynamically create a LangChain tool for an Adopt capability.
    
    This function creates a closure that captures the capability and profile,
    and returns a LangChain @tool decorated function that can be bound to
    a language model.
    
    Args:
        capability: The Adopt action to create a tool for
        profile: The adopt profile configuration containing authentication
        
    Returns:
        A LangChain tool function that can be bound to a model
    """
    tool_name = sanitize_tool_name(capability.title)
    tool_description = capability.description
    
    # Add required inputs to description if any
    if capability.required_inputs:
        inputs_desc = ", ".join(capability.required_inputs)
        tool_description += f"\n\nRequired inputs: {inputs_desc}"
    
    # Create the inner function that will be decorated
    # Use **kwargs to accept any parameters the LLM might provide
    def tool_func(**kwargs) -> str:
        """Execute this Adopt action with the provided input.
        
        Args:
            **kwargs: Parameters for the action. For actions with required_inputs,
                     pass them as named parameters. Otherwise, pass 'user_input'.
            
        Returns:
            The result from executing the Adopt action
        """
        try:
            # Handle nested kwargs structure (LangChain sometimes nests params in 'kwargs')
            if 'kwargs' in kwargs and isinstance(kwargs['kwargs'], dict):
                actual_kwargs = kwargs['kwargs']
            else:
                actual_kwargs = kwargs
            
            # Extract user_input and other params
            user_input = actual_kwargs.get('user_input', '')
            
            # For actions with required_inputs, extract them as workflow_params
            workflow_params = {}
            if capability.required_inputs:
                for req_input in capability.required_inputs:
                    if req_input in actual_kwargs:
                        workflow_params[req_input] = actual_kwargs[req_input]
                
                # If no workflow params were found, try to use user_input as the message
                if not workflow_params and user_input:
                    # Let the message content be processed by Adopt
                    pass
                elif not user_input:
                    # Use a generic message if only params are provided
                    user_input = f"Execute {capability.title}"
            else:
                # For actions without required inputs, just use user_input from actual_kwargs
                if not user_input:
                    # Try to construct from all actual_kwargs
                    user_input = " ".join(str(v) for v in actual_kwargs.values() if v)
                if not user_input:
                    # Use the action description as a more natural query
                    user_input = capability.description or capability.title
            
            result = run_action_by_id(
                action_id=capability.id,
                user_input=user_input,
                profile=profile,
                workflow_params=workflow_params if workflow_params else None
            )
            return result
        except Exception as e:
            raise ToolException(f"Failed to execute {capability.title}: {str(e)}")
    
    # Set the function name and docstring before decorating
    tool_func.__name__ = tool_name
    tool_func.__doc__ = tool_description
    
    # Apply the tool decorator
    adopt_tool = tool(tool_func)
    
    return adopt_tool


def create_all_tools(
    capabilities: List[AdoptAction],
    profile: Dict[str, Any]
) -> List[Callable]:
    """Create LangChain tools for all Adopt capabilities.
    
    This function takes a list of Adopt capabilities and creates a LangChain
    tool for each one. The resulting tools can be bound to any LangChain
    model that supports tool calling.
    
    Args:
        capabilities: List of Adopt actions to create tools for
        profile: The adopt profile configuration
        
    Returns:
        List of LangChain tool functions ready to be bound to a model
    """
    tools = []
    
    for capability in capabilities:
        tool_func = create_adopt_tool(capability, profile)
        tools.append(tool_func)
    
    return tools

