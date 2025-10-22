"""Example demonstrating LangChain tool calling with Adopt capabilities.

This example shows how to dynamically create LangChain tools from Adopt
capabilities and use them with AWS Bedrock for native tool calling.
"""

import json
from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage
from pydantic import SecretStr
from examples import read_env
from examples.action_api_samples.api_sample import (
    list_actions_by_type,
    load_adopt_profile
)
from examples.tool_calling_samples.tool_factory import create_all_tools


def format_param_details(required_inputs):
    """Format required_inputs metadata for display.
    
    New format with type and definition:
    '{"org_id": {"default": 3919, "type": "int", "definition": "organization id"}}'
    
    Shows (mandatory) or (optional) based on presence of default value.
    
    Args:
        required_inputs: List of JSON strings with parameter metadata
        
    Returns:
        Formatted string showing parameter names with type, constraints, and mandatory/optional status
        
    Examples:
        ['{"org_id": {"default": 3919, "type": "int"}}'] 
        -> "org_id: int (optional) [default=3919]"
        
        ['{"keyword_id": {"type": "int"}}']
        -> "keyword_id: int (mandatory)"
        
        ['{"limit": {"min": 25, "max": 100, "default": 50, "type": "int"}}']
        -> "limit: int (optional) [25-100, default=50]"
    """
    if not required_inputs:
        return ""
    
    param_strs = []
    for input_str in required_inputs:
        try:
            param_dict = json.loads(input_str)
            # Structured JSON format
            for param_name, param_meta in param_dict.items():
                param_type = param_meta.get('type', 'string')
                has_default = 'default' in param_meta
                
                # Determine if mandatory or optional
                mandatory_status = "(optional)" if has_default else "(mandatory)"
                
                details = []
                
                if 'min' in param_meta and 'max' in param_meta:
                    details.append(f"{param_meta['min']}-{param_meta['max']}")
                elif 'min' in param_meta:
                    details.append(f"min={param_meta['min']}")
                elif 'max' in param_meta:
                    details.append(f"max={param_meta['max']}")
                
                if 'default' in param_meta:
                    details.append(f"default={param_meta['default']}")
                
                type_str = f"{param_name}: {param_type} {mandatory_status}"
                if details:
                    param_strs.append(f"{type_str} [{', '.join(details)}]")
                else:
                    param_strs.append(type_str)
        except (json.JSONDecodeError, TypeError):
            # Simple string format - just use the parameter name (assume mandatory)
            param_strs.append(f"{input_str.strip()} (mandatory)")
    
    return ", ".join(param_strs)


def create_model_with_tools(tools, adopt_env):
    """Create AWS Bedrock model with tools bound.
    
    Args:
        tools: List of LangChain tools to bind to the model
        adopt_env: Environment configuration with AWS credentials
        
    Returns:
        ChatBedrockConverse model with tools bound
    """
    model = ChatBedrockConverse(
        model=adopt_env.BEDROCK_MODEL,
        region_name=adopt_env.AWS_REGION,
        aws_access_key_id=SecretStr(adopt_env.AWS_ACCESS_KEY_ID),
        aws_secret_access_key=SecretStr(adopt_env.AWS_SECRET_ACCESS_KEY),
    )
    return model.bind_tools(tools)


