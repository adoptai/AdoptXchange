#!/usr/bin/env python3
"""
Simple test script for the Adopt LangGraph agent.
This script demonstrates how to use the agent programmatically.
"""

import os
import sys
from pathlib import Path

# Add the parent directory to the path so we can import from examples
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from examples.langgraph_samples.langgraph_sample import create_adopt_agent
from langchain_core.messages import HumanMessage


def test_agent():
    """Test the Adopt LangGraph agent with sample requests."""
    print("🤖 Testing Adopt LangGraph Agent")
    print("=" * 50)
    
    # Check if environment variables are set
    required_vars = [
        "ADOPT_CLIENT_ID", "ADOPT_CLIENT_SECRET", "ADOPT_API_ENDPOINT",
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION", "BEDROCK_MODEL"
    ]
    
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        print(f"❌ Missing required environment variables: {', '.join(missing_vars)}")
        print("Please set these variables in your dev.env file and source it.")
        return False
    
    try:
        # Create the agent
        print("🔧 Creating agent...")
        agent = create_adopt_agent("examples/adopt_profile.json") # type: ignore
        print("✅ Agent created successfully")
        
        # Test cases
        test_cases = [
            "List all available actions",
            "What can you help me with?",
            "Create a new segment called 'Test Segment'",
            "What's the weather like today?",  # This should not be handled by Adopt
        ]
        
        for i, message in enumerate(test_cases, 1):
            print(f"\n📝 Test Case {i}: {message}")
            print("-" * 40)
            
            try:
                # Run the agent
                result = agent.invoke({  # type: ignore
                    "messages": [HumanMessage(content=message)],
                    "adopt_capabilities": "",
                    "can_handle_request": False,
                    "adopt_profile": agent.adopt_profile # type: ignore
                })
                
                # Print the result
                if result["messages"]:
                    final_message = result["messages"][-1] # type: ignore
                    if hasattr(final_message, 'content'): # type: ignore
                        print(f"🤖 Response: {final_message.content}") # type: ignore
                    else:
                        print(f"🤖 Response: {final_message}") # type: ignore
                
                print(f"✅ Test case {i} completed")
                
            except Exception as e:
                print(f"❌ Test case {i} failed: {e}")
        
        print("\n🎉 All tests completed!")
        return True
        
    except Exception as e:
        print(f"❌ Failed to create or run agent: {e}")
        return False


if __name__ == "__main__":
    success = test_agent()
    sys.exit(0 if success else 1)
