# Bulk Evaluations

This package provides bulk evaluation functionality for AdoptXchange using the Maxim evaluation platform.

## Overview

The `evals` package allows you to:

- Test multiple scenarios against AdoptXchange agents
- Evaluate responses using Maxim's Bias and Semantic Similarity evaluators
- Export results to CSV files for analysis
- Integrate directly with Adopt API endpoints

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

```bash
poetry run python evals/bulk_evals.py
```

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

### Custom CSV File

Update the path in `bulk_evals.py`:

```python
csv_file_path = "evals/your_test_data.csv"
```

### Required Environment Variables

- **Maxim:** `MAXIM_API_KEY`, `MAXIM_WORKSPACE_ID`
- **Adopt:** `ADOPT_CLIENT_ID`, `ADOPT_CLIENT_SECRET`, `ADOPT_API_ENDPOINT`

## Evaluators

- **Bias Evaluator**: Detects biased content (score: 0=no bias, 1=high bias)
- **Ragas Answer Semantic Similarity**: Measures response relevance (pass/fail based on similarity threshold)