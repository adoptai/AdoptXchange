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
from typing import List, Any, Dict, Union, Tuple
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError, as_completed
from contextlib import contextmanager
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
RETRYABLE_STATUS_CODES = [503, 504]
MAX_RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5

# Get environment variables
adopt_env = read_env()

# Initialize Maxim SDK
maxim_client = maxim.Maxim({"api_key": adopt_env.MAXIM_API_KEY })


class RetryableHTTPError(Exception):
    """Exception raised for retryable HTTP errors (503, 504)."""
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
    Load test data from a CSV file with columns: Input, Expected_output

    Args:
        csv_file_path: Path to the CSV file

    Returns:
        List of test data dictionaries
    """
    if not os.path.exists(csv_file_path):
        raise FileNotFoundError(f"CSV file not found: {csv_file_path}")

    # Read CSV file
    df = pd.read_csv(csv_file_path)

    # Validate required columns
    required_columns = ["Input", "Expected_output"]
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(f"CSV file missing required columns: {missing_columns}")

    # Convert to list of dictionaries
    test_data = []
    for _, row in df.iterrows():
        test_data.append({
            "input": str(row["Input"]),
            "expected_output": str(row["Expected_output"]),
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
        # Modify the input to include max_items instruction if specified
        modified_input = data["input"]
        if max_items is not None and max_items > 0:
            # Append instruction to limit results in the prompt
            modified_input = f"{data['input']}\n\nPlease limit your response to only the first {max_items} items if returning a list, table, or array of results."
        
        # If timeout is specified, wrap the call in a ThreadPoolExecutor with timeout
        if timeout is not None and timeout > 0:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(run_simple_action, modified_input, profile, access_token)
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
            response = run_simple_action(modified_input, profile, access_token)

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
                .with_data(test_data)
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


def fetch_test_run_entries(test_run_id: str, workspace_id: str, api_key: str):
    """Fetch individual test run entries from Maxim API"""
    url = "https://api.getmaxim.ai/v1/test-runs/entries"
    
    headers = {
        "x-maxim-api-key": api_key
    }
    
    params = {
        "workspaceId": workspace_id,
        "id": test_run_id
    }
    
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Failed to fetch test run entries: {e}")
        return None


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
        entries_response = fetch_test_run_entries(
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
    
    args = parser.parse_args()
    
    # Parse exclude fields from comma-separated string
    exclude_fields = [field.strip() for field in args.exclude_fields.split(',') if field.strip()]
    
    # Load test data from specified CSV file
    test_data = load_test_data_from_csv(args.csv_file)
    
    # Check for MAXIM API key
    if not adopt_env.MAXIM_API_KEY:
        raise ValueError("MAXIM_API_KEY environment variable is required")

    if not adopt_env.MAXIM_WORKSPACE_ID:
        raise ValueError("MAXIM_WORKSPACE_ID environment variable is required")

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
        
        # Start overall timer
        overall_start_time = time.time()
        total_batch_time = 0.0
        
        # Phase 1: Process all prompts in batches (limiting parallel calls to your server)
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
        
        # Phase 2: Send ALL results to Maxim in one single test run
        if all_results:
            print("\nSending all results to Maxim for evaluation...")
            
            maxim_start_time = time.time()
            
            test_run_id = send_all_results_to_maxim(
                test_data=test_data,
                all_results=all_results
            )
            
            maxim_elapsed_time = time.time() - maxim_start_time
            
            if test_run_id:
                print(f"✓ Results sent to Maxim (test run: {test_run_id})")
                print(f"⏱️  Maxim evaluation time: {maxim_elapsed_time:.2f}s")
                print("\nFetching evaluation results...")
                save_results_to_csv_from_test_runs([test_run_id])
            else:
                print("\n⚠️  Failed to send results to Maxim.")
                print("Check the Maxim API status and try again.")
        else:
            print("\n⚠️  No results were collected.")
            print("Check your agent server and try again.")
        
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