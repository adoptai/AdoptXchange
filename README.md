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
- `--list`: List actions via a natural language message (requires `--profile` parameter)
- `--run TEXT`: Run a specific action with the specified command (requires `--profile` parameter)
- `--profile PATH`: Path to the adopt profile JSON file (required for `--list` and `--run` commands)

### Examples

1. **Sync actions with the training pipeline:**
   ```bash
   source dev.env && poetry run python examples/action_api_samples/api_sample.py --sync
   ```

2. **List all available actions:**
   ```bash
   source dev.env && poetry run python examples/action_api_samples/api_sample.py --get-list
   ```

3. **List actions using natural language:**
   ```bash
   source dev.env && poetry run python examples/action_api_samples/api_sample.py --list --profile examples/adopt_profile.json
   ```

4. **Run a specific action:**
   ```bash
   source dev.env && poetry run python examples/action_api_samples/api_sample.py --run "Create a segment named 'Test Segment'" --profile examples/adopt_profile.json
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
# Set up environment variables
source dev.env

# Run the LangGraph agent example
poetry run python examples/langgraph_samples/langgraph_sample.py
```

### Tool Calling Integration

The tool calling example (`examples/tool_calling_samples/tool_calling_sample.py`) demonstrates native LangChain tool calling where each Adopt capability becomes a discrete tool that the LLM can automatically select and execute.

#### Features

- **Dynamic Tool Generation**: Automatically creates LangChain tools from Adopt capabilities
- **Native Tool Calling**: Uses LangChain's built-in tool calling mechanisms
- **Action-Specific Execution**: Each tool directly executes its corresponding Adopt action by ID
- **Multiple Tool Calls per Turn**: LLM can select and execute multiple tools in a single turn when appropriate

#### How It Works

1. Fetches Adopt capabilities using `execution_type=TOOL`
2. Dynamically creates a LangChain tool for each capability
3. Binds all tools to an AWS Bedrock model
4. LLM automatically selects and calls appropriate tools based on user requests

#### Running the Example

```bash
# Set up environment variables
source dev.env

# Run the tool calling example
poetry run python examples/tool_calling_samples/tool_calling_sample.py
```

#### Usage in Your Own Code

```python
from examples.tool_calling_samples.tool_factory import create_all_tools
from examples.action_api_samples.api_sample import list_actions_by_type, load_adopt_profile

# Load configuration
profile = load_adopt_profile()

# Get capabilities as tools
capabilities = list_actions_by_type(execution_type="TOOL").capabilities
tools = create_all_tools(capabilities, profile)

# Use with any LangChain model that supports tool calling
from langchain_aws import ChatBedrockConverse
model = ChatBedrockConverse(...)
model_with_tools = model.bind_tools(tools)

# Execute
response = model_with_tools.invoke("Create a segment named 'Test'")
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

### Bulk Evaluations

The `evals` package provides comprehensive bulk evaluation functionality for testing AdoptXchange agents at scale, with automatic schema validation, tracing comparison, and Maxim integration.

#### Key Features

- **🚀 High-Performance Testing**: Parallel processing with configurable batch sizes and token reuse
- **📊 Multiple Validation Modes**:
  - **Schema Validation**: Automatic comparison of response structure vs expected schema
  - **Tracing Validation**: Compares debug_tracing steps for workflow accuracy
  - **Style Validation**: Ensures output formatting matches expected types
  - **Semantic Similarity**: Maxim evaluators for bias detection and answer relevance
- **🔧 Advanced Configuration**: Field filtering, timeouts, array limiting, retry logic
- **💾 Comprehensive Results**: Detailed CSV output with validation scores and error details
- **🎯 Flexible Execution**: Run with or without Maxim, or evaluate existing results

#### Quick Start

1. **Prepare your test data CSV** (`evals/test_data.csv`):
   ```csv
   Input,Expected_output
   "List all available actions","[{\"name\":\"Create Segment\",\"description\":\"Creates a new segment\"}]"
   "Show device management capabilities","Device Management\n- List All Devices\n- Get Location"
   ```

2. **Configure environment variables in `.env`:**
   ```env
   # Required for AdoptXchange API
   ADOPT_CLIENT_ID=your-client-id
   ADOPT_CLIENT_SECRET=your-client-secret
   ADOPT_API_ENDPOINT=https://connect.adopt.ai
   
   # Required for Maxim evaluation (optional if using --skip-maxim)
   MAXIM_API_KEY=your-maxim-api-key
   MAXIM_WORKSPACE_ID=your-workspace-id
   ```

3. **Run bulk evaluation:**
   ```bash
   # Basic evaluation with all features
   python -m evals.bulk_evals
   
   # With custom CSV and field filtering
   python -m evals.bulk_evals --csv-file my_tests.csv --exclude-fields header_message,footer_message
   
   # Skip Maxim evaluation (faster, local-only validation)
   python -m evals.bulk_evals --skip-maxim
   
   # View all options
   python -m evals.bulk_evals --help
   ```

#### Command-Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--csv-file PATH` | Path to test data CSV file | `evals/test_data.csv` |
| `--exclude-fields LIST` | Comma-separated fields to filter from responses | None |
| `--timeout SECONDS` | Timeout for each agent response | None |
| `--max-items N` | Limit arrays/lists to first N items | None |
| `--batch-size N` | Number of parallel requests | 10 |
| `--max-retries N` | Retry attempts for 503/504 errors | 3 |
| `--skip-maxim` | Skip Maxim evaluation (local validation only) | False |
| `--maxim-only CSV` | Run Maxim eval on existing CSV results | None |

