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

3. Install dependencies (if any):
   ```bash
   pip install -r requirements.txt
   ```

## Usage

The main functionality is demonstrated in `examples/action-api-samples/sample.py`, which provides a command-line interface for interacting with the Adopt API.

### Command Line Options

```bash
python examples/action-api-samples/sample.py [OPTIONS]
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
   python examples/action-api-samples/sample.py --sync
   ```

2. **List all available actions:**
   ```bash
   python examples/action-api-samples/sample.py --get-list
   ```

3. **List actions using natural language:**
   ```bash
   python examples/action-api-samples/sample.py --list
   ```

4. **Run a specific action:**
   ```bash
   python examples/action-api-samples/sample.py --run --command "Create a segment named 'Test Segment'"
   ```

### Available Functions

The sample script provides several functions for interacting with the Adopt API:

- **`sync_adopt_actions()`**: Authenticates with the Adopt API and syncs actions with the training pipeline
- **`list_actions()`**: Retrieves and returns a list of all available actions
- **`run_list_actions_message()`**: Uses natural language to request a list of actions
- **`run_action(command)`**: Executes a specific action based on the provided command

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

### Security Note

The `dev.env` file is included in `.gitignore` to prevent sensitive information from being committed to version control. Always use environment variables for sensitive data like API keys and secrets.
