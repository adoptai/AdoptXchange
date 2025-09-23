"""LangGraph agent that uses Adopt API functions for capability checking and action execution."""

import os
import json
from typing import TypedDict, Annotated, Sequence, Literal, Any
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_aws import ChatBedrockConverse
from langgraph.graph import StateGraph, END, add_messages
from examples import read_env, AdoptEnv
from examples.action_api_samples.api_sample import list_actions, run_action
from pydantic import SecretStr

CAPABILITY_CHECK_PROMPT = """
You are an AI assistant that determines whether a set of available capabilities can handle a user's request.

Available Adopt capabilities:
{capabilities_text}

Conversation history: "{conversation_history}"

Based on the available capabilities above, can any of them handle the user's request in the last message? 

Respond with exactly "YES" if the request can be handled by one or more of the available capabilities, or "NO" if it cannot be handled.

Consider:
- The intent and purpose of the conversation history with specific reference to the user's request in the last message
- Whether any of the available capabilities match the request's requirements in the last message
- Be generous in matching - if a capability could potentially help with the request, respond "YES"

"""

class AgentState(TypedDict):
    """State for the LangGraph agent."""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    adopt_capabilities: str
    can_handle_request: bool
    adopt_profile: dict[str, Any]


class GraphConfig(TypedDict):
    """Configuration for the LangGraph agent."""
    adopt_profile_path: str


def get_bedrock_model(adopt_env: AdoptEnv) -> ChatBedrockConverse:
    """Initialize and return a ChatBedrockConverse model."""
    if adopt_env.BEDROCK_MODEL is None:
        raise ValueError("BEDROCK_MODEL is not set")
    if adopt_env.AWS_ACCESS_KEY_ID is None:
        raise ValueError("AWS_ACCESS_KEY_ID is not set")
    if adopt_env.AWS_SECRET_ACCESS_KEY is None:
        raise ValueError("AWS_SECRET_ACCESS_KEY is not set")
    if adopt_env.AWS_REGION is None:
        raise ValueError("AWS_REGION is not set")
    return ChatBedrockConverse(
        model=adopt_env.BEDROCK_MODEL,
        region_name=adopt_env.AWS_REGION,
        aws_access_key_id=SecretStr(adopt_env.AWS_ACCESS_KEY_ID),
        aws_secret_access_key=SecretStr(adopt_env.AWS_SECRET_ACCESS_KEY),
    )


def capability_checker_node(state: AgentState) -> AgentState:
    """
    First node: Check if Adopt can handle the user's request.
    Uses get_list to get capabilities and ChatBedrock to determine if the request can be satisfied.
    """
    print("🔍 Checking if Adopt can handle the request...")
    
    # Get the latest user message
    user_message = state["messages"][-1].content if state["messages"] else "" # type: ignore
    
    try:
        # Get Adopt capabilities
        action_list_response = list_actions()
        capabilities = action_list_response.capabilities
        
        # Format capabilities for the LLM
        capabilities_text = "\n".join([
            f"- {cap.title}: {cap.description}" for cap in capabilities
        ])
        
        # Initialize Bedrock model
        adopt_env = read_env()
        bedrock_model = get_bedrock_model(adopt_env)
        
        # Create prompt to check if capabilities can handle the request
        conversation_history = "\n".join([f"{msg.__class__.__name__}: {str(msg.content)}" for msg in state["messages"]]) # type: ignore
        capability_check_prompt = CAPABILITY_CHECK_PROMPT.format(
            capabilities_text=capabilities_text,
            conversation_history=conversation_history
        )

        # Get response from Bedrock
        response = bedrock_model.invoke([HumanMessage(content=capability_check_prompt)])
        can_handle = response.content.strip().upper() == "YES" # type: ignore
        
        print(f"✅ Capability check result: {'CAN HANDLE' if can_handle else 'CANNOT HANDLE'}")
        
        return {
            **state,
            "adopt_capabilities": capabilities_text,
            "can_handle_request": can_handle
        }
        
    except Exception as e:
        print(f"❌ Error in capability checking: {e}")
        return {
            **state,
            "adopt_capabilities": "Error retrieving capabilities",
            "can_handle_request": False
        }


