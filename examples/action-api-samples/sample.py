"""Module to demonstrate the use of the Adopt action API"""

import os
import requests
from langchain_core.messages import HumanMessage
from examples import read_env, AdoptEnv
from models import AdoptActionListResponse, AdoptAction, AdoptActionRunRequest, AdoptActionRunResponse

def get_adopt_env() -> AdoptEnv:
    """Get the Adopt environment variables."""
    return read_env()

def sync_adopt_actions() -> None:
    """Syncing actions with the training pipeline if running on prem."""
    
    try:
        # Get environment variables
        adopt_env = get_adopt_env()

        # Authenticate with Adopt API to get bearer token
        auth_url = f"{adopt_env.ADOPT_API_ENDPOINT}/v1/auth/token"

        auth_payload = {
            'clientId': adopt_env.ADOPT_CLIENT_ID,
            'secret': adopt_env.ADOPT_CLIENT_SECRET,
        }

        print(f"Authenticating with Adopt API at: {auth_url}")
        auth_response = requests.post(auth_url, data=auth_payload)
        
        if auth_response.status_code != 200:
            print(f"Failed to authenticate with Adopt API. Status code: {auth_response.status_code}")
            print(f"Response: {auth_response.text}")
            return
        
        # Extract access token from response
        auth_data = auth_response.json()
        access_token = auth_data.get('access_token')
        
        if not access_token:
            print("No access token received from authentication response")
            print(f"Response: {auth_data}")
            return
        
        print("Successfully authenticated with Adopt API")
        
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


def list_actions() -> AdoptActionListResponse:
    """Test listing all actions."""

    adopt_env = get_adopt_env()

    # first let's hit the auth API with the PAT to get a bearer token
    url = f"{adopt_env.ADOPT_API_ENDPOINT}/v1/auth/token"
    auth_response = requests.post(url, json={
        'clientId': adopt_env.ADOPT_CLIENT_ID,
        'secret': adopt_env.ADOPT_CLIENT_SECRET,
    })
    assert auth_response.status_code == 200
    auth_token_response = AuthTokenResponse(**auth_response.json())
    url = f"{adopt_env.ADOPT_API_ENDPOINT}/v1/actions/list"
    headers = {
        "Authorization": f"Bearer {auth_token_response.access_token}",
        "Content-Type": "application/json"
    }
    response = requests.post(url, headers=headers)
    assert response.status_code == 200
    json_response = response.json()
    print(json_response)
    assert "capabilities" in json_response
    assert isinstance(json_response["capabilities"], list)
    assert len(json_response["capabilities"]) > 0
    return AdoptActionListResponse(**json_response)

def run_list_actions_message() -> str:
    """Running a list actions meta message via APIs."""

    url = f"{adopt_env.ADOPT_API_ENDPOINT}/v1/auth/token"
    auth_response = requests.post(url, json=get_auth_request.model_dump())
    assert auth_response.status_code == 200
    auth_token_response = AuthTokenResponse(**auth_response.json())
    url = f"{adopt_env.ADOPT_API_ENDPOINT}/v1/actions/run"
    headers = {
        "Authorization": f"Bearer {auth_token_response.access_token}"
    }
    action_request = AdoptActionRunRequest(
        messages=[
            HumanMessage(content="List all actions")
        ],
    )
    response = requests.post(url, headers=headers,
        json=action_request.model_dump())
    assert response.status_code == 200
    json_response = response.json()
    print(json_response)
    assert json_response["status"] == True
    action_message = AIMessage(**json_response["ai_message"])
    return action_message.content

def run_action(command: str) -> str:
    """Test running a specific action via langchain adapter."""
    adopt_env = get_adopt_env()

    # now let's hit the auth API with the PAT to get a bearer token
    url = f"{adopt_env.ADOPT_API_ENDPOINT}/v1/auth/token"
    auth_response = requests.post(url, json=get_auth_request.model_dump())
    assert auth_response.status_code == 200
    auth_token_response = AuthTokenResponse(**auth_response.json())
    url = f"{adopt_env.ADOPT_API_ENDPOINT}/v1/actions/run"
    headers = {
        "Authorization": f"Bearer {auth_token_response.access_token}"
    }
    action_request = AdoptActionRunRequest(
        messages=[
            HumanMessage(content=command)
        ],
        base_url="https://test6sense.abm.6sense.com",
        application_base_url="https://test6sense.abm.6sense.com",
        workflow_params={},
        security_params={
            "cookie": ""
        }
    )
    response = requests.post(url, headers=headers, json=action_request.model_dump())
    assert response.status_code == 200
    json_response = response.json()
    print(json_response)
    assert json_response["status"] == True
    assert "Test Segment" in json_response["response"]
    assert "This is a test segment" in json_response["response"]
    assert re.search(r"Industry:\s*Technology", json_response["response"])
    assert re.search(r"Employee Count:\s*100-500", json_response["response"])

if __name__ == "__main__":
    """Run the demo when script is executed directly."""

    # let's parse the command line arguments
    parser = argparse.ArgumentParser(description="Adopt Action API Samples")
    parser.add_argument("--sync", action="store_true", help="Sync adopt actions")
    parser.add_argument("--get-list", action="store_true", help="List adopt actions")
    parser.add_argument("--list", action="store_true", help="List adopt actions via message")
    parser.add_argument("--run", action="store_true", help="Run adopt action")
    parser.add_argument("--command", type=str, help="Command to run")
    args = parser.parse_args()
    
    if args.sync:
        sync_adopt_actions()
        exit(0)
    if args.get_list:
        action_list = list_actions()
        print(action_list)
        exit(0)
    if args.list:
        message = run_list_actions_message()
        print(message)
        exit(0)
    if args.run:
        message = run_action()
        print(message)
        exit(0)
