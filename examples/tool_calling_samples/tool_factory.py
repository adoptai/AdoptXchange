"""Factory for dynamically creating LangChain tools from Adopt capabilities."""

import json
from langchain_core.tools import tool, ToolException
from typing import Dict, Any, List, Callable, Optional, Type
from pydantic import BaseModel, Field, create_model
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


def parse_required_input(input_str: str) -> Dict[str, Dict[str, Any]]:
    """Parse a required_input JSON string into parameter metadata.
    
    Handles strings like: '{"limit": {"min": 25, "max": 100, "default": 50}}'
    
    Args:
        input_str: JSON string containing parameter name and metadata
        
    Returns:
        Dictionary mapping parameter name to its metadata (min, max, default, etc.)
        Returns empty dict if parsing fails
        
    Examples:
        >>> parse_required_input('{"limit": {"min": 25, "max": 100, "default": 50}}')
        {'limit': {'min': 25, 'max': 100, 'default': 50}}
    """
    try:
        parsed = json.loads(input_str)
        if isinstance(parsed, dict):
            return parsed
        return {}
    except (json.JSONDecodeError, TypeError):
        # If it's not valid JSON, it's probably a simple string parameter
        # This is expected for the hybrid format - no warning needed
        return {}


def create_tool_schema(capability: AdoptAction) -> Optional[Type[BaseModel]]:
    """Create a dynamic Pydantic schema for a tool based on its required_inputs.
    
    Parses required_inputs and generates a Pydantic model. Supports two formats:
    1. Structured JSON: '{"limit": {"min": 25, "max": 100, "default": 50}}'
    2. Simple strings: 'keyword_id' (treated as required string parameter)
    
    Args:
        capability: The Adopt action to create a schema for
        
    Returns:
        A Pydantic BaseModel class with fields for each required input,
        or None if there are no required inputs
        
    Examples:
        For capability with required_inputs:
        ['{"limit": {"min": 25, "max": 100, "default": 50}}']
        
        Generates equivalent to:
        class ToolSchema(BaseModel):
            limit: int = Field(default=50, ge=25, le=100, description="limit parameter")
    """
    if not capability.required_inputs:
        return None
    
    field_definitions = {}
    
    for input_str in capability.required_inputs:
        param_dict = parse_required_input(input_str)
        
        if param_dict:
            # Structured JSON format
            for param_name, param_meta in param_dict.items():
                # Extract metadata
                default_value = param_meta.get('default')
                min_value = param_meta.get('min')
                max_value = param_meta.get('max')
                description = param_meta.get('description', f"{param_name} parameter")
                
                # Infer type from default value
                if default_value is not None:
                    param_type = type(default_value)
                elif min_value is not None:
                    param_type = type(min_value)
                elif max_value is not None:
                    param_type = type(max_value)
                else:
                    # Default to string if we can't infer
                    param_type = str
                
                # Build Field constraints
                field_kwargs = {'description': description}
                
                if min_value is not None and param_type in (int, float):
                    field_kwargs['ge'] = min_value  # greater than or equal
                if max_value is not None and param_type in (int, float):
                    field_kwargs['le'] = max_value  # less than or equal
                
                # Handle default value
                if default_value is not None:
                    field_kwargs['default'] = default_value
                # If no default, field is required - Pydantic handles this automatically
                
                # Create the field
                field_definitions[param_name] = (param_type, Field(**field_kwargs))
        else:
            # Simple string format - treat as required string parameter
            param_name = input_str.strip()
            if param_name:  # Ensure it's not empty
                field_definitions[param_name] = (
                    str, 
                    Field(description=f"{param_name} parameter")
                )
    
    if not field_definitions:
        return None
    
    # Create dynamic Pydantic model
    schema_name = f"{sanitize_tool_name(capability.title)}_schema"
    return create_model(
        schema_name,
        **field_definitions
    )


def create_adopt_tool(capability: AdoptAction, profile: Dict[str, Any]) -> Callable:
    """Dynamically create a LangChain tool for an Adopt capability.
    
    This function creates a closure that captures the capability and profile,
    and returns a LangChain @tool decorated function that can be bound to
    a language model. If the capability has required_inputs with metadata,
    a Pydantic schema is automatically generated for validation.
    
    Args:
        capability: The Adopt action to create a tool for
        profile: The adopt profile configuration containing authentication
        
    Returns:
        A LangChain tool function that can be bound to a model
    """
    tool_name = sanitize_tool_name(capability.title)
    tool_description = capability.description
    
    # Create dynamic Pydantic schema if we have required inputs with metadata
    tool_schema = create_tool_schema(capability)
    
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
            
            # Extract workflow_params from the validated input
            # Pydantic has already validated these if we have a schema
            workflow_params = {}
            if capability.required_inputs:
                # Parse required_inputs to get parameter names
                param_names = set()
                for input_str in capability.required_inputs:
                    param_dict = parse_required_input(input_str)
                    param_names.update(param_dict.keys())
                
                # Extract all parameters that match required input names
                for param_name in param_names:
                    if param_name in actual_kwargs:
                        workflow_params[param_name] = actual_kwargs[param_name]
                
                # Use generic message if only params are provided
                if not user_input:
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
    
    # Apply the tool decorator with optional schema
    if tool_schema:
        adopt_tool = tool(args_schema=tool_schema)(tool_func)
    else:
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

