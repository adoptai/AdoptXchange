# AdoptXchange
Methods and examples to connect external agents to interact with agents built on the [Adopt AI platform](https://www.adopt.ai).

## Environment Setup

This project requires several environment variables to be configured. A comprehensive `dev.env` file has been created with all the necessary variables for development.

### Quick Start

1. Copy the environment template:
   ```bash
   cp dev.env .env
   ```

2. Edit `.env` and fill in your actual values for the required variables.

3. Install dependencies using Poetry:
   ```bash
   poetry install
   ```

   **Note**: The project now includes additional dependencies for the LangGraph agent:
   - `langchain-aws`: For AWS Bedrock Converse integration
   - `langgraph`: For building the intelligent agent workflow

## Usage

The main functionality is demonstrated in two ways:

1. **Direct API Usage**: `examples/action_api_samples/api_sample.py` provides a command-line interface for interacting with the Adopt API.
2. **LangGraph Agent**: `examples/langgraph_samples/langgraph_sample.py` provides an intelligent agent that automatically determines if Adopt can handle requests and executes them accordingly.

### Command Line Options

```bash
# Using Poetry (recommended)
poetry run python examples/action_api_samples/api_sample.py [OPTIONS]

# Or activate the virtual environment first
poetry shell
python examples/action_api_samples/api_sample.py [OPTIONS]
```

Available options:
- `--sync`: Sync actions with the Adopt training pipeline
- `--get-list`: List all available actions from the Adopt API
- `--list`: List actions via a natural language message
- `--run`: Run a specific action (requires `--command` parameter)
- `--command TEXT`: Specify the command to run when using `--run`

### Examples

1. **Sync actions with the training pipeline:**
   ```bash
   poetry run python examples/action_api_samples/api_sample.py --sync
   ```

2. **List all available actions:**
   ```bash
   poetry run python examples/action_api_samples/api_sample.py --get-list
   ```

3. **List actions using natural language:**
   ```bash
   poetry run python examples/action_api_samples/api_sample.py --list --profile examples/adopt_profile.json
   ```

4. **Run a specific action:**
   ```bash
   poetry run python examples/action_api_samples/api_sample.py --run "Create a segment named 'Test Segment'" --profile examples/adopt_profile.json
   ```

### LangGraph Agent

The LangGraph agent (`examples/langgraph_samples/langgraph_sample.py`) provides an intelligent way to interact with Adopt capabilities:

#### Features

- **Automatic Capability Checking**: Uses AWS Bedrock Converse to determine if Adopt can handle a user's request
- **Smart Routing**: Only executes actions when Adopt can actually fulfill the request
- **Conversation Context**: Maintains message history for better context understanding
- **Error Handling**: Gracefully handles errors and provides meaningful feedback

#### How It Works

The agent has two main nodes:

1. **Capability Checker**: 
   - Retrieves available Adopt capabilities using `get_list()`
   - Uses AWS Bedrock Converse (Claude) to analyze if the user's request can be handled
   - Returns a boolean decision on whether to proceed

2. **Action Runner**:
   - If the request can be handled, executes it using `run_action()`
   - Passes the entire message history for context
   - Returns the Adopt API response

#### Usage Example

```python
from examples.langgraph_samples.langgraph_sample import create_adopt_agent
from langchain_core.messages import HumanMessage

# Create the agent
agent = create_adopt_agent("examples/adopt_profile.json")

# Run a conversation
result = agent.invoke({
    "messages": [HumanMessage(content="Create a new segment called 'Test Segment'")],
    "adopt_capabilities": "",
    "can_handle_request": False,
    "adopt_profile": agent.adopt_profile
})

print(result["messages"][-1].content)
```

#### Running the Example

```bash
# Run the LangGraph agent example
poetry run python examples/langgraph_samples/langgraph_sample.py
```

### Available Functions

The sample script provides several functions for interacting with the Adopt API:

- **`sync_adopt_actions()`**: Authenticates with the Adopt API and syncs actions with the training pipeline
- **`list_actions()`**: Retrieves and returns a list of all available actions
- **`run_list_actions_message()`**: Uses natural language to request a list of actions
- **`run_action(messages, profile)`**: Executes a specific action based on the provided messages and profile
- **`run_simple_action(command, profile)`**: Simple convenience function that takes just a command string and profile, creates a HumanMessage, and calls run_action

#### Simple Action Example

The `run_simple_action` function provides an easy way to execute actions with minimal setup:

```python
from examples.action_api_samples.api_sample import run_simple_action, load_adopt_profile

# Load your profile configuration
profile = load_adopt_profile()

# Run a simple action
result = run_simple_action("Create a segment named 'Test Segment'", profile)
print(result)
```

This function automatically:
1. Creates a `HumanMessage` from your command string
2. Calls the `run_action` function with the message and profile
3. Returns the response from the Adopt API

### Configuration Files

#### adopt_profile.json

**TODO: Create your `adopt_profile.json` file**

Before using the Adopt API, you need to create the `examples/adopt_profile.json` file with your platform-specific configuration. This file contains the configuration settings that are passed to Adopt when running actions and is essential for ensuring that the right settings are used when executing messages through the Adopt API.

**Required Steps:**

1. Copy the template file:
   ```bash
   cp examples/adopt_profile.json examples/my_adopt_profile.json
   ```

2. Update the configuration with your platform details:
   - Set `base_url` and `application_base_url` to your target platform's URLs
   - Configure `security_params` with the necessary headers and authentication tokens that your platform's browser-facing APIs require

3. **Important**: The `security_params` section should include all the headers typically needed for calling your platform's browser-facing APIs, such as:
   - Authentication cookies
   - Authorization headers
   - CSRF tokens
   - Session IDs
   - Any other platform-specific authentication parameters

The `examples/adopt_profile.json` file contains the configuration settings that are passed to Adopt when running actions. This file is essential for ensuring that the right settings are used when executing messages through the Adopt API.

**File Structure:**
```json
{
    "base_url": "https://test6sense.abm.6sense.com",
    "application_base_url": "https://test6sense.abm.6sense.com", 
    "workflow_params": {},
    "security_params": {
        "cookie": ""
    }
}
```

**Configuration Parameters:**

- `base_url`: The base URL for the target platform/application that Adopt will interact with
- `application_base_url`: The application-specific base URL for the platform
- `workflow_params`: Additional workflow-specific parameters (typically empty object `{}`)
- `security_params`: Security-related parameters including authentication cookies
  - `cookie`: Authentication cookie value for the target platform (leave empty if not needed)

**Usage:**
This profile is automatically loaded when running actions through the API sample script. The settings in this file are passed to the Adopt API to ensure that actions are executed with the correct platform context and security credentials.

**Important Notes:**
- Update the `base_url` and `application_base_url` to match your target platform
- If your platform requires authentication cookies, add them to the `security_params.cookie` field
- Keep this file secure as it may contain sensitive authentication information

### Environment Variables

The `dev.env` file contains the following configuration:

#### Adopt API Configuration
- `ADOPT_CLIENT_ID`: Client ID for Adopt API authentication
- `ADOPT_CLIENT_SECRET`: Client secret for Adopt API authentication  
- `ADOPT_API_ENDPOINT`: Endpoint where Adopt is running (https://connect.adopt.ai by default. Point it to your onprem endpoint if appropriate)

#### AWS Bedrock Configuration (Required for LangGraph Agent)
- `AWS_ACCESS_KEY_ID`: AWS Access Key ID for Bedrock authentication
- `AWS_SECRET_ACCESS_KEY`: AWS Secret Access Key for Bedrock authentication
- `AWS_REGION`: AWS Region where Bedrock is available (default: us-east-1)
- `BEDROCK_MODEL`: Bedrock Converse model to use for capability checking (default: anthropic.claude-3-sonnet-20240229-v1:0)

### Required Variables

You'll need to configure all the variables in the `dev.env` file:

#### For Direct API Usage:
- `ADOPT_CLIENT_ID`: Your Adopt API client ID
- `ADOPT_CLIENT_SECRET`: Your Adopt API client secret
- `ADOPT_API_ENDPOINT`: The Adopt API endpoint URL

**Getting Your Adopt API Credentials:**

To obtain your `ADOPT_CLIENT_ID` and `ADOPT_CLIENT_SECRET`, follow these steps from the [Adopt AI External API documentation](https://docs.adopt.ai/api-reference/external-api):

1. Go to the **Adopt Platform**
2. Navigate to `Settings → Profile → Personal Tokens`
3. Click **"Generate Token"**
4. Copy the `clientId` and `secret` values
5. Use these values in your `.env` file as `ADOPT_CLIENT_ID` and `ADOPT_CLIENT_SECRET`

> 💡 You can manage and revoke tokens from the same page at any time.

#### For LangGraph Agent (Additional):
- `AWS_ACCESS_KEY_ID`: Your AWS Access Key ID
- `AWS_SECRET_ACCESS_KEY`: Your AWS Secret Access Key
- `AWS_REGION`: AWS region where Bedrock is available
- `BEDROCK_MODEL`: Bedrock model identifier

## Development

This project uses Poetry for dependency management and virtual environment handling.

### Poetry Commands

```bash
# Install dependencies
poetry install

# Add a new dependency
poetry add package-name

# Add a development dependency
poetry add --group dev package-name

# Activate the virtual environment
poetry shell

# Run commands in the virtual environment
poetry run python script.py

# Update dependencies
poetry update

# Show dependency tree
poetry show --tree
```

### Development Dependencies

The project includes several development tools:
- `pytest` - Testing framework
- `black` - Code formatter
- `flake8` - Linting
- `mypy` - Type checking

Run them with:
```bash
poetry run pytest
poetry run black .
poetry run flake8
poetry run mypy .
```

### Security Note

The `.env` file is included in `.gitignore` to prevent sensitive information from being committed to version control. Always use environment variables for sensitive data like API keys and secrets.

