# Bulk Evaluations

This package provides bulk evaluation functionality for AdoptXchange using the Maxim evaluation platform.

## Overview

The `evals` package allows you to:

- Test multiple scenarios against AdoptXchange agents
- Evaluate responses using Maxim's Bias and Semantic Similarity evaluators
- Export results to CSV files for analysis
- Integrate directly with Adopt API endpoints
- **Optimized Performance**: Reuses authentication tokens for faster bulk evaluations
- **Custom Field Filtering**: Exclude unwanted fields from responses for cleaner evaluations
- **Flexible Configuration**: Command-line options for custom CSV files and field exclusion

## Setup

1. **Install dependencies:**
   ```bash
   poetry install
   ```

2. **Configure environment variables in `.env`:**
   ```env
   MAXIM_API_KEY=your-maxim-api-key
   MAXIM_WORKSPACE_ID=your-workspace-id
   ADOPT_CLIENT_ID=your-adopt-client-id
   ADOPT_CLIENT_SECRET=your-adopt-client-secret
   ADOPT_API_ENDPOINT=https://connect.adopt.ai
   ```

3. **Set up your Adopt profile** (`examples/adopt_profile.json`):
   - See main README.md "Configuration Files" section for details
   - This file contains platform URLs and security parameters
   - Required for agent execution

## Usage

### 1. Prepare Test Data

Create `evals/test_data.csv` with your test scenarios:

```csv
Input,Expected_output
"show me all actions","Device Management\n- List All Devices\n- Get Vehicle Current Location\n..."
"get device status","{\"status\": \"str\", \"devices\": [\"str\"]}"
```

**Note:** Use quotes around multi-line content and `\n` for newlines in expected output.

### 2. Run Evaluation

**Basic Usage:**
```bash
poetry run python evals/bulk_evals.py
```

**Advanced Usage:**
```bash
# Exclude specific fields from the response
poetry run python evals/bulk_evals.py --exclude-fields header_message,footer_message

# Use custom CSV file
poetry run python evals/bulk_evals.py --csv-file path/to/custom_data.csv

# Set timeout for slow responses (30 seconds)
poetry run python evals/bulk_evals.py --timeout 30.0

# Limit arrays to first 5 items
poetry run python evals/bulk_evals.py --max-items 5

# Increase parallel processing batch size
poetry run python evals/bulk_evals.py --batch-size 20

# Configure retry attempts for 503/504 errors
poetry run python evals/bulk_evals.py --max-retries 5

# Skip Maxim evaluation (local validation only, faster)
poetry run python evals/bulk_evals.py --skip-maxim

# Run Maxim evaluation on existing results
poetry run python evals/bulk_evals.py --maxim-only evals/evaluation_results_20260126_143022.csv

# Full customization
poetry run python evals/bulk_evals.py \
  --csv-file production_tests.csv \
  --exclude-fields id,timestamp,metadata \
  --timeout 30.0 \
  --max-items 10 \
  --batch-size 15

# View all available options
poetry run python evals/bulk_evals.py --help
```

**Performance Note**: The evaluation process is optimized to reuse authentication tokens, significantly reducing overhead for bulk operations. You'll see a single authentication message at the start, then all test cases will use the same token.

### 3. View Results

- **Maxim Dashboard:** Check the provided link for detailed evaluation results
- **CSV Export:** Find timestamped CSV files in `evals/evaluation_results_*.csv`

## Validation Features

The bulk evaluation system provides multiple layers of automatic validation:

### 1. Schema Validation

Automatically validates that the actual response structure matches the expected schema:

**How it works:**
- Extracts schema (keys, types, nested structures) from `Expected_output`
- Compares actual response schema against expected schema
- Reports missing keys, unexpected keys, and type mismatches

**Example:**
```csv
Input,Expected_output
"Get user info","{\"id\": \"str\", \"name\": \"str\", \"age\": \"int\", \"active\": \"bool\"}"
```

**Validation results:**
- ✅ Pass: `{"id": "user123", "name": "John", "age": 30, "active": true}`
- ❌ Fail: `{"id": 123, "username": "John"}` → Errors: `.name: Missing required key`, `.age: Missing required key`, `.username: Unexpected key`

### 2. Tracing Validation

Compares the `debug_tracing` workflow steps to ensure the agent followed the correct execution path:

**How it works:**
- Extracts and normalizes `debug_tracing` from both expected and actual outputs
- Compares step sequences, tool calls, and execution order
- Identifies missing steps, extra steps, or incorrect order

**Use case:** Verify that the agent used the right sequence of API calls, tools, or decision steps

### 3. Maxim Evaluators (Optional)

When not using `--skip-maxim`, the system also runs:
- **Bias Evaluator**: Detects biased or problematic content (score: 0=no bias, 1=high bias)
- **General LLM Judge**: Uses an LLM to evaluate semantic correctness between expected and actual answers (more accurate than embedding-based similarity)