#### CSV Format

**Input columns:**
- `Input` (required): The query/command to send to your agent
- `Expected_output` (required): Expected response (can be JSON, text, or schema)

**Output columns (auto-generated):**
- `input`, `expected_output`, `actual_output`: Test case and results
- `schema_valid`, `schema_errors`: Schema structure validation
- `tracing_valid`, `tracing_errors`: Debug tracing workflow validation
- `style_valid`, `style_errors`: Output type/formatting validation
- `bias`: Maxim bias detection score (0-1, lower is better)
- `similarity`: Maxim semantic similarity (yes/no)

#### Examples

```bash
# Standard evaluation with Maxim
python -m evals.bulk_evals --csv-file evals/my_tests.csv

# Filter out formatting fields for cleaner comparison
python -m evals.bulk_evals --exclude-fields header_message,footer_message,id,timestamp

# Fast local validation without Maxim (no API costs)
python -m evals.bulk_evals --skip-maxim --timeout 30.0

# Limit arrays to 5 items and increase parallelism
python -m evals.bulk_evals --max-items 5 --batch-size 20

# Re-run Maxim evaluation on existing results
python -m evals.bulk_evals --maxim-only evals/evaluation_results_20260126_143022.csv
```

#### Schema Validation

The system automatically validates that actual responses match the expected schema structure:

```csv
Input,Expected_output
"Get user data","{\"id\": \"str\", \"name\": \"str\", \"active\": \"bool\"}"
```

If actual output is `{"id": "user123", "name": "John", "active": true}`, schema validation passes. If it returns `{"id": 123, "username": "John"}`, you'll see errors like:
- `.name: Missing required key`
- `.username: Unexpected key (not in expected schema)`

#### Performance Tips

- Use `--exclude-fields` to remove noise from responses (header/footer messages, IDs, timestamps)
- Set `--timeout` to prevent hanging on slow responses
- Use `--max-items` to limit large arrays for faster comparison
- Increase `--batch-size` if you have good network and want faster processing
- Use `--skip-maxim` for rapid iteration during development
- Token reuse: Authentication happens once per run, not per request

See **`evals/README.md`** for detailed documentation, advanced features, and troubleshooting.

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
   - **`user_org_id`** - Required organization user ID
   - **`org_auth_id`** - Required organization auth ID
   - Any other platform-specific authentication parameters

The `examples/adopt_profile.json` file contains the configuration settings that are passed to Adopt when running actions. This file is essential for ensuring that the right settings are used when executing messages through the Adopt API.

**File Structure:**
```json
{
    "base_url": "https://test6sense.abm.6sense.com",
    "application_base_url": "https://test6sense.abm.6sense.com", 
    "workflow_params": {},
    "security_params": {
        "cookie": "your_session_cookie_here",
        "x-csrftoken": "your_csrf_token_here",
        "referer": "https://test6sense.abm.6sense.com",
        "user_org_id": "your_org_id",
        "org_auth_id": "your_org_auth_id"
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

#### Maxim Evaluation Configuration (Required for Bulk Evaluations)
- `MAXIM_API_KEY`: Maxim API Key for evaluation platform
- `MAXIM_WORKSPACE_ID`: Maxim Workspace ID for storing evaluation results

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

#### For Bulk Evaluations (Additional):
- `MAXIM_API_KEY`: Your Maxim API key for evaluation platform
- `MAXIM_WORKSPACE_ID`: Your Maxim workspace ID for storing results

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

The `dev.env` file is included in `.gitignore` to prevent sensitive information from being committed to version control. Always use environment variables for sensitive data like API keys and secrets.
