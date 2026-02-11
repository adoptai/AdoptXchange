# FIFO Evals Client - Migration Guide

## What Changed?

### OLD: `bulk_evals.py` (Synchronous)
- **Problem:** Times out after 60 seconds
- **Failure Rate:** 100% on jobs with 990+ prompts
- **Flow:** CSV → external-apis (synchronous) → ❌ Timeout

### NEW: `fifo_client.py` (Async Job Queue + Enhanced Validation)
- **Solution:** Async job submission with FIFO queue
- **Success Rate:** 0% failure rate (no timeouts)
- **Flow:** CSV → Submit (<1s) → FIFO Queue → Background Processing → Results
- **New Features:**
  - ✅ Client-side CSV validation (encoding, columns, structure)
  - ✅ List all jobs with status filtering
  - ✅ Cancel running jobs
  - ✅ Comprehensive error messages
  - ✅ Progress tracking with conversation stats

---

## Quick Start

### Installation

No additional dependencies needed! Uses `httpx` which is already in the project.

### Basic Usage

```python
from AdoptXchange.evals import FIFOEvalsClient

# Create client
client = FIFOEvalsClient(api_key="your_api_key")

# Submit and wait (simplest)
result_file = client.submit_and_wait(
    csv_file="evaluation_test_cases.csv",
    config={
        "action_id": "action_rallyup_assistant",
        "base_url": "https://go.rallyup.com",
        "security_params": {"cookie": "session=..."},
        "batch_size": 5
    },
    output_file="results.csv"
)

print(f"Results: {result_file}")
```

**Output:**
```
Submitting evaluation job: evaluation_test_cases.csv

⚠️  CSV Validation Warnings:
   • Mixed conversation structure: 5 multi-turn, 45 single-turn conversations.

📊 CSV Analysis:
   • 55 total rows
   • 50 conversations (5 multi-turn, 45 single-turn)
   • Input column: 'input'
   • ID column: 'input_id'

Job submitted: abc-123

Progress: 10.0% (5 of 50 conversations)
Progress: 20.0% (10 of 50 conversations)
Progress: 30.0% (15 of 50 conversations)
...
✅ Job completed in 5.2 minutes
Downloaded: results.csv (12.5 KB)
```

---

## Migration Examples

### Example 1: Replace Synchronous Call

**Before (bulk_evals.py):**
```python
from AdoptXchange.evals.bulk_evals import run_bulk_evaluation

# Times out on 990 prompts ❌
result = run_bulk_evaluation(
    csv_file="test.csv",
    action_id="action_rallyup_assistant",
    # ... fails
)
```

**After (fifo_client.py):**
```python
from AdoptXchange.evals import run_fifo_evaluation

# Succeeds on 990 prompts ✅
result_file = run_fifo_evaluation(
    csv_file="test.csv",
    action_id="action_rallyup_assistant",
    base_url="https://go.rallyup.com",
    security_params={"cookie": "session=..."},
    api_key="your_api_key",
    output_file="results.csv"
)
```

### Example 2: Step-by-Step Control

**When you need more control:**

```python
from AdoptXchange.evals import FIFOEvalsClient

client = FIFOEvalsClient(api_key="your_api_key")

# 1. Submit job (returns immediately)
job_id = client.submit_evaluation(
    csv_file="test.csv",
    config={
        "action_id": "action_rallyup_assistant",
        "base_url": "https://go.rallyup.com",
        "security_params": {"cookie": "session=..."}
    }
)
print(f"Job ID: {job_id}")

# 2. Check status anytime
status = client.get_status(job_id)
print(f"Progress: {status['progress']['percent_complete']:.1f}%")

# 3. Wait for completion (optional)
result = client.wait_for_completion(job_id, poll_interval=30)

# 4. Download results
client.download_results(result, "results.csv")
```

### Example 3: List and Manage Jobs

**List all your evaluation jobs:**