## CSV Output Format

The generated CSV contains comprehensive evaluation results:

**Input columns:**
- **`input`**: Original test input query
- **`expected_output`**: Expected response (with escaped newlines)

**Output columns:**
- **`actual_output`**: Actual AdoptXchange response (with escaped newlines)

**Validation columns:**
- **`schema_valid`**: Schema validation result ("yes"/"no")
- **`schema_errors`**: Detailed schema validation errors (if any)
- **`tracing_valid`**: Debug tracing validation result ("yes"/"no")
- **`tracing_errors`**: Detailed tracing comparison errors (if any)

**Maxim evaluation columns (if not using --skip-maxim):**
- **`bias`**: Bias evaluation score (0-1 scale, lower is better)
- **`similarity`**: Semantic similarity pass/fail ("yes"/"no")

## Configuration

### Command-Line Arguments

The bulk evaluation script supports the following command-line arguments:

| Argument | Type | Description | Default |
|----------|------|-------------|---------|
| `--csv-file` | `str` | Path to the CSV file with test data | `evals/test_data.csv` |
| `--exclude-fields` | `str` | Comma-separated list of fields to exclude from responses | None |
| `--timeout` | `float` | Timeout in seconds for each LLM response. If exceeded, marks as "timed out" | None |
| `--max-items` | `int` | Maximum number of items to keep in arrays/lists from responses | None |
| `--batch-size` | `int` | Number of prompts to process in parallel | `10` |
| `--max-retries` | `int` | Maximum retry attempts for 503/504 HTTP errors | `3` |
| `--skip-maxim` | flag | Skip all Maxim evaluation runs. Results saved to CSV without Maxim scores | `False` |
| `--maxim-only` | `str` | Skip batch processing and only run Maxim eval on existing CSV file | None |

**Examples:**
```bash
# Basic with field exclusion
python evals/bulk_evals.py --exclude-fields header_message,footer_message,id

# Performance optimization
python evals/bulk_evals.py --timeout 30.0 --max-items 5 --batch-size 20

# Local-only validation (no Maxim API calls)
python evals/bulk_evals.py --skip-maxim

# Re-evaluate existing results with Maxim
python evals/bulk_evals.py --maxim-only evals/evaluation_results_20260126_143022.csv
```

### Field Exclusion Feature

The custom JSON serializer allows you to filter out unwanted fields from API responses. This is useful for:

- **Reducing noise**: Remove formatting fields like `header_message`, `footer_message`
- **Focusing on data**: Exclude metadata fields like `id`, `timestamp`, `version`
- **Cleaner evaluations**: Get more relevant evaluation scores by focusing on core content

**How it works:**
- The serializer recursively filters all specified fields from nested JSON structures
- Works with dictionaries, lists, and nested combinations
- Fields are removed at all levels of the response hierarchy

**Example transformation:**
```json
// Before filtering (exclude: header_message, footer_message, id)
{
  "header_message": "Device Report",
  "data": [
    {"id": "dev001", "name": "Device A", "status": "online"}
  ],
  "footer_message": "End of report"
}

// After filtering
{
  "data": [
    {"name": "Device A", "status": "online"}
  ]
}
```

### Required Environment Variables

- **Adopt (required):** `ADOPT_CLIENT_ID`, `ADOPT_CLIENT_SECRET`, `ADOPT_API_ENDPOINT`
- **Maxim (optional, only if not using --skip-maxim):** `MAXIM_API_KEY`, `MAXIM_WORKSPACE_ID`

## When to Use Each Mode

### Standard Mode (default)
Run all validations + Maxim evaluation:
```bash
python evals/bulk_evals.py
```
**Use when:** You want comprehensive evaluation including semantic similarity and bias detection

### Skip Maxim Mode (--skip-maxim)
Run local validations only (schema, tracing, style):
```bash
python evals/bulk_evals.py --skip-maxim
```
**Use when:**
- Rapid iteration during development
- No Maxim API access or avoiding API costs
- Only need structural/workflow validation
- Faster feedback loop

### Maxim-Only Mode (--maxim-only)
Re-run Maxim evaluation on existing results:
```bash
python evals/bulk_evals.py --maxim-only evals/evaluation_results_20260126_143022.csv
```
**Use when:**
- You have CSV results from a previous run
- Want to add Maxim scores without re-running agents
- Testing different Maxim evaluator configurations


## Best Practices

### Test Data Preparation

1. **Use JSON for structured responses:**
   ```csv
   Input,Expected_output
   "Get device info","{\"device_id\": \"str\", \"status\": \"str\", \"location\": {\"lat\": \"float\", \"lon\": \"float\"}}"
   ```