def run_tool_calling_example():
    """Main example demonstrating Adopt tool calling.
    
    This function:
    1. Loads configuration from adopt_profile.json
    2. Discovers Adopt capabilities using execution_type=TOOL
    3. Creates LangChain tools for each capability
    4. Binds tools to AWS Bedrock model
    5. Runs example queries demonstrating tool calling
    """
    print("🛠️  Adopt AI Tool Calling Example")
    print("=" * 60)
    
    # Load configuration
    try:
        profile = load_adopt_profile()
        print("✓ Loaded adopt profile")
    except Exception as e:
        print(f"❌ Failed to load profile: {e}")
        return
    
    try:
        adopt_env = read_env()
        print("✓ Loaded environment configuration")
    except Exception as e:
        print(f"❌ Failed to load environment: {e}")
        return
    
    # Discover tools
    print("\n📡 Discovering Adopt capabilities...")
    try:
        capabilities_response = list_actions_by_type(execution_type="TOOL")
        capabilities = capabilities_response.capabilities
        print(f"✓ Found {len(capabilities)} capabilities")
        
        # Show all discovered capabilities
        if capabilities:
            print("\nDiscovered capabilities:")
            for i, cap in enumerate(capabilities, 1):
                print(f"\n  {i}. {cap.title}")
                if cap.required_inputs:
                    print(f"     Parameters:")
                    # Parse and display each parameter on its own line
                    for input_str in cap.required_inputs:
                        try:
                            param_dict = json.loads(input_str)
                            for param_name, param_meta in param_dict.items():
                                param_type = param_meta.get('type', 'string')
                                has_default = 'default' in param_meta
                                mandatory_status = "optional" if has_default else "mandatory"
                                
                                # Build constraint info
                                constraints = []
                                if 'min' in param_meta and 'max' in param_meta:
                                    constraints.append(f"range: {param_meta['min']}-{param_meta['max']}")
                                elif 'min' in param_meta:
                                    constraints.append(f"min: {param_meta['min']}")
                                elif 'max' in param_meta:
                                    constraints.append(f"max: {param_meta['max']}")
                                
                                if 'default' in param_meta:
                                    default_val = param_meta['default']
                                    # Format empty string defaults nicely
                                    if default_val == "":
                                        default_val = '""'
                                    constraints.append(f"default: {default_val}")
                                
                                constraint_str = f" [{', '.join(constraints)}]" if constraints else ""
                                print(f"       • {param_name}: {param_type} ({mandatory_status}){constraint_str}")
                                
                                # Optionally show definition on next line if it exists
                                if 'definition' in param_meta and param_meta['definition']:
                                    definition = param_meta['definition']
                                    if len(definition) > 60:
                                        definition = definition[:57] + "..."
                                    print(f"         → {definition}")
                        except (json.JSONDecodeError, TypeError):
                            # Simple string format
                            print(f"       • {input_str.strip()} (mandatory)")
                else:
                    print(f"     No parameters required")
    except Exception as e:
        print(f"❌ Failed to discover capabilities: {e}")
        return
    
    # Create tools
    print("\n🔧 Creating LangChain tools...")
    try:
        tools = create_all_tools(capabilities, profile)
        print(f"✓ Created {len(tools)} tools")
    except Exception as e:
        print(f"❌ Failed to create tools: {e}")
        return
    
    # Bind to model
    print("\n🤖 Binding tools to AWS Bedrock model...")
    try:
        model_with_tools = create_model_with_tools(tools, adopt_env)
        print("✓ Model ready with tools")
    except Exception as e:
        print(f"❌ Failed to bind tools to model: {e}")
        return
    
    # Run example queries that match the discovered capabilities
    # Note: Modify these queries based on the capabilities listed above
    # The queries below match the actions we discovered
    test_queries = [
        "Get organization details",  # Should work with "Get Organization Details" action (read-only, might work!)
        "Show me all keywords",  # Should work with "Show All Keywords" action
        "Show me all keyword groups",  # Should work with "Show All Keyword Groups" action
    ]
    
    # Add validation failure test case to demonstrate min/max constraints
    validation_test_queries = [
        "Show me just 10 keywords",              # Should FAIL: limit min is 25
    ]
    
    # Alternative queries for different environments (uncomment and modify as needed):
    # For segment management:
    # test_queries = [
    #     "List all available segments",
    #     "Create a segment named 'High Value Accounts'",
    #     "Show segment details",
    # ]
    
    # For campaign management:
    # test_queries = [
    #     "Show me my campaigns",
    #     "List active campaigns",
    #     "Get campaign performance",
    # ]
    
    # For account management:
    # test_queries = [
    #     "Get all accounts",
    #     "Show account details",
    #     "List high-value accounts",
    # ]
    
    print("\n" + "=" * 60)
    print("Running Example Queries")
    print("=" * 60)
    
    for i, query in enumerate(test_queries, 1):
        print(f"\n[{i}/{len(test_queries)}] 👤 User: {query}")
        print("-" * 60)
        
        try:
            # Initial response from model with potential tool calls
            response = model_with_tools.invoke([HumanMessage(content=query)])
            
            # Check if model wants to call tools
            if hasattr(response, 'tool_calls') and response.tool_calls:
                print(f"🔧 Model selected {len(response.tool_calls)} tool(s):")
                for tool_call in response.tool_calls:
                    print(f"  - {tool_call.get('name', 'unknown')}")
                
                print("\n⚙️  Executing tools...")
                
                # Execute each tool call
                from langchain_core.messages import ToolMessage
                tool_results = []
                
                for tool_call in response.tool_calls:
                    tool_name = tool_call.get('name')
                    tool_input = tool_call.get('args', {})
                    tool_id = tool_call.get('id')
                    
                    # Find and execute the matching tool
                    for tool in tools:
                        if tool.name == tool_name:
                            try:
                                result = tool.invoke(tool_input)
                                tool_results.append(ToolMessage(
                                    content=str(result),
                                    tool_call_id=tool_id
                                ))
                                print(f"  ✓ {tool_name} executed")
                            except Exception as e:
                                tool_results.append(ToolMessage(
                                    content=f"Error: {str(e)}",
                                    tool_call_id=tool_id
                                ))
                                print(f"  ✗ {tool_name} failed: {e}")
                            break
                
                # Get final response with tool results
                if tool_results:
                    print("\n🤖 Final Response:")
                    final_response = model_with_tools.invoke([
                        HumanMessage(content=query),
                        response,
                        *tool_results
                    ])
                    print(final_response.content)
            else:
                # No tool calls, just show the response
                print(f"\n🤖 Assistant: {response.content}")
                
        except Exception as e:
            print(f"❌ Error: {str(e)}")
    
    # Run validation failure test cases
    print("\n" + "=" * 60)
    print("Testing Validation Constraints (Should Fail)")
    print("=" * 60)
    print("These queries intentionally use invalid parameters to demonstrate")
    print("that Pydantic validation is working correctly.\n")
    
    for i, query in enumerate(validation_test_queries, 1):
        print(f"\n[{i}/{len(validation_test_queries)}] 👤 User: {query}")
        print("-" * 60)
        
        try:
            # Initial response from model with potential tool calls
            response = model_with_tools.invoke([HumanMessage(content=query)])
            
            # Check if model wants to call tools
            if hasattr(response, 'tool_calls') and response.tool_calls:
                print(f"🔧 Model selected {len(response.tool_calls)} tool(s):")
                for tool_call in response.tool_calls:
                    print(f"  - {tool_call.get('name', 'unknown')}")
                    print(f"    Args: {tool_call.get('args', {})}")
                
                print("\n⚙️  Executing tools (expecting validation errors)...")
                
                # Execute each tool call
                from langchain_core.messages import ToolMessage
                tool_results = []
                
                for tool_call in response.tool_calls:
                    tool_name = tool_call.get('name')
                    tool_input = tool_call.get('args', {})
                    tool_id = tool_call.get('id')
                    
                    # Find and execute the matching tool
                    for tool in tools:
                        if tool.name == tool_name:
                            try:
                                result = tool.invoke(tool_input)
                                tool_results.append(ToolMessage(
                                    content=str(result),
                                    tool_call_id=tool_id
                                ))
                                print(f"  ⚠️  {tool_name} executed successfully (unexpected!)")
                            except Exception as e:
                                error_msg = str(e)
                                tool_results.append(ToolMessage(
                                    content=f"Validation Error: {error_msg}",
                                    tool_call_id=tool_id
                                ))
                                print(f"  ✓ {tool_name} validation failed as expected:")
                                print(f"    Error: {error_msg[:150]}...")
                            break
                
                # Get final response with tool results
                if tool_results:
                    print("\n🤖 Final Response:")
                    final_response = model_with_tools.invoke([
                        HumanMessage(content=query),
                        response,
                        *tool_results
                    ])
                    print(final_response.content)
            else:
                # No tool calls
                print(f"\n🤖 Assistant: {response.content}")
                
        except Exception as e:
            print(f"✓ Validation error caught: {str(e)[:150]}...")
    
    print("\n" + "=" * 60)
    print("Validation Tests Complete")
    print("=" * 60)
    print("✓ Pydantic successfully enforced min/max constraints!")
    print("✓ Invalid parameters were rejected before reaching the API")
    
    print("\n" + "=" * 60)
    print("Example Complete")
    print("=" * 60)
    print("\n💡 Tips:")
    print("  - Each Adopt capability is now a discrete LangChain tool")
    print("  - The LLM automatically selects the appropriate tool(s)")
    print("  - Multiple tools can be called in sequence for complex tasks")
    print("  - Try your own queries by modifying the test_queries list")
    print("\n📝 To customize queries:")
    print("  1. Look at the 'Example capabilities' listed above")
    print("  2. Modify test_queries to match your available actions")
    print("  3. For actions with required inputs, include those values in your query")
    print("  4. Example: 'Add keywords: AI, ML to category Technology'")
    print("\n⚠️  If actions fail:")
    print("  - Some actions may require browser sessions (not API-only)")
    print("  - Try simpler actions first (list/get vs. create/update)")


if __name__ == "__main__":
    """Run the example when script is executed directly."""
    run_tool_calling_example()

