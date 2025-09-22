# AdoptXchange
Methods and examples to connect external agents to interact with agents built on the AdoptAI platform.

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

## Usage

The main functionality is demonstrated in `examples/action-api-samples/api_sample.py`, which provides a command-line interface for interacting with the Adopt API.

### Command Line Options

```bash
# Using Poetry (recommended)
poetry run python examples/action-api-samples/api_sample.py [OPTIONS]

# Or activate the virtual environment first
poetry shell
python examples/action-api-samples/api_sample.py [OPTIONS]
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
   source dev.env && poetry run python examples/action-api-samples/api_sample.py --sync
   ```

2. **List all available actions:**
   ```bash
   source dev.env && poetry run python examples/action-api-samples/api_sample.py --get-list
   ```

3. **List actions using natural language:**
   ```bash
   source dev.env && poetry run python examples/action-api-samples/api_sample.py --list
   ```

4. **Run a specific action:**
   ```bash
   source dev.env && poetry run python examples/action-api-samples/api_sample.py --run --command "Create a segment named 'Test Segment'"
   ```

### Available Functions

The sample script provides several functions for interacting with the Adopt API:

- **`sync_adopt_actions()`**: Authenticates with the Adopt API and syncs actions with the training pipeline
- **`list_actions()`**: Retrieves and returns a list of all available actions
- **`run_list_actions_message()`**: Uses natural language to request a list of actions
- **`run_action(command)`**: Executes a specific action based on the provided command

### Configuration Files

#### adopt_profile.json

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

### Required Variables

You'll need to configure all the variables in the `dev.env` file:
- `ADOPT_CLIENT_ID`: Your Adopt API client ID
- `ADOPT_CLIENT_SECRET`: Your Adopt API client secret
- `ADOPT_API_ENDPOINT`: The Adopt API endpoint URL

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
