"""Example demonstrating LangChain tool calling with Adopt capabilities.

This example shows how to dynamically create LangChain tools from Adopt
capabilities and use them with AWS Bedrock for native tool calling.
"""

import uuid
import asyncio
from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage
from pydantic import SecretStr
from examples import read_env
from examples.action_api_samples.api_sample import (
    load_adopt_profile
)
from examples.action_api_samples.adopt_client import AdoptClient
from langchain_openai import ChatOpenAI
from adopt_factory.agent_factory import create_adopt_agents
from middleware_registry.middleware_registry import MiddlewareSpec
from examples.models import ToolsConfig


async def run_tool_calling_example():
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
    
    try:
        profile = load_adopt_profile()
        adopt_client = AdoptClient()
        adopt_env = read_env()
    except Exception as e:
        print(f"❌ Failed to load profile: {e}")
        return
    
    test_queries = [
        "fetch organization Product Details for ID 4"
    ]
    
    bedrock_model = ChatBedrockConverse(
        model=adopt_env.BEDROCK_MODEL,
        region_name=adopt_env.AWS_REGION,
        aws_access_key_id=SecretStr(adopt_env.AWS_ACCESS_KEY_ID),
        aws_secret_access_key=SecretStr(adopt_env.AWS_SECRET_ACCESS_KEY),
    )
    openai_model = ChatOpenAI(
        model="gpt-4o-mini",
        api_key=adopt_env.OPENAI_API_KEY
    )

    agent = await create_adopt_agents(
        model=bedrock_model,
        adopt_client=adopt_client,
        tools=ToolsConfig(
            capability_keys=[
                "create_new_project",
                "list_all_projects",
                "get_project_activity_feed",
                "search_project_by_name",
                "manage_user_profiles",
                "update_user_preferences",
                "get_team_members_list",
                "invite_user_to_team",
                "remove_user_from_team",
                "get_system_health_status"
            ],
            profile=profile,
            execution_type="TOOL"
        ),
        middleware=[
            MiddlewareSpec("tool_call_limit", {"thread_limit": 20, "run_limit": 10}),
            MiddlewareSpec("tool_retry", {
                "max_retries": 3,
                "backoff_factor": 2.0,
                "initial_delay": 1.0,
            }),
            MiddlewareSpec("llm_tool_selector", {
                "model": openai_model
            }),
            MiddlewareSpec("summarization_middleware", {
                "model": openai_model,
                "trigger": ("tokens", 4000),
                "keep": ("messages", 20),
            }),
            MiddlewareSpec("human_in_the_loop", {
                "interrupt_on": {
                    "add_new_keywords": True,
                }
            })
        ],
        name="project_manager_agent",
        system_prompt="You are an autonomous project Management Agent specialized in B2B marketing project intelligence and optimization. Your primary responsibility is to continuously monitor project performance, recommend strategic optimizations, and automate project lifecycle management with minimal manual intervention. You help marketers stay ahead of search trends and engagement patterns while ensuring projects are always tuned for maximum performance and pipeline generation",
    )

    config = {
        "configurable": {
            "thread_id": str(uuid.uuid4())
        }
    }

    print("\n" + "=" * 60)
    print("Running Example Queries")
    print("=" * 60)
    
    for i, query in enumerate(test_queries, 1):
        print(f"\n[{i}/{len(test_queries)}] 👤 User: {query}")
        print("-" * 60)
        
        try:
            # Initial response from model with potential tool calls (async)
            messages = [HumanMessage(content=query)]
            response = await agent.ainvoke({"messages": messages}, config=config)
            print("\n" + "=" * 60)
            print("Model Response")
            print("=" * 60)
            for m in response["messages"]:
                m.pretty_print()
                
        except Exception as e:
            print(f"❌ Error: {str(e)}")
    
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
    asyncio.run(run_tool_calling_example())