```python
from AdoptXchange.evals import FIFOEvalsClient

client = FIFOEvalsClient(api_key="your_api_key")

# List all jobs
all_jobs = client.list_jobs()
for job in all_jobs:
    print(f"{job['job_id']}: {job['status']} - {job['submitted_at']}")

# List only completed jobs
completed = client.list_jobs(status_filter="completed")

# List only in-progress jobs
active = client.list_jobs(status_filter="processing")
```

### Example 4: Cancel a Long-Running Job

**Cancel jobs that are taking too long:**

```python
from AdoptXchange.evals import FIFOEvalsClient

client = FIFOEvalsClient(api_key="your_api_key")

# Submit large evaluation (990 prompts = 85 minutes)
job_id = client.submit_evaluation("large_eval.csv", config={...})

# Check progress
status = client.get_status(job_id)
print(f"Progress: {status['progress']['percent_complete']}%")

# User realizes wrong file - cancel it!
if status['status'] in ['pending', 'processing']:
    result = client.cancel_job(job_id)
    print(f"Cancelled at: {result['cancelled_at']}")
```

### Example 5: Context Manager

**For automatic cleanup:**

```python
from AdoptXchange.evals import FIFOEvalsClient

with FIFOEvalsClient(api_key="your_api_key") as client:
    result_file = client.submit_and_wait(
        csv_file="test.csv",
        config={...},
        output_file="results.csv"
    )
# Client automatically closed
```

---

## Configuration Options

### Required Fields

```python
config = {
    "action_id": "action_rallyup_assistant",  # ProjectA3 action ID
    "base_url": "https://go.rallyup.com",     # Customer API URL
    "security_params": {                       # Auth credentials
        "cookie": "session=abc123"             # or api_key, etc.
    }
}
```

### Optional Fields

```python
config = {
    # ... required fields ...

    "batch_size": 5,              # Conversations per batch (default: 5)
    "skip_maxim": False,          # Skip Maxim evaluation (default: False)
    "maxim_workspace_id": "...",  # Maxim workspace (optional)
    "workflow_params": {},        # Additional action params (default: {})
}
```

---

## CSV Format

### Input CSV (Flexible Column Names!)

The CSV format is **backward compatible** with bulk_evals.py, plus new flexibility:

```csv
input_id,input,expected_output
1,I want to view raffle tickets,Perfect! Here's the link...
11,I want to see ticket registrations,I found 2 campaigns. Which one?
11,Discovered Water Gala 2026,Here's the link to view registrations...
```

**Column Name Flexibility:**
- **Input column:** `input`, `prompt`, `user_message`, or `message`
- **ID column:** `input_id`, `conversation_id`, or `id`
- **Output column:** `expected_output` or `response`
- All case-insensitive matching

**Example Alternative Format:**
```csv
conversation_id,prompt,response
conv1,Hello,Hi there
conv1,How are you?,I'm doing well
```

**Multi-Turn Detection:**
- Same `input_id` = same conversation
- Rows executed in order
- Conversation history preserved

**No ID Column?**
- All rows treated as separate single-turn conversations
- Server auto-generates IDs

**CSV Validation:**
The client now validates your CSV before submission:
- ✅ Encoding support (UTF-8, UTF-8-BOM, Latin-1, Windows-1252)
- ✅ File size limit (100 MB max)
- ✅ Row count limit (10,000 rows max)
- ✅ Required columns check
- ✅ Conversation structure analysis

### Output CSV (Enhanced!)

```csv
input_id,turn,input,expected_output,actual_output,status,execution_time_ms
1,1,I want to view raffle tickets,...,Perfect!...,completed,4823
11,1,I want to see ticket registrations,...,I found 2...,completed,4201
11,2,Discovered Water Gala 2026,...,Here's the link...,completed,5567
```

**New columns:**
- `turn`: Turn number within conversation
- `status`: `completed`, `failed`, or `error`
- `execution_time_ms`: Per-turn execution time

---

## API Methods

### `FIFOEvalsClient(api_key, base_url="https://api.adopt.ai")`

