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

## Usage

### 1. Prepare Test Data

Create `evals/test_data.csv` with your test scenarios:

```csv
Input,Expected_output
"show me all actions","Device Management\n- List All Devices\n- Get Vehicle Current Location\n..."
```

**Note:** Use quotes around multi-line content and `\n` for newlines in expected output.

### 2. Run Evaluation

**Basic Usage:**
```bash
poetry run python evals/bulk_evals.py
```

**Advanced Usage with Field Exclusion:**
```bash
# Exclude specific fields from the response
poetry run python evals/bulk_evals.py --exclude-fields header_message,footer_message

# Use custom CSV file
poetry run python evals/bulk_evals.py --csv-file path/to/custom_data.csv

# Combine options
poetry run python evals/bulk_evals.py --csv-file custom.csv --exclude-fields id,timestamp

# View all available options
poetry run python evals/bulk_evals.py --help
```

**Performance Note**: The evaluation process is optimized to reuse authentication tokens, significantly reducing overhead for bulk operations. You'll see a single authentication message at the start, then all test cases will use the same token.

### 3. View Results

- **Maxim Dashboard:** Check the provided link for detailed evaluation results
- **CSV Export:** Find timestamped CSV files in `evals/evaluation_results_*.csv`

## CSV Output Format

The generated CSV contains:

- **`input`**: Original test input
- **`expected_output`**: Expected response (with escaped newlines)
- **`actual_output`**: Actual AdoptXchange response (with escaped newlines)
- **`bias`**: Bias evaluation score (0-1 scale)
- **`similarity`**: Semantic similarity pass/fail ("yes"/"no")

## Configuration

### Command-Line Arguments

The bulk evaluation script supports the following command-line arguments:

| Argument | Description | Default |
|----------|-------------|---------|
| `--csv-file` | Path to the CSV file with test data | `evals/test_data.csv` |
| `--exclude-fields` | Comma-separated list of fields to exclude from responses | None |

**Example:**
```bash
python evals/bulk_evals.py --exclude-fields header_message,footer_message,id
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

- **Maxim:** `MAXIM_API_KEY`, `MAXIM_WORKSPACE_ID`
- **Adopt:** `ADOPT_CLIENT_ID`, `ADOPT_CLIENT_SECRET`, `ADOPT_API_ENDPOINT`

## Evaluators

- **Bias Evaluator**: Detects biased content (score: 0=no bias, 1=high bias)
- **Ragas Answer Semantic Similarity**: Measures response relevance (pass/fail based on similarity threshold)


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
# Basic evaluation
python evals/bulk_evals.py

# Exclude formatting fields
python evals/bulk_evals.py --exclude-fields header_message,footer_message

# Use custom test data
python evals/bulk_evals.py --csv-file my_tests.csv

# Full customization
python evals/bulk_evals.py --csv-file production_tests.csv --exclude-fields id,timestamp,metadata
```

### Field Exclusion Tips
- Use comma-separated field names (no spaces)
- Field names are case-sensitive
- Excludes fields at all nesting levels
- Common fields to exclude: `index`, `parentIndex`, `id`, `timestamp`, `version`