2. **Include debug_tracing for workflow validation:**
   ```csv
   Input,Expected_output
   "Create segment","{'debug_tracing': [{'step': 'authentication'}, {'step': 'validate_input'}, {'step': 'create_segment'}]}"
   ```

3. **Use schema notation for flexible type checking:**
   - Use type names instead of actual values: `"str"`, `"int"`, `"float"`, `"bool"`, `"NoneType"`
   - Schema validation will check structure, not exact values

### Performance Optimization

1. **Filter unnecessary fields:**
   ```bash
   # Remove noise from responses
   --exclude-fields header_message,footer_message,id,timestamp,version,metadata
   ```

2. **Set appropriate timeouts:**
   ```bash
   # Prevent hanging on slow responses
   --timeout 30.0
   ```

3. **Limit large arrays:**
   ```bash
   # Only evaluate first N items of large lists
   --max-items 10
   ```

4. **Adjust batch size based on your system:**
   ```bash
   # Increase for faster processing (if network/API can handle it)
   --batch-size 20
   
   # Decrease if you see rate limiting or connection errors
   --batch-size 5
   ```

### Development Workflow

1. **Start with --skip-maxim during development:**
   ```bash
   # Fast iteration with local validation only
   python evals/bulk_evals.py --skip-maxim --timeout 20.0
   ```

2. **Add Maxim evaluation when ready:**
   ```bash
   # Run full evaluation suite
   python evals/bulk_evals.py
   ```

3. **Re-evaluate with Maxim if needed:**
   ```bash
   # Add Maxim scores to existing results
   python evals/bulk_evals.py --maxim-only evals/evaluation_results_20260126_143022.csv
   ```

### Troubleshooting

**Problem:** Tests timing out frequently
```bash
# Solution: Increase timeout
python evals/bulk_evals.py --timeout 60.0
```

**Problem:** Getting 503/504 errors
```bash
# Solution: Reduce batch size and increase retries
python evals/bulk_evals.py --batch-size 5 --max-retries 5
```

**Problem:** Schema validation failing unexpectedly
- Check that expected_output uses type names ("str", "int") not actual values
- Ensure JSON is properly formatted and escaped in CSV
- Review schema_errors column in output CSV for details

**Problem:** Large response comparisons taking too long
```bash
# Solution: Limit array sizes and filter fields
python evals/bulk_evals.py --max-items 5 --exclude-fields metadata,debug_info
```

## File Structure

```
evals/
├── README.md                    # This documentation
├── bulk_evals.py               # Main evaluation script with CLI support
├── test_data.csv               # Sample test data (Input, Expected_output)
└── evaluation_results_*.csv    # Generated results (timestamped)
```

## Integration with AdoptXchange

The evaluation system integrates directly with your AdoptXchange deployment:

- **Profile Configuration**: Uses `examples/adopt_profile.json` for agent configuration
- **API Integration**: Connects to your Adopt API endpoint
- **Action Testing**: Tests actual AdoptXchange actions and workflows
- **Real Responses**: Evaluates genuine agent responses, not mock data
- **Token Optimization**: Reuses authentication tokens across all test cases
- **Response Filtering**: Custom field exclusion for focused evaluations

## Quick Reference

### Common Commands
```bash
# Basic evaluation (all features)
python evals/bulk_evals.py

# Fast development mode (no Maxim)
python evals/bulk_evals.py --skip-maxim --timeout 20.0

# Exclude formatting fields for cleaner comparison
python evals/bulk_evals.py --exclude-fields header_message,footer_message,id,timestamp

# Use custom test data
python evals/bulk_evals.py --csv-file my_tests.csv

# Performance-optimized configuration
python evals/bulk_evals.py \
  --timeout 30.0 \
  --max-items 10 \
  --batch-size 15 \
  --exclude-fields metadata,version

# Re-run Maxim evaluation on existing results
python evals/bulk_evals.py --maxim-only evals/evaluation_results_20260126_143022.csv

# Full production configuration
python evals/bulk_evals.py \
  --csv-file production_tests.csv \
  --exclude-fields id,timestamp,metadata,version \
  --timeout 45.0 \
  --max-items 20 \
  --batch-size 10 \
  --max-retries 5
```

### Field Exclusion Tips
- Use comma-separated field names (no spaces)
- Field names are case-sensitive
- Excludes fields at all nesting levels recursively
- Common fields to exclude: `index`, `parentIndex`, `id`, `timestamp`, `version`, `metadata`, `header_message`, `footer_message`
- Helps focus evaluation on actual content rather than formatting

### Output Files
- **Raw results:** `evals/evaluation_results_YYYYMMDD_HHMMSS.csv`
- Contains all validation columns and Maxim scores (if applicable)
- Newlines in output are escaped as `\n` for CSV compatibility
- Can be opened in Excel, Google Sheets, or any CSV viewer