Initialize client.

**Parameters:**
- `api_key` (str): Bearer token for authentication
- `base_url` (str): API base URL (default: production)

---

### `submit_evaluation(csv_file, config) -> str`

Submit evaluation job (returns immediately in <1 second).

**Parameters:**
- `csv_file` (str): Path to CSV file
- `config` (dict): Job configuration (see Configuration Options)

**Returns:**
- `job_id` (str): Job identifier for status tracking

**Example:**
```python
job_id = client.submit_evaluation("test.csv", config={...})
```

---

### `get_status(job_id) -> dict`

Get current job status and progress.

**Parameters:**
- `job_id` (str): Job identifier

**Returns:**
```python
{
    "job_id": "abc-123",
    "status": "processing",  # pending, processing, completed, failed, cancelled
    "progress": {
        "total_conversations": 50,
        "completed_conversations": 10,
        "total_turns": 55,
        "completed_turns": 12,
        "percent_complete": 21.8
    }
}
```

**Status Values:**
- `pending` - Job queued, not started yet
- `processing` - Worker actively executing
- `completed` - Successfully finished
- `failed` - Execution error
- `cancelled` - User cancelled the job

---

### `wait_for_completion(job_id, poll_interval=30) -> dict`

Wait for job to complete (blocks until done).

**Parameters:**
- `job_id` (str): Job identifier
- `poll_interval` (int): Seconds between status checks

**Returns:**
- Result dictionary with download URLs

**Example:**
```python
result = client.wait_for_completion(job_id, poll_interval=30)
```

---

### `get_result(job_id) -> dict`

Get job result with download URLs.

**Parameters:**
- `job_id` (str): Job identifier

**Returns:**
```python
{
    "job_id": "abc-123",
    "status": "completed",
    "output_csv_url": "https://s3.../output.csv?X-Amz-...",
    "report_url": "https://s3.../report.json?X-Amz-...",
    "expires_at": "2026-02-10T15:45:00Z",
    "summary": {
        "total_turns": 55,
        "successful_turns": 53,
        "failed_turns": 2
    }
}
```

---

### `list_jobs(limit=50, status_filter=None) -> list`

List all evaluation jobs for current user.

**Parameters:**
- `limit` (int): Maximum number of jobs to return (1-100, default: 50)
- `status_filter` (str): Filter by status (pending, processing, completed, failed, cancelled)

**Returns:**
- List of job summaries

**Example:**
```python
# List all jobs
all_jobs = client.list_jobs()

# List only completed jobs
completed = client.list_jobs(status_filter="completed")

# List recent 20 jobs
recent = client.list_jobs(limit=20)

# Each job contains:
# {
#   "job_id": "abc-123",
#   "status": "completed",
#   "submitted_at": "2026-02-10T19:00:00Z",
#   "total_conversations": 50,
#   "total_turns": 55
# }
```

---

### `cancel_job(job_id) -> dict`

Cancel a running or pending evaluation job.

**Parameters:**
- `job_id` (str): Job identifier to cancel

**Returns:**
- Updated job status with cancellation details

**Example:**
```python
result = client.cancel_job(job_id)
print(f"Cancelled at: {result['cancelled_at']}")

# Returns:
# {
#   "job_id": "abc-123",
#   "status": "cancelled",
#   "cancelled_at": "2026-02-10T20:30:00Z",
#   "progress": {...}
# }
```

**Note:** Cannot cancel jobs with status `completed` or `failed`.

---

### `download_results(result, output_file) -> str`

Download result CSV from presigned URL.

**Parameters:**
- `result` (dict): Result dictionary from `get_result()`
- `output_file` (str): Local path to save CSV

**Returns:**
- Path to downloaded file

---

### `submit_and_wait(csv_file, config, output_file="results.csv") -> str`

Convenience method: submit, wait, and download in one call.

**Parameters:**
- `csv_file` (str): Input CSV path
- `config` (dict): Job configuration
- `output_file` (str): Output CSV path

