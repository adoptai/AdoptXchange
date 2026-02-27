# Evals V2 — Server-Side Bulk Evaluations

Evals V2 submits evaluation jobs to the Adopt.AI backend, which processes them asynchronously via a Temporal FIFO queue. All LLM execution and Maxim scoring happen server-side. The client submits a CSV, polls for progress, and downloads results.

## Setup

Set your Frontegg API credentials:

```bash
export ADOPT_CLIENT_ID=your_client_id
export ADOPT_CLIENT_SECRET=your_client_secret
```

## CLI Usage (`bulk_evals_v2.py`)

```bash
# Submit and wait for results
python evals/bulk_evals_v2.py \
    --csv-file test_data.csv \
    --action-id action_rallyup_assistant \
    --base-url https://go.rallyup.com \
    --cookie "session=abc123"

# Skip Maxim scoring
python evals/bulk_evals_v2.py \
    --csv-file test_data.csv \
    --action-id action_rallyup_assistant \
    --base-url https://go.rallyup.com \
    --cookie "session=abc123" \
    --skip-maxim

# List all jobs
python evals/bulk_evals_v2.py --list-jobs

# Filter by status
python evals/bulk_evals_v2.py --list-jobs --status completed

# Check job progress
python evals/bulk_evals_v2.py --check-status JOB_ID

# Cancel a running job
python evals/bulk_evals_v2.py --cancel-job JOB_ID
```

Run `python evals/bulk_evals_v2.py --help` for all options.

## Python Usage (`FIFOEvalsClient`)

```python
from AdoptXchange.evals import FIFOEvalsClient

# One-liner: submit, wait, download
client = FIFOEvalsClient(client_id="...", client_secret="...")
result_file = client.submit_and_wait(
    csv_file="test_data.csv",
    config={
        "action_id": "action_rallyup_assistant",
        "base_url": "https://go.rallyup.com",
        "security_params": {"cookie": "session=abc123"},
    },
    output_file="results.csv",
)

# Or step-by-step
job_id = client.submit_evaluation("test_data.csv", config={...})
status = client.get_status(job_id)
result = client.wait_for_completion(job_id, poll_interval=30)
client.download_results(result, "results.csv")
```

Create from environment variables:

```python
client = FIFOEvalsClient.from_env()  # reads ADOPT_CLIENT_ID + ADOPT_CLIENT_SECRET
```

## CSV Format

The input CSV must have at least one of these columns: `input`, `prompt`, `user_message`, or `message`.

### Single-turn

```csv
input,expected_output
What is 2+2?,4
What is the capital of France?,Paris
```

### Multi-turn

Rows with the same ID column (`input_id`, `conversation_id`, or `id`) are grouped into a conversation and executed in order:

```csv
input_id,input,expected_output
1,I want to view raffle tickets,"Here's the link..."
11,I want to see ticket registrations,"I found 2 campaigns. Which one?"
11,Discovered Water Gala 2026,"Here's the link to view registrations..."
```

### Limits

- Max file size: 100 MB
- Max rows: 10,000
- Supported encodings: UTF-8, UTF-8-BOM, Latin-1, Windows-1252

## Config Options

```python
config = {
    "action_id": "action_rallyup_assistant",   # required
    "base_url": "https://go.rallyup.com",      # required
    "security_params": {"cookie": "session=..."}, # required
    "batch_size": 5,          # conversations per batch (default: 5)
    "skip_maxim": False,      # skip Maxim scoring (default: False)
}
```

## API Reference

### `FIFOEvalsClient(client_id, client_secret, *, access_token=None, base_url="https://api.adopt.ai", timeout=30.0)`

Create with credentials (auto token management) or a pre-obtained `access_token`.

### Class methods

- `FIFOEvalsClient.from_env(base_url=...)` — create from `ADOPT_CLIENT_ID` + `ADOPT_CLIENT_SECRET` env vars

### Instance methods

| Method | Returns | Description |
|--------|---------|-------------|
| `submit_evaluation(csv_file, config)` | `str` (job_id) | Submit job, returns immediately |
| `get_status(job_id)` | `dict` | Status with progress metrics |
| `wait_for_completion(job_id, poll_interval=30)` | `dict` | Block until done, return result |
| `get_result(job_id)` | `dict` | Get download URLs |
| `list_jobs(page=1, page_size=20, status_filter=None)` | `list` | List jobs for your org |
| `cancel_job(job_id)` | `dict` | Cancel pending/running job |
| `download_results(result, output_file)` | `str` | Download CSV from presigned URL |
| `submit_and_wait(csv_file, config, output_file, ...)` | `str` | Submit + wait + download |

### Exceptions

- `FIFOClientError` — base exception
- `ValidationError` — CSV validation failed
- `AuthenticationError` — invalid credentials or expired token
- `JobNotFoundError` — job not found
- `JobFailedError` — job execution failed (has `.job_id`, `.error_message`, `.status_data`)

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ADOPT_CLIENT_ID` | Yes | — | Frontegg API client ID |
| `ADOPT_CLIENT_SECRET` | Yes | — | Frontegg API client secret |
| `ADOPT_API_BASE_URL` | No | `https://api.adopt.ai` | Backend proxy URL |
