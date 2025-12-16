#!/usr/bin/env python3
"""Bulk evaluation functionality using maxim-py for AdoptXchange."""

import os
import pandas as pd
import json
import ast
import requests
import argparse
from typing import List, Any, Dict, Union
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from maxim import maxim
from maxim.models import YieldedOutput
from examples import read_env
from examples.action_api_samples.api_sample import run_simple_action, load_adopt_profile, get_auth_token
from langchain_core.messages import HumanMessage

# Get environment variables
adopt_env = read_env()

# Initialize Maxim SDK
maxim_client = maxim.Maxim({"api_key": adopt_env.MAXIM_API_KEY })

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

    except Exception as e:
        # Return error information in YieldedOutput format
        return YieldedOutput(
            data=f"Error: {str(e)}",
            retrieved_context_to_evaluate=data.get("context", ""),
        )


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


def save_results_to_csv(maxim_result):
    """Save evaluation results to CSV file"""
    import csv
    from datetime import datetime
    
    # Generate timestamp for unique filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_filename = f"evals/evaluation_results_{timestamp}.csv"
    
    # Extract test run ID from the result link
    # Link format: https://app.getmaxim.ai/workspace/{workspace_id}/testrun/{test_run_id}
    result_link = maxim_result.test_run_result.link
    test_run_id = result_link.split('/')[-1]
    
    print(f"\nFetching detailed test run entries for test run ID: {test_run_id}")
    
    # Fetch detailed entries from Maxim API
    entries_response = fetch_test_run_entries(
        test_run_id=test_run_id,
        workspace_id=adopt_env.MAXIM_WORKSPACE_ID,
        api_key=adopt_env.MAXIM_API_KEY
    )
    
    if not entries_response or 'data' not in entries_response:
        print("Failed to fetch test run entries from API")
        return
    
    entries = entries_response['data']['entries']
    
    # Prepare CSV data
    csv_data = []
    
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
        
        csv_data.append({
            'input': input_text,
            'expected_output': expected_output,
            'actual_output': actual_output,
            'bias': bias_score,
            'similarity': similarity
        })
    
    # Write to CSV file
    try:
        with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['input', 'expected_output', 'actual_output', 'bias', 'similarity']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            writer.writeheader()
            writer.writerows(csv_data)
        
        print(f"\n{'='*50}")
        print("RESULTS SAVED TO CSV")
        print(f"{'='*50}")
        print(f"Results saved to: {csv_filename}")
        print(f"Total records: {len(csv_data)}")
        
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

    # Load the adopt profile configuration once
    profile = load_adopt_profile()
    
    # Get authentication token once for all test cases
    print("Getting authentication token...")
    access_token = get_auth_token()
    print("Authentication token obtained successfully")
    
    try:
        # Create a wrapper function for Maxim that includes the profile, token, exclude fields, timeout, and max_items
        def call_local_agent_with_profile(data):
            return call_local_agent(data, profile, access_token, exclude_fields, args.timeout, args.max_items)
        
        result = (
            maxim_client.create_test_run(
                name="Local Agent Endpoint Test", in_workspace_id=adopt_env.MAXIM_WORKSPACE_ID
            )
            .with_data_structure(
                {
                    "input": "INPUT",
                    "expected_output": "EXPECTED_OUTPUT",
                    "context": "CONTEXT_TO_EVALUATE",
                }
            )
            .with_data(test_data)
            .with_evaluators("Bias","Ragas Answer Semantic Similarity")
            .yields_output(call_local_agent_with_profile)
            .run()
        )
        print(f"Maxim test run completed! View results: {result}")
        
        # Extract results and save to CSV
        save_results_to_csv(result)
        
    except Exception as e:
        print(f"Failed to run Maxim evaluation: {e}")
    print("Bulk evaluation process completed.")


if __name__ == "__main__":
    main()