def action_runner_node(state: AgentState) -> AgentState:
    """
    Second node: Execute the action using Adopt's run_action method.
    Only called if capability_checker determined the request can be handled.
    """
    print("🚀 Running action with Adopt...")
    
    # Get the entire message history for context
    message_history = state["messages"]
    
    # Convert message history to a single command string
    # For simplicity, we'll use the latest user message, but in a real implementation
    # you might want to include more context from the conversation history
    user_message = message_history[-1].content if message_history else "" # type: ignore
    
    try:
        # Load the adopt profile
        adopt_profile = state.get("adopt_profile", {})
        
        # Run the action using Adopt with the full message history
        result = run_action(list(message_history), adopt_profile)  # type: ignore
        
        # Add the result as an AI message
        ai_response = AIMessage(content=result)
        
        print("✅ Action completed successfully")
        
        return {
            **state,
            "messages": [*state["messages"], ai_response]
        }
        
    except Exception as e:
        print(f"❌ Error running action: {e}")
        error_response = AIMessage(content=f"I encountered an error while trying to execute your request: {str(e)}")
        
        return {
            **state,
            "messages": [*state["messages"], error_response]
        }


def should_continue(state: AgentState) -> Literal["run_action", "end"]:
    """
    Determine whether to continue to the action runner or end the workflow.
    """
    if state.get("can_handle_request", False):
        return "run_action"
    else:
        return "end"


def create_adopt_agent(adopt_profile_path: str | None = None) -> StateGraph:  # type: ignore
    """
    Create and configure the Adopt LangGraph agent.
    
    Args:
        adopt_profile_path: Path to the adopt profile JSON file
        
    Returns:
        Compiled StateGraph ready for execution
    """
    # Load adopt profile if path is provided
    adopt_profile = {}
    if adopt_profile_path and os.path.exists(adopt_profile_path):
        try:
            with open(adopt_profile_path, 'r') as f:
                adopt_profile = json.load(f)
            print(f"✅ Loaded adopt profile from: {adopt_profile_path}")
        except Exception as e:
            print(f"⚠️ Warning: Could not load adopt profile: {e}")
            print("Using default profile settings")
    else:
        print("Using default adopt profile settings")
    
    # Create the workflow
    workflow = StateGraph(AgentState, config_schema=GraphConfig)
    
    # Add nodes
    workflow.add_node("capability_checker", capability_checker_node) # type: ignore
    workflow.add_node("action_runner", action_runner_node) # type: ignore
    
    # Set entry point
    workflow.set_entry_point("capability_checker")
    
    # Add conditional edges
    workflow.add_conditional_edges(
        "capability_checker",
        should_continue,
        {
            "run_action": "action_runner",
            "end": END,
        },
    )
    
    # Add edge from action_runner to end
    workflow.add_edge("action_runner", END) # type: ignore
    
    # Compile the workflow
    graph = workflow.compile() # type: ignore
    
    # Store the adopt profile in the graph for later use
    graph.adopt_profile = adopt_profile # type: ignore
    
    return graph # type: ignore


def run_agent_example():
    """
    Example of how to use the Adopt LangGraph agent.
    """
    print("🤖 Adopt LangGraph Agent Example")
    print("=" * 50)
    
    # Create the agent
    agent = create_adopt_agent("examples/adopt_profile.json")
    
    # Example conversation
    test_messages = [
        "List all available actions",
        "Create a new segment called 'Test Segment'",
        "What's the weather like today?",  # This should not be handled by Adopt
    ]
    
    for message in test_messages:
        print(f"\n👤 User: {message}")
        print("-" * 30)
        
        # Run the agent
        result = agent.invoke({  # type: ignore
            "messages": [HumanMessage(content=message)],
            "adopt_capabilities": "",
            "can_handle_request": False,
            "adopt_profile": agent.adopt_profile # type: ignore
        })
        
        # Print the final response
        if result["messages"]:
            final_message = result["messages"][-1] # type: ignore
            if isinstance(final_message, AIMessage):
                print(f"🤖 Agent: {final_message.content}") # type: ignore
            else:
                print(f"🤖 Agent: {final_message.content}") # type: ignore
        
        print("=" * 50)


if __name__ == "__main__":
    """Run the example when script is executed directly."""
    run_agent_example()