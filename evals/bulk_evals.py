#!/usr/bin/env python3
"""Bulk evaluation functionality using maxim-py for AdoptXchange."""

import os
import sys
import logging
import pandas as pd
import json
import ast
import requests
import argparse
import time
import uuid
from typing import List, Any, Dict, Union, Tuple
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError, as_completed
from contextlib import contextmanager

# Auto-add project root to Python path so imports work from any directory
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from maxim import maxim
from maxim.models import YieldedOutput
from examples import read_env
from examples.action_api_samples.api_sample import run_simple_action, load_adopt_profile, get_auth_token
from langchain_core.messages import HumanMessage


@contextmanager
def suppress_maxim_logs():
    """Context manager to suppress verbose Maxim SDK output."""
    # Suppress logging from maxim module
    maxim_logger = logging.getLogger("maxim")
    original_level = maxim_logger.level
    maxim_logger.setLevel(logging.ERROR)
    
    # Also suppress stdout prints from the SDK
    class OutputFilter:
        def __init__(self, original_stdout):
            self.original_stdout = original_stdout
            
        def write(self, text):
            # Filter out the verbose "Overriding context_to_evaluate" messages
            if "Overriding context_to_evaluate" not in text:
                self.original_stdout.write(text)
                
        def flush(self):
            self.original_stdout.flush()
    
    original_stdout = sys.stdout
    sys.stdout = OutputFilter(original_stdout)
    
    try:
        yield
    finally:
        # Restore original settings
        sys.stdout = original_stdout
        maxim_logger.setLevel(original_level)

# Constants for batch processing
MAX_PARALLEL_PROMPTS = 10
RETRYABLE_STATUS_CODES = [401, 503, 504]
MAX_RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5

# Get environment variables
adopt_env = read_env()

# Initialize Maxim SDK
maxim_client = maxim.Maxim({"api_key": adopt_env.MAXIM_API_KEY })


class RetryableHTTPError(Exception):
    """Exception raised for retryable HTTP errors (401, 503, 504)."""
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"HTTP {status_code}: {message}")

def filter_json_fields(data: Union[Dict, List, Any], exclude_fields: List[str]) -> Union[Dict, List, Any]:
    """
    Custom serializer that filters out specified fields from JSON data.
    
    Args:
        data: The JSON data (dict, list, or primitive) to filter
        exclude_fields: List of field names to exclude from the result
        
    Returns:
        Filtered data with excluded fields removed
    """
    if not exclude_fields:
        return data
    
    if isinstance(data, dict):
        # Create a new dict excluding specified fields
        filtered_dict = {}
        for key, value in data.items():
            if key not in exclude_fields:
                # Recursively filter nested structures
                filtered_dict[key] = filter_json_fields(value, exclude_fields)
        return filtered_dict
    
    elif isinstance(data, list):
        # Recursively filter each item in the list
        return [filter_json_fields(item, exclude_fields) for item in data]
    
    else:
        # Return primitive values as-is
        return data

def load_test_data_from_csv(csv_file_path: str) -> list:
    """
    Load test data from a CSV file with columns: input, expected_output
    (case-insensitive - accepts Input/Expected_output or input/expected_output)
    Skips blank rows and rows with empty input or expected_output.

    Args:
        csv_file_path: Path to the CSV file

    Returns:
        List of test data dictionaries
    """
    if not os.path.exists(csv_file_path):
        raise FileNotFoundError(f"CSV file not found: {csv_file_path}")

    # Read CSV file, skip blank lines
    df = pd.read_csv(csv_file_path, skip_blank_lines=True)

    # Normalize column names to lowercase for case-insensitive matching
    df.columns = df.columns.str.lower().str.strip()
    
    # Validate required columns (now lowercase)
    required_columns = ["input", "expected_output"]
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(f"CSV file missing required columns: {missing_columns}")

    # Drop rows with empty/NaN values in required columns
    original_count = len(df)
    df = df.dropna(subset=["input", "expected_output"])
    
    # Also drop rows where input or expected_output is just whitespace
    df = df[df["input"].astype(str).str.strip() != ""]
    df = df[df["expected_output"].astype(str).str.strip() != ""]
    df = df[df["input"].astype(str).str.lower() != "nan"]
    df = df[df["expected_output"].astype(str).str.lower() != "nan"]
    
    skipped_count = original_count - len(df)
    if skipped_count > 0:
        print(f"⚠️  Skipped {skipped_count} blank/invalid rows from CSV")

    # Convert to list of dictionaries
    test_data = []
    for _, row in df.iterrows():
        test_data.append({
            "input": str(row["input"]).strip(),
            "expected_output": str(row["expected_output"]).strip(),
            "context": "",  # Optional context column, default to empty
        })
    return test_data


# Default CSV file path - will be overridden by CLI args if provided
default_csv_file_path = "evals/test_data.csv"


def call_local_agent(data, profile, access_token, exclude_fields: List[str] = None, timeout: float = None, max_items: int = None):
    """Function to call your local agent endpoint using Adopt API
    
    Args:
        data: Input data dictionary
        profile: Adopt profile configuration
        access_token: Authentication token
        exclude_fields: List of field names to exclude from the response
        timeout: Optional timeout in seconds. If the call takes longer, returns "timed out"
        max_items: Optional maximum number of items to keep in arrays/lists (e.g., 5 for first 5 items)
    """
    try:
        # Generate a unique trace ID for this prompt to create a new conversation context
        trace_id = str(uuid.uuid4())
        
        # Modify the input to include max_items instruction if specified
        modified_input = data["input"]
        if max_items is not None and max_items > 0:
            # Append instruction to limit results in the prompt
            modified_input = f"{data['input']}\n\nPlease limit your response to only the first {max_items} items if returning a list, table, or array of results."
        
        # If timeout is specified, wrap the call in a ThreadPoolExecutor with timeout
        if timeout is not None and timeout > 0:
            with ThreadPoolExecutor(max_workers=3) as executor:
                future = executor.submit(run_simple_action, modified_input, profile, access_token, trace_id)
                try:
                    response = future.result(timeout=timeout)
                except FutureTimeoutError:
                    # Timeout occurred, return "timed out" as the response
                    return YieldedOutput(
                        data="timed out",
                        retrieved_context_to_evaluate=data.get("context", ""),
                    )
        else:
            # No timeout specified, call directly
            response = run_simple_action(modified_input, profile, access_token, trace_id)

        # Parse the response if it's a string representation of a list
        try:
            # Try to parse the response as a Python literal (list/dict)
            parsed_response = ast.literal_eval(response)
            
            # Apply field filtering if exclude_fields is provided
            if exclude_fields:
                parsed_response = filter_json_fields(parsed_response, exclude_fields)
            
            # If it's a list with dict elements, extract and combine header, data, and footer
            if isinstance(parsed_response, list) and len(parsed_response) > 0:
                first_item = parsed_response[0]
                if isinstance(first_item, dict):
                    # Initialize parts of the response
                    response_parts = []
                    
                    # Add header_message if present
                    if 'header_message' in first_item and first_item['header_message']:
                        response_parts.append(first_item['header_message'])
                    
                    # Add data field
                    if 'data' in first_item:
                        data_field = first_item['data']
                        
                        # If data field is a list of dicts, convert to readable string
                        if isinstance(data_field, list):
                            data_strings = []
                            for item in data_field:
                                if isinstance(item, dict):
                                    # Convert dict to readable key-value pairs
                                    item_str = ', '.join([f"{k}: {v}" for k, v in item.items()])
                                    data_strings.append(item_str)
                                else:
                                    data_strings.append(str(item))
                            response_parts.append('\n'.join(data_strings))
                        else:
                            response_parts.append(str(data_field))
                    
                    # Add footer_message if present
                    if 'footer_message' in first_item and first_item['footer_message']:
                        response_parts.append(first_item['footer_message'])
                    
                    # Combine all parts with double newlines for readability
                    response_data = '\n\n'.join(response_parts)
                else:
                    response_data = response
            else:
                response_data = response
        except (ValueError, SyntaxError):
            # If parsing fails, use the original response
            response_data = response
        # Return the agent's response in the expected YieldedOutput format
        return YieldedOutput(
            data=response_data,
            retrieved_context_to_evaluate=data.get("context", ""),
        )

    except ValueError as e:
        error_str = str(e)
        # Check for retryable HTTP status codes (503, 504)
        for status_code in RETRYABLE_STATUS_CODES:
            if f"status code {status_code}" in error_str:
                raise RetryableHTTPError(status_code, error_str)
        # Return error information in YieldedOutput format for non-retryable errors
        return YieldedOutput(
            data=f"Error: {error_str}",
            retrieved_context_to_evaluate=data.get("context", ""),
        )
    except Exception as e:
        # Return error information in YieldedOutput format
        return YieldedOutput(
            data=f"Error: {str(e)}",
            retrieved_context_to_evaluate=data.get("context", ""),
        )


def process_single_batch(
    batch_data: List[Dict],
    call_agent_func,
    max_parallel: int,
    max_retries: int,
    retry_counts: Dict[str, int],
    error_log: List[Dict]
) -> Tuple[List[Tuple[Dict, YieldedOutput]], List[Dict]]:
    """
    Process a single batch of prompts with parallel execution.
    
    Args:
        batch_data: List of test data dictionaries for this batch
        call_agent_func: Function to call for each prompt
        max_parallel: Maximum number of prompts to process in parallel
        max_retries: Maximum number of retry attempts
        retry_counts: Dictionary tracking retry counts by input string
        error_log: List to append error information to
    
    Returns:
        Tuple of (successful_results, failed_prompts_to_retry)
    """
    batch_results = []
    failed_prompts = []
    
    # Process batch in parallel using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max_parallel) as executor:
        # Submit all tasks
        future_to_data = {
            executor.submit(call_agent_func, data): data 
            for data in batch_data
        }
        
        # Collect results as they complete
        for future in as_completed(future_to_data):
            data = future_to_data[future]
            input_key = data["input"]
            try:
                result = future.result()
                # Check if the result itself contains an error
                if result.data and str(result.data).startswith("Error:"):
                    error_log.append({
                        "input": input_key[:100] + "..." if len(input_key) > 100 else input_key,
                        "error": str(result.data)
                    })
                batch_results.append((data, result))
            except RetryableHTTPError as e:
                # Track retry count by input string
                current_retries = retry_counts.get(input_key, 0)
                truncated_input = input_key[:80] + "..." if len(input_key) > 80 else input_key
                if current_retries < max_retries:
                    retry_counts[input_key] = current_retries + 1
                    print(f"  ⚠️  HTTP {e.status_code} - will retry (attempt {retry_counts[input_key]}/{max_retries})")
                    print(f"      Prompt: {truncated_input}")
                    failed_prompts.append(data)
                else:
                    # Max retries exceeded, add error result
                    error_msg = f"Error after {max_retries} retries: HTTP {e.status_code}"
                    print(f"  ❌ HTTP {e.status_code} - max retries exceeded")
                    print(f"      Prompt: {truncated_input}")
                    error_log.append({
                        "input": input_key[:100] + "..." if len(input_key) > 100 else input_key,
                        "error": error_msg
                    })
                    batch_results.append((data, YieldedOutput(
                        data=error_msg,
                        retrieved_context_to_evaluate=data.get("context", ""),
                    )))
            except Exception as e:
                # Non-retryable error
                error_msg = f"Error: {str(e)}"
                truncated_input = input_key[:80] + "..." if len(input_key) > 80 else input_key
                print(f"  ❌ {error_msg}")
                print(f"      Prompt: {truncated_input}")
                error_log.append({
                    "input": input_key[:100] + "..." if len(input_key) > 100 else input_key,
                    "error": error_msg
                })
                batch_results.append((data, YieldedOutput(
                    data=error_msg,
                    retrieved_context_to_evaluate=data.get("context", ""),
                )))
    
    return batch_results, failed_prompts


def send_all_results_to_maxim(
    test_data: List[Dict],
    all_results: List[Tuple[Dict, YieldedOutput]]
) -> str:
    """
    Send all collected results to Maxim for evaluation in a single test run.
    
    Args:
        test_data: Original test data list
        all_results: List of (data, YieldedOutput) tuples with all results
    
    Returns:
        Test run ID if successful, None otherwise
    """
    # Create lookup for precomputed results
    precomputed_results = {}
    for data, output in all_results:
        precomputed_results[data["input"]] = output
    
    # Filter test_data to only include items that have results
    # This ensures we only send data to Maxim that we have precomputed results for
    test_data_with_results = [
        data for data in test_data 
        if data["input"] in precomputed_results
    ]
    
    print(f"  Filtered test_data: {len(test_data)} -> {len(test_data_with_results)} items with results")
    
    def get_precomputed_result(data):
        input_key = data["input"]
        if input_key in precomputed_results:
            return precomputed_results[input_key]
        else:
            return YieldedOutput(
                data="Error: Result not found in precomputed cache",
                retrieved_context_to_evaluate=data.get("context", ""),
            )
    
    try:
        # Suppress verbose "Overriding context_to_evaluate" messages from Maxim SDK
        with suppress_maxim_logs():
            result = (
                maxim_client.create_test_run(
                    name="Local Agent Endpoint Test", 
                    in_workspace_id=adopt_env.MAXIM_WORKSPACE_ID
                )
                .with_data_structure(
                    {
                        "input": "INPUT",
                        "expected_output": "EXPECTED_OUTPUT",
                        "context": "CONTEXT_TO_EVALUATE",
                    }
                )
                .with_data(test_data_with_results)
                .with_evaluators("Bias", "Ragas Answer Semantic Similarity")
                .yields_output(get_precomputed_result)
                .run()
            )
        
        if result is not None and result.test_run_result is not None:
            test_run_id = result.test_run_result.link.split('/')[-1]
            return test_run_id
        else:
            print("⚠️  Maxim returned None - likely a server error")
            return None
    except Exception as e:
        print(f"⚠️  Failed to send results to Maxim: {e}")
        return None


def initialize_raw_csv(csv_filename: str) -> None:
    """Initialize a new CSV file with headers for raw results (without Maxim scores).
    
    Args:
        csv_filename: Path to the CSV file to create
    """
    import csv
    
    with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['input', 'expected_output', 'actual_output', 'bias', 'similarity']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
    
    print(f"📄 Initialized raw results CSV: {csv_filename}")


