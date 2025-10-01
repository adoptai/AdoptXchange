"""Module to demonstrate the use of the Adopt action API"""

import argparse
import json
import os
import requests
from typing import Any, Dict, Sequence
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from examples import read_env, AdoptEnv
from examples.models import AdoptActionListResponse, AdoptActionRunRequest

def get_adopt_env() -> AdoptEnv:
    """Get the Adopt environment variables."""
    return read_env()

def get_auth_token() -> str:
    """Get authentication token from Adopt API."""
    adopt_env = get_adopt_env()
    
    # Authenticate with Adopt API to get bearer token
    auth_url = f"{adopt_env.ADOPT_API_ENDPOINT}/v1/auth/token"
    
    auth_payload = {
        'clientId': adopt_env.ADOPT_CLIENT_ID,
        'secret': adopt_env.ADOPT_CLIENT_SECRET,
    }
    
    print(f"Authenticating with Adopt API at: {auth_url}")
    auth_response = requests.post(auth_url, json=auth_payload)
    
    if auth_response.status_code != 200:
        print(f"Failed to authenticate with Adopt API. Status code: {auth_response.status_code}")
        print(f"Response: {auth_response.text}")
        raise ValueError(f"Authentication failed with status code {auth_response.status_code}: {auth_response.text}")
    
    # Extract access token from response
    auth_data = auth_response.json()
    access_token = auth_data.get('access_token')
    
    if not access_token:
        print("No access token received from authentication response")
        print(f"Response: {auth_data}")
        raise ValueError("No access token received from authentication response")
    
    print("Successfully authenticated with Adopt API")
    return access_token

def load_adopt_profile() -> Dict[str, Any]:
    """Load the adopt profile configuration from adopt_profile.json."""
    # Get the directory of this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Navigate to the examples directory and find adopt_profile.json
    examples_dir = os.path.dirname(script_dir)
    profile_path = os.path.join(examples_dir, "adopt_profile.json")
    
    try:
        with open(profile_path, 'r') as f:
            profile = json.load(f)
        print(f"Loaded adopt profile from: {profile_path}")
        return profile
    except FileNotFoundError:
        print(f"Warning: adopt_profile.json not found at {profile_path}")
        print("Using default profile settings")
        return {
            "base_url": "",
            "application_base_url": "",
            "workflow_params": {},
            "security_params": {
                "cookie": ""
            }
        }
    except json.JSONDecodeError as e:
        print(f"Error parsing adopt_profile.json: {e}")
        raise ValueError(f"Invalid JSON in adopt_profile.json: {e}")

def load_adopt_profile_from_path(profile_path: str) -> Dict[str, Any]:
    """Load the adopt profile configuration from a specified path."""
    try:
        with open(profile_path, 'r') as f:
            profile = json.load(f)
        print(f"Loaded adopt profile from: {profile_path}")
        return profile
    except FileNotFoundError:
        print(f"Error: Profile file not found at {profile_path}")
        raise ValueError(f"Profile file not found at {profile_path}")
    except json.JSONDecodeError as e:
        print(f"Error parsing profile file: {e}")
        raise ValueError(f"Invalid JSON in profile file: {e}")

def sync_adopt_actions(access_token: str = None) -> None:
    """Syncing actions with the training pipeline if running on prem."""
    try:
        # Get environment variables
        adopt_env = get_adopt_env()

        # Get authentication token if not provided
        if access_token is None:
            access_token = get_auth_token()
        
        # Now sync actions with the training pipeline
        # This would typically involve calling an actions sync endpoint
        # For now, we'll just demonstrate the authenticated request capability
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        # Example: List actions to verify authentication works
        actions_url = f"{adopt_env.ADOPT_API_ENDPOINT}/v1/actions/sync"
        print(f"Testing authenticated request to: {actions_url}")
        
        actions_response = requests.post(actions_url, headers=headers)
        
        if actions_response.status_code == 200:
            actions_data = actions_response.json()
            print("Successfully synced actions with Adopt API")
            print(f"Sync response: {actions_data}")
        else:
            print(f"Failed to sync actions. Status code: {actions_response.status_code}")
            print(f"Response: {actions_response.text}")
            
    except requests.exceptions.RequestException as e:
        print(f"Network error occurred: {e}")
    except Exception as e:
        print(f"Unexpected error occurred: {e}")


def list_actions(access_token: str = None) -> AdoptActionListResponse:
    """Test listing all actions."""

    adopt_env = get_adopt_env()

    # Get authentication token if not provided
    if access_token is None:
        access_token = get_auth_token()
    
    url = f"{adopt_env.ADOPT_API_ENDPOINT}/v1/actions/list"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        print(f"Failed to list actions. Status code: {response.status_code}")
        print(f"Response: {response.text}")
        raise ValueError(f"API request failed with status code {response.status_code}: {response.text}")
    
    json_response = response.json()
    
    if "capabilities" not in json_response:
        raise ValueError(f"Expected 'capabilities' in response, got: {json_response}")
    if not isinstance(json_response["capabilities"], list):
        raise ValueError(f"Expected 'capabilities' to be a list, got: {type(json_response['capabilities'])}")
    if len(json_response["capabilities"]) == 0:
        print("Warning: No capabilities found in response")
    return AdoptActionListResponse(**json_response)

def run_list_actions_message(profile: Dict[str, Any], access_token: str = None) -> str:
    """Running a list actions meta message via APIs."""
    adopt_env = get_adopt_env()

    # Get authentication token if not provided
    if access_token is None:
        access_token = get_auth_token()
        
    url = f"{adopt_env.ADOPT_API_ENDPOINT}/v1/actions/run"
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    action_request = AdoptActionRunRequest(
        messages=[
            HumanMessage(content="List all actions")
        ],
        base_url=profile.get("base_url", ""),
        application_base_url=profile.get("application_base_url", ""),
        workflow_params=profile.get("workflow_params", {}),
        security_params=profile.get("security_params", {})
    )
    response = requests.post(url, headers=headers,
        json=action_request.model_dump())
    
    if response.status_code != 200:
        print(f"Failed to run list actions message. Status code: {response.status_code}")
        print(f"Response: {response.text}")
        raise ValueError(f"API request failed with status code {response.status_code}: {response.text}")
    
    json_response = response.json()
    if json_response.get("status") != True:
        print(f"API returned unsuccessful status: {json_response}")
        raise ValueError(f"API returned unsuccessful status: {json_response}")
    action_message = AIMessage(**json_response["ai_message"])
    if not isinstance(action_message.content, list): # pyright: ignore
        raise ValueError(f"Action message content is not a list. It is: {type(action_message.content)}") # pyright: ignore
    return str(action_message.content) # pyright: ignore

def run_action(messages: Sequence[HumanMessage | AIMessage | SystemMessage], profile: Dict[str, Any], access_token: str = None) -> str:
    """Test running a specific action via langchain adapter."""
    adopt_env = get_adopt_env()

    # Get authentication token if not provided
    if access_token is None:
        access_token = get_auth_token()
        
    url = f"{adopt_env.ADOPT_API_ENDPOINT}/v1/actions/run"
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    action_request = AdoptActionRunRequest(
        messages=list(messages),
        base_url=profile.get("base_url", ""),
        application_base_url=profile.get("application_base_url", ""),
        workflow_params=profile.get("workflow_params", {}),
        security_params=profile.get("security_params", {})
    )
    response = requests.post(url, headers=headers, json=action_request.model_dump())
    print(f"Request payload: {response}")
    if response.status_code != 200:
        print(f"Failed to run action. Status code: {response.status_code}")
        print(f"Response: {response.text}")
        raise ValueError(f"API request failed with status code {response.status_code}: {response.text}")
    
    json_response = response.json()
    
    if json_response.get("status") != True:
        print(f"API returned unsuccessful status: {json_response}")
        raise ValueError(f"API returned unsuccessful status: {json_response}")
    
    # Check for expected content in response (these are specific to the test action)
    ai_message = AIMessage(**json_response["ai_message"])
    if not isinstance(ai_message.content, list): # pyright: ignore
        raise ValueError(f"Action message content is not a list. It is: {type(ai_message.content)}") # pyright: ignore
    return str(ai_message.content) # pyright: ignore

def run_simple_action(command: str, profile: Dict[str, Any], access_token: str = None) -> str:
    """Simple function to run an action with just a command string.
    
    This is a convenience function that creates a HumanMessage from the command
    and calls run_action with it.
    
    Args:
        command: The command string to execute
        profile: The adopt profile configuration
        access_token: Optional authentication token to reuse
        
    Returns:
        The response from the action execution
    """
    messages = [HumanMessage(content=command)]
    return run_action(messages, profile, access_token)

def main():
    """Main entry point for the Adopt Action API Samples."""
    # let's parse the command line arguments
    parser = argparse.ArgumentParser(description="Adopt Action API Samples")
    parser.add_argument("--sync", action="store_true", help="Sync adopt actions")
    parser.add_argument("--get-list", action="store_true", help="List adopt actions")
    parser.add_argument("--list", action="store_true", help="List adopt actions via message")
    parser.add_argument("--run", type=str, help="Run adopt action with the specified command")
    parser.add_argument("--profile", type=str, help="Path to the adopt profile JSON file (required for --list and --run commands)")
    args = parser.parse_args()
    # Check if no arguments are provided or if invalid combination of arguments
    if not any([args.sync, args.get_list, args.list, args.run]):
        print("Error: No action specified. Please provide one of the following options:")
        parser.print_help()
        exit(1)
    
    # Check if --profile is required for specific commands
    if (args.list or args.run) and not args.profile:
        print("Error: --profile is required for --list and --run commands")
        parser.print_help()
        exit(1)

    if args.sync:
        sync_adopt_actions()
        exit(0)
    if args.get_list:
        action_list = list_actions()
        print(action_list)
        exit(0)
    if args.list:
        profile = load_adopt_profile_from_path(args.profile)
        message = run_list_actions_message(profile)
        print(message)
        exit(0)
    if args.run:
        profile = load_adopt_profile_from_path(args.profile)
        messages = [HumanMessage(content=args.run)]
        message = run_action(messages, profile)
        print(message)
        exit(0)


if __name__ == "__main__":
    """Run the demo when script is executed directly."""
    main()