**Returns:**
- Path to downloaded results file

**This is the simplest migration path from bulk_evals.py!**

---

## Performance Comparison

| Metric | bulk_evals.py (OLD) | fifo_client.py (NEW) |
|--------|---------------------|----------------------|
| **Submission Time** | Blocks until complete | <1 second |
| **Max Prompts** | ~10 (timeout at 60s) | 10,000 per job |
| **990 Prompts** | ❌ 100% failure rate | ✅ 0% failure rate |
| **Execution Time (990)** | Timeout | ~85 minutes |
| **Progress Tracking** | ❌ None | ✅ Real-time |
| **Multi-Turn** | ✅ Supported | ✅ Supported |
| **Maxim Integration** | ✅ Supported | ✅ Supported |

---

## Troubleshooting

### Error: "Job failed"

**Check the error message:**
```python
try:
    result = client.wait_for_completion(job_id)
except Exception as e:
    print(f"Error: {e}")
    # Check last status for details
    status = client.get_status(job_id)
    print(status)
```

### Error: "Results not ready"

Wait for job to complete before calling `get_result()`:
```python
status = client.get_status(job_id)
if status["status"] == "completed":
    result = client.get_result(job_id)
else:
    print(f"Still processing: {status['progress']['percent_complete']:.1f}%")
```

### Error: "CSV file not found"

Use absolute paths:
```python
from pathlib import Path

csv_file = Path("test.csv").resolve()
job_id = client.submit_evaluation(str(csv_file), config={...})
```

### Error: "CSV missing required column"

Your CSV must have at least one of these input columns:
- `input`, `prompt`, `user_message`, or `message`

Example fix:
```csv
# ❌ Wrong - no input column
id,query,answer
1,Test,Response

# ✅ Correct - has 'input' column
id,input,answer
1,Test,Response
```

### Error: "CSV has too many rows"

Maximum 10,000 rows per job. Split large files:

```python
# Split into chunks of 10,000 rows each
import pandas as pd

df = pd.read_csv("large_file.csv")
chunk_size = 10000

for i, chunk_df in enumerate(df.groupby(df.index // chunk_size)):
    chunk_df[1].to_csv(f"chunk_{i}.csv", index=False)

    # Submit each chunk
    job_id = client.submit_evaluation(f"chunk_{i}.csv", config={...})
    print(f"Submitted chunk {i}: {job_id}")
```

### Warning: "Mixed conversation structure"

This is informational - your CSV has both multi-turn and single-turn conversations:

```
⚠️  CSV Validation Warnings:
   • Mixed conversation structure: 5 multi-turn, 45 single-turn conversations.
```

This is normal! The client will handle both correctly.

---

## FAQ

### Q: Do I need to update my CSV format?

**No!** The CSV format is the same. The client handles everything transparently.

### Q: Can I cancel a running job?

**Yes!** Use `client.cancel_job(job_id)` to cancel pending or processing jobs:

```python
result = client.cancel_job(job_id)
print(f"Cancelled: {result['status']}")
```

Note: Cannot cancel jobs that are already `completed` or `failed`.

### Q: How long do result URLs last?

Presigned URLs expire after 15 minutes. Download promptly after `get_result()`.

### Q: Can I submit multiple jobs?

Yes! Each job gets a unique job_id. They'll be processed in FIFO order.

Use `client.list_jobs()` to see all your jobs:

```python
jobs = client.list_jobs()
for job in jobs:
    print(f"{job['job_id']}: {job['status']}")
```

### Q: How do I see all my evaluation jobs?

Use `client.list_jobs()` to list all jobs, with optional filtering:

```python
# All jobs
all_jobs = client.list_jobs()

# Only completed
completed = client.list_jobs(status_filter="completed")

# Only in-progress
active = client.list_jobs(status_filter="processing")
```

### Q: What happened to bulk_evals.py?

It's still there for backward compatibility but deprecated. Migrate to fifo_client.py.