def append_batch_to_csv(
    csv_filename: str,
    batch_results: List[Tuple[Dict, YieldedOutput]]
) -> None:
    """Append batch results to the CSV file immediately after processing.
    
    Args:
        csv_filename: Path to the CSV file
        batch_results: List of (data, YieldedOutput) tuples from the batch
    """
    import csv
    
    with open(csv_filename, 'a', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['input', 'expected_output', 'actual_output', 'bias', 'similarity']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        for data, output in batch_results:
            # Escape newlines in actual output
            actual_output = str(output.data).replace('\n', '\\n') if output.data else ""
            
            writer.writerow({
                'input': data['input'],
                'expected_output': data['expected_output'],
                'actual_output': actual_output,
                'bias': '',  # Will be filled by Maxim later
                'similarity': ''  # Will be filled by Maxim later
            })


def send_batch_to_maxim_background(
    batch_data: List[Dict],
    batch_results: List[Tuple[Dict, YieldedOutput]],
    batch_number: int
) -> str:
    """
    Send a batch of results to Maxim for evaluation.
    
    Args:
        batch_data: Original test data for this batch
        batch_results: List of (data, YieldedOutput) tuples
        batch_number: The batch number for naming
    
    Returns:
        Test run ID if successful, None otherwise
    """
    # Create lookup for precomputed results
    precomputed_results = {}
    for data, output in batch_results:
        precomputed_results[data["input"]] = output
    
    def get_precomputed_result(data):
        input_key = data["input"]
        if input_key in precomputed_results:
            return precomputed_results[input_key]
        else:
            return YieldedOutput(
                data="Error: Result not found in precomputed cache",
                retrieved_context_to_evaluate=data.get("context", ""),
            )
    
    try:
        with suppress_maxim_logs():
            result = (
                maxim_client.create_test_run(
                    name=f"Local Agent Endpoint Test - Batch {batch_number}", 
                    in_workspace_id=adopt_env.MAXIM_WORKSPACE_ID
                )
                .with_data_structure(
                    {
                        "input": "INPUT",
                        "expected_output": "EXPECTED_OUTPUT",
                        "context": "CONTEXT_TO_EVALUATE",
                    }
                )
                .with_data(batch_data)
                .with_evaluators("Bias", "Ragas Answer Semantic Similarity")
                .yields_output(get_precomputed_result)
                .run()
            )
        
        if result is not None and result.test_run_result is not None:
            test_run_id = result.test_run_result.link.split('/')[-1]
            return test_run_id
        else:
            return None
    except Exception as e:
        print(f"  ⚠️  Maxim error for batch {batch_number}: {e}")
        return None


def update_csv_with_maxim_scores(raw_csv_filename: str, test_run_ids: List[str]) -> str:
    """Update the raw CSV file with Maxim evaluation scores.
    
    Args:
        raw_csv_filename: Path to the raw CSV file (with empty bias/similarity)
        test_run_ids: List of Maxim test run IDs to fetch scores from
    
    Returns:
        Path to the final CSV file with scores
    """
    import csv
    from datetime import datetime
    
    if not test_run_ids:
        print("⚠️  No Maxim test runs to fetch scores from")
        print(f"Raw results are still available in: {raw_csv_filename}")
        return raw_csv_filename
    
    # Fetch all Maxim scores and create a lookup by input
    scores_lookup = {}
    total_entries_fetched = 0
    duplicate_count = 0
    
    for test_run_id in test_run_ids:
        if test_run_id is None:
            continue
        
        print(f"  Fetching scores from test run: {test_run_id}")
        
        entries_response = fetch_all_test_run_entries(
            test_run_id=test_run_id,
            workspace_id=adopt_env.MAXIM_WORKSPACE_ID,
            api_key=adopt_env.MAXIM_API_KEY
        )
        
        if not entries_response or 'data' not in entries_response:
            print(f"    ⚠️  No data in response for {test_run_id}")
            continue
        
        entries = entries_response['data']['entries']
        print(f"    Found {len(entries)} entries")
        total_entries_fetched += len(entries)
        
        for entry in entries:
            # Normalize input text for matching (strip whitespace)
            input_text = entry['input']['payload'].strip()
            
            # Extract scores
            stats = entry.get('stats', {})
            overall_results = stats.get('overallEvaluatorMeanResult', [])
            pass_fail_results = stats.get('overallPassFailResult', [])
            
            bias_score = 0
            for result in overall_results:
                if result['name'] == 'Bias':
                    bias_score = result['value']
                    break
            
            similarity = "no"
            for result in pass_fail_results:
                if result['name'] == 'Ragas Answer Semantic Similarity':
                    similarity = "yes" if result['value']['pass'] else "no"
                    break
            
            # Handle duplicates: keep track of all occurrences but use the latest scores
            if input_text in scores_lookup:
                duplicate_count += 1
                # Keep the latest scores (most recent evaluation)
                # Could also average or keep first, but latest is usually most accurate
            
            scores_lookup[input_text] = {
                'bias': bias_score,
                'similarity': similarity
            }
    
    print(f"\n  Total entries fetched from Maxim: {total_entries_fetched}")
    print(f"  Unique inputs in scores lookup: {len(scores_lookup)}")
    if duplicate_count > 0:
        print(f"  ⚠️  Found {duplicate_count} duplicate inputs (kept latest scores)")
    
    # Read the raw CSV and update with scores
    updated_rows = []
    matched_count = 0
    unmatched_inputs = []
    
    with open(raw_csv_filename, 'r', newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            # Normalize input text for matching (strip whitespace)
            input_text = row['input'].strip()
            
            # Try exact match first
            if input_text in scores_lookup:
                row['bias'] = scores_lookup[input_text]['bias']
                row['similarity'] = scores_lookup[input_text]['similarity']
                matched_count += 1
            else:
                # Try to find a fuzzy match (case-insensitive, normalized whitespace)
                matched = False
                normalized_input = input_text.lower().strip()
                for maxim_input in scores_lookup.keys():
                    normalized_maxim = maxim_input.lower().strip()
                    if normalized_input == normalized_maxim:
                        # Found a case/whitespace variant match
                        row['bias'] = scores_lookup[maxim_input]['bias']
                        row['similarity'] = scores_lookup[maxim_input]['similarity']
                        matched_count += 1
                        matched = True
                        break
                
                if not matched:
                    # Try to find partial match for debugging
                    if len(unmatched_inputs) < 10:  # Show more unmatched for debugging
                        unmatched_inputs.append(input_text)
            updated_rows.append(row)
    
    # Debug: show sample of lookup keys vs CSV inputs if no matches
    if matched_count == 0 and scores_lookup:
        print(f"\n  ⚠️  DEBUG: No matches found!")
        print(f"  Sample Maxim input (first 80 chars): {list(scores_lookup.keys())[0][:80]}...")
        if updated_rows:
            print(f"  Sample CSV input (first 80 chars): {updated_rows[0]['input'][:80]}...")
    
    if unmatched_inputs:
        print(f"  Unmatched CSV inputs ({len(unmatched_inputs)} shown):")
        for i, unmatched in enumerate(unmatched_inputs[:10], 1):
            print(f"    {i}. {unmatched[:80]}{'...' if len(unmatched) > 80 else ''}")
        
        # Show sample of Maxim inputs for comparison
        if scores_lookup:
            print(f"\n  Sample Maxim inputs (first 3):")
            for i, maxim_input in enumerate(list(scores_lookup.keys())[:3], 1):
                print(f"    {i}. {maxim_input[:80]}{'...' if len(maxim_input) > 80 else ''}")
    
    # Write updated data back
    with open(raw_csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['input', 'expected_output', 'actual_output', 'bias', 'similarity']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(updated_rows)
    
    print(f"\n✓ Updated {matched_count}/{len(updated_rows)} rows with Maxim scores")
    
    return raw_csv_filename


def load_existing_results_from_csv(csv_file_path: str) -> Tuple[List[Dict], List[Tuple[Dict, YieldedOutput]]]:
    """
    Load existing results from a CSV file that already has actual_output.
    Used for --maxim-only mode.
    
    Args:
        csv_file_path: Path to the CSV file with existing results
        
    Returns:
        Tuple of (test_data, all_results) ready for Maxim evaluation
    """
    import csv
    
    if not os.path.exists(csv_file_path):
        raise FileNotFoundError(f"CSV file not found: {csv_file_path}")
    
    test_data = []
    all_results = []
    skipped = 0
    
    with open(csv_file_path, 'r', newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        
        for row in reader:
            input_text = row.get('input', '').strip()
            expected_output = row.get('expected_output', '').strip()
            actual_output = row.get('actual_output', '').strip()
            
            # Skip rows with missing data
            if not input_text or not expected_output or not actual_output:
                skipped += 1
                continue
            
            # Skip rows where actual_output is an error
            if actual_output.startswith('Error:'):
                skipped += 1
                continue
            
            data = {
                "input": input_text,
                "expected_output": expected_output,
                "context": "",
            }
            
            # Unescape newlines in actual_output (they were escaped when saving)
            actual_output_unescaped = actual_output.replace('\\n', '\n')
            
            output = YieldedOutput(
                data=actual_output_unescaped,
                retrieved_context_to_evaluate="",
            )
            
            test_data.append(data)
            all_results.append((data, output))
    
    if skipped > 0:
        print(f"⚠️  Skipped {skipped} rows with missing/error data")
    
    return test_data, all_results


def fetch_test_run_entries(test_run_id: str, workspace_id: str, api_key: str, limit: int = 1000, offset: int = 0):
    """Fetch individual test run entries from Maxim API with pagination support"""
    url = "https://api.getmaxim.ai/v1/test-runs/entries"
    
    headers = {
        "x-maxim-api-key": api_key
    }
    
    params = {
        "workspaceId": workspace_id,
        "id": test_run_id,
        "limit": limit,
        "offset": offset
    }
    
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Failed to fetch test run entries: {e}")
        return None


def fetch_all_test_run_entries(test_run_id: str, workspace_id: str, api_key: str):
    """Fetch all test run entries from Maxim API, handling pagination automatically.
    Continues fetching until all entries are retrieved, regardless of count (200, 2000, etc.)
    """
    all_entries = []
    offset = 0
    page_size = 100  # Fetch 100 entries per page
    page_num = 1
    max_pages = 1000  # Safety limit to prevent infinite loops (1000 pages = 100k entries)
    consecutive_empty_pages = 0
    
    while page_num <= max_pages:
        response = fetch_test_run_entries(test_run_id, workspace_id, api_key, limit=page_size, offset=offset)
        
        if not response or 'data' not in response:
            print(f"    ⚠️  No response or data for page {page_num}, stopping")
            break
        
        entries = response['data'].get('entries', [])
        
        # If we got no entries, check if we should stop
        if not entries:
            consecutive_empty_pages += 1
            if consecutive_empty_pages >= 2:  # Stop after 2 consecutive empty pages
                print(f"    Got {consecutive_empty_pages} consecutive empty pages, stopping")
                break
            # Try next page in case of transient issue
            offset += page_size
            page_num += 1
            continue
        
        consecutive_empty_pages = 0  # Reset counter on successful fetch
        all_entries.extend(entries)
        print(f"    Fetched page {page_num}: {len(entries)} entries (total so far: {len(all_entries)})")
        
        # Check if there's pagination metadata indicating more results
        data = response.get('data', {})
        total = data.get('total')  # Total count if provided
        has_more = data.get('hasMore')  # Has more flag if provided
        
        # If we've fetched all entries (total matches what we have), stop
        if total is not None and len(all_entries) >= total:
            print(f"    ✓ Reached total count: {total}")
            break
        
        # If hasMore is explicitly False, stop
        if has_more is False:
            print(f"    ✓ API indicates no more results (hasMore=False)")
            break
        
        # If we got fewer entries than requested, we've reached the end
        if len(entries) < page_size:
            print(f"    ✓ Got fewer entries than page size ({len(entries)} < {page_size}), all entries fetched")
            break
        
        # If we got exactly page_size entries, there might be more - continue to next page
        offset += page_size
        page_num += 1
    
    if page_num > max_pages:
        print(f"    ⚠️  Reached safety limit of {max_pages} pages, stopping")
    
    print(f"    Total entries fetched: {len(all_entries)}")
    
    # Return in the same format as the original function
    return {
        'data': {
            'entries': all_entries
        }
    }


def save_results_to_csv_from_test_runs(test_run_ids: List[str]):
    """Save evaluation results from multiple test runs to a single CSV file.
    
    Args:
        test_run_ids: List of Maxim test run IDs to fetch and combine
    """
    import csv
    from datetime import datetime
    
    if not test_run_ids:
        print("No test run IDs to save")
        return
    
    # Generate timestamp for unique filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_filename = f"evals/evaluation_results_{timestamp}.csv"
    
    # Collect all entries from all test runs
    all_csv_data = []
    
    for test_run_id in test_run_ids:
        print(f"Fetching entries for test run: {test_run_id}")
        
        # Fetch detailed entries from Maxim API
        entries_response = fetch_all_test_run_entries(
            test_run_id=test_run_id,
            workspace_id=adopt_env.MAXIM_WORKSPACE_ID,
            api_key=adopt_env.MAXIM_API_KEY
        )
        
        if not entries_response or 'data' not in entries_response:
            print(f"  Failed to fetch entries for test run: {test_run_id}")
            continue
        
        entries = entries_response['data']['entries']
        
        for entry in entries:
            # Extract input, output, and expected output
            input_text = entry['input']['payload']
            actual_output = entry['output']['payload']
            expected_output = entry['expectedOutput']['payload']
            
            # Extract individual evaluator scores
            stats = entry.get('stats', {})
            overall_results = stats.get('overallEvaluatorMeanResult', [])
            pass_fail_results = stats.get('overallPassFailResult', [])
            
            # Find Bias score
            bias_score = 0
            for result in overall_results:
                if result['name'] == 'Bias':
                    bias_score = result['value']
                    break
            
            # Find Similarity pass/fail
            similarity = "no"
            for result in pass_fail_results:
                if result['name'] == 'Ragas Answer Semantic Similarity':
                    similarity = "yes" if result['value']['pass'] else "no"
                    break
            
            # Escape newlines in actual output to match expected output format
            actual_output = actual_output.replace('\n', '\\n')
            
            all_csv_data.append({
                'input': input_text,
                'expected_output': expected_output,
                'actual_output': actual_output,
                'bias': bias_score,
                'similarity': similarity
            })
    
    if not all_csv_data:
        print("No data collected from test runs")
        return
    
    # Write to CSV file
    try:
        with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['input', 'expected_output', 'actual_output', 'bias', 'similarity']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            writer.writeheader()
            writer.writerows(all_csv_data)
        
        print(f"\n{'='*50}")
        print("RESULTS SAVED TO CSV")
        print(f"{'='*50}")
        print(f"Results saved to: {csv_filename}")
        print(f"Total records: {len(all_csv_data)}")
        print(f"From {len(test_run_ids)} test run(s)")
        
    except Exception as e:
        print(f"Failed to save results to CSV: {e}")


def main():
    """Main function to run bulk evaluations sequentially"""
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="Run bulk evaluations for AdoptXchange using Maxim",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with default CSV and no field exclusion
  python evals/bulk_evals.py
  
  # Exclude specific fields from response
  python evals/bulk_evals.py --exclude-fields header_message,footer_message
  
  # Use custom CSV file with field exclusion
  python evals/bulk_evals.py --csv-file path/to/data.csv --exclude-fields id,timestamp
  
  # Set timeout limit (30 seconds)
  python evals/bulk_evals.py --timeout 30.0
  
  # Limit array/table items to first 5 items
  python evals/bulk_evals.py --max-items 5
  
  # Combine options: timeout, field exclusion, and item limit
  python evals/bulk_evals.py --timeout 30.0 --exclude-fields header_message,footer_message --max-items 5
  
  # Custom batch size and retry settings
  python evals/bulk_evals.py --batch-size 5 --max-retries 5
        """
    )
    
    parser.add_argument(
        '--csv-file',
        type=str,
        default=default_csv_file_path,
        help=f'Path to the CSV file with test data (default: {default_csv_file_path})'
    )
    
    parser.add_argument(
        '--exclude-fields',
        type=str,
        default='',
        help='Comma-separated list of field names to exclude from response (e.g., header_message,footer_message,id)'
    )
    
    parser.add_argument(
        '--timeout',
        type=float,
        default=None,
        help='Timeout in seconds for LLM responses. If exceeded, actual_output will be "timed out" (e.g., 30.0)'
    )
    
    parser.add_argument(
        '--max-items',
        type=int,
        default=None,
        help='Maximum number of items to keep in arrays/lists from LLM response (e.g., 5 for first 5 items)'
    )
    
    parser.add_argument(
        '--batch-size',
        type=int,
        default=MAX_PARALLEL_PROMPTS,
        help=f'Maximum number of prompts to process in parallel (default: {MAX_PARALLEL_PROMPTS})'
    )
    
    parser.add_argument(
        '--max-retries',
        type=int,
        default=MAX_RETRY_ATTEMPTS,
        help=f'Maximum retry attempts for 503/504 errors (default: {MAX_RETRY_ATTEMPTS})'
    )
    
    parser.add_argument(
        '--maxim-only',
        type=str,
        default=None,
        metavar='CSV_FILE',
        help='Skip batch processing and only run Maxim evaluation on an existing CSV file with actual_output already filled'
    )
    
    args = parser.parse_args()
    
    # Check for MAXIM API key (always required)
    if not adopt_env.MAXIM_API_KEY:
        raise ValueError("MAXIM_API_KEY environment variable is required")

    if not adopt_env.MAXIM_WORKSPACE_ID:
        raise ValueError("MAXIM_WORKSPACE_ID environment variable is required")
    
    # ==================== MAXIM-ONLY MODE ====================
    if args.maxim_only:
        print("=" * 60)
        print("🔬 MAXIM-ONLY MODE")
        print("=" * 60)
        print(f"Loading existing results from: {args.maxim_only}")
        
        maxim_start_time = time.time()
        
        try:
            test_data, all_results = load_existing_results_from_csv(args.maxim_only)
            print(f"✓ Loaded {len(all_results)} valid results for Maxim evaluation")
            
            if len(all_results) == 0:
                print("❌ No valid results to evaluate. Exiting.")
                return
            
            # Send to Maxim
            print("\n📤 Sending to Maxim for evaluation...")
            test_run_id = send_all_results_to_maxim(
                test_data=test_data,
                all_results=all_results
            )
            
            maxim_time = time.time() - maxim_start_time
            
            if test_run_id:
                # Generate output filename based on input filename
                base_name = os.path.splitext(os.path.basename(args.maxim_only))[0]
                output_file = os.path.join(
                    os.path.dirname(args.maxim_only),
                    f"{base_name}_with_scores.csv"
                )
                
                # Update the original CSV with scores
                print(f"\n📊 Updating CSV with Maxim scores...")
                update_csv_with_maxim_scores(args.maxim_only, [test_run_id])
                
                print("\n" + "=" * 60)
                print("✅ MAXIM-ONLY MODE COMPLETE")
                print("=" * 60)
                print(f"⏱️  Maxim evaluation time: {maxim_time:.2f}s")
                print(f"📄 Updated file: {args.maxim_only}")
            else:
                print("\n❌ Maxim evaluation failed. No scores added.")
            
        except FileNotFoundError as e:
            print(f"❌ Error: {e}")
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
        
        return
    
    # ==================== NORMAL MODE ====================
    # Parse exclude fields from comma-separated string
    exclude_fields = [field.strip() for field in args.exclude_fields.split(',') if field.strip()]
    
    # Load test data from specified CSV file
    test_data = load_test_data_from_csv(args.csv_file)

    print("Starting bulk evaluation process...")
    print(f"CSV file: {args.csv_file}")
    print(f"Loaded {len(test_data)} test cases from CSV")
    
    if exclude_fields:
        print(f"Excluding fields from response: {', '.join(exclude_fields)}")
    else:
        print("No field exclusion applied")
    
    if args.timeout is not None:
        print(f"Timeout set to {args.timeout} seconds for LLM responses")
    else:
        print("No timeout limit set for LLM responses")
    
    if args.max_items is not None:
        print(f"Array/table items limited to first {args.max_items} items")
    else:
        print("No limit on array/table items")
    
    print(f"Batch size: {args.batch_size} parallel prompts")
    print(f"Max retries for 503/504 errors: {args.max_retries}")

    # Load the adopt profile configuration once
    profile = load_adopt_profile()
    
    # Get authentication token once for all test cases
    print("Getting authentication token...")
    access_token = get_auth_token()
    print("Authentication token obtained successfully")
    
    try:
        # Create a wrapper function for calling the agent with profile and settings
        def call_local_agent_with_profile(data):
            return call_local_agent(data, profile, access_token, exclude_fields, args.timeout, args.max_items)
        
        print(f"\n{'='*50}")
        print(f"PROCESSING PROMPTS IN BATCHES (max {args.batch_size} parallel)")
        print(f"{'='*50}")
        print(f"Batch size: {args.batch_size} | Max retries for 503/504 errors: {args.max_retries}")
        
        # Initialize tracking variables
        pending_data = list(test_data)
        retry_counts: Dict[str, int] = {}  # Track retries by input string
        all_results: List[Tuple[Dict, YieldedOutput]] = []  # Collect all results
        error_log: List[Dict] = []  # Track all errors
        batch_number = 0
        
        # Initialize CSV file for raw results (saved immediately after each batch)
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        raw_csv_filename = f"evals/evaluation_results_{timestamp}.csv"
        initialize_raw_csv(raw_csv_filename)
        
        # Start overall timer
        overall_start_time = time.time()
        total_batch_time = 0.0
        
        # Phase 1: Process all prompts in batches (limiting parallel calls to your server)
        # CSV is saved after each batch for resilience
        while pending_data:
            batch_number += 1
            
            # Take up to batch_size items for this batch
            current_batch = pending_data[:args.batch_size]
            pending_data = pending_data[args.batch_size:]
            
            print(f"\n--- Batch {batch_number} ---")
            print(f"Processing {len(current_batch)} prompts...")
            
            # Start batch timer
            batch_start_time = time.time()
            
            # Process this batch (call agents in parallel)
            batch_results, failed_prompts = process_single_batch(
                batch_data=current_batch,
                call_agent_func=call_local_agent_with_profile,
                max_parallel=args.batch_size,
                max_retries=args.max_retries,
                retry_counts=retry_counts,
                error_log=error_log
            )
            
            # Calculate batch time
            batch_elapsed_time = time.time() - batch_start_time
            total_batch_time += batch_elapsed_time
            
            # IMMEDIATELY save batch results to CSV (resilience!)
            if batch_results:
                append_batch_to_csv(raw_csv_filename, batch_results)
                print(f"  💾 Saved {len(batch_results)} results to CSV")
            
            # Collect successful results
            all_results.extend(batch_results)
            
            # Handle failed prompts (503/504 errors to retry)
            if failed_prompts:
                print(f"  {len(failed_prompts)} prompts will be retried in next batch")
                time.sleep(RETRY_DELAY_SECONDS)
                pending_data = failed_prompts + pending_data
            
            print(f"  ✓ Batch {batch_number} complete: {len(batch_results)} results collected")
            print(f"  ⏱️  Batch time: {batch_elapsed_time:.2f}s")
            print(f"  Total collected so far: {len(all_results)}")
        
        print(f"\n{'='*50}")
        print(f"ALL BATCHES COMPLETE")
        print(f"{'='*50}")
        print(f"Total prompts processed: {len(all_results)}")
        print(f"Total batch processing time: {total_batch_time:.2f}s")
        print(f"Raw results saved to: {raw_csv_filename}")
        
        # Phase 2: Send ALL results to Maxim in ONE call (faster than per-batch)
        print(f"\n{'='*50}")
        print(f"SENDING TO MAXIM FOR EVALUATION")
        print(f"{'='*50}")
        
        maxim_start_time = time.time()
        test_run_id = None
        
        if all_results:
            print(f"Sending {len(all_results)} results to Maxim...")
            
            test_run_id = send_all_results_to_maxim(
                test_data=test_data,
                all_results=all_results
            )
            
            maxim_elapsed_time = time.time() - maxim_start_time
            
            if test_run_id:
                print(f"✓ Results sent to Maxim (test run: {test_run_id})")
                print(f"⏱️  Maxim evaluation time: {maxim_elapsed_time:.2f}s")
                
                # Phase 3: Update CSV with Maxim scores
                print("\nUpdating CSV with Maxim evaluation scores...")
                update_csv_with_maxim_scores(raw_csv_filename, [test_run_id])
                print(f"\n📄 Final results saved to: {raw_csv_filename}")
            else:
                print("\n⚠️  Maxim evaluation failed.")
                print(f"📄 Raw results (without scores) still available: {raw_csv_filename}")
        else:
            print("\n⚠️  No results to send to Maxim.")
            print(f"📄 Raw results saved to: {raw_csv_filename}")
        
        # Calculate and display total time
        overall_elapsed_time = time.time() - overall_start_time
        
        print(f"\n{'='*50}")
        print(f"TIMING SUMMARY")
        print(f"{'='*50}")
        print(f"Batch processing time: {total_batch_time:.2f}s")
        print(f"Total elapsed time:    {overall_elapsed_time:.2f}s")
        print(f"Average time per prompt: {overall_elapsed_time / len(all_results):.2f}s" if all_results else "")
        
        # Display error log if there were any errors
        if error_log:
            print(f"\n{'='*50}")
            print(f"⚠️  ERROR LOG ({len(error_log)} prompts with errors)")
            print(f"{'='*50}")
            for i, error_entry in enumerate(error_log, 1):
                print(f"\n{i}. Input: {error_entry['input']}")
                print(f"   Error: {error_entry['error']}")
        else:
            print(f"\n✓ No errors encountered during processing!")
        
    except Exception as e:
        print(f"Failed to run evaluation: {e}")
    print("\nBulk evaluation process completed.")


if __name__ == "__main__":
    main()