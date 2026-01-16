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
from examples.action_api_samples.api_sample import run_simple_action, run_simple_action_full_response, load_adopt_profile, get_auth_token
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

# Maxim client will be initialized in main() after parsing arguments
maxim_client = None


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

def extract_schema(data: Any) -> Any:
    """
    Extract schema/structure from data (dict keys, list types, etc.).
    Converts values to their types, recursively handles nested structures.
    
    Args:
        data: The data structure (dict, list, or primitive)
        
    Returns:
        Schema representation with types instead of values
    """
    if isinstance(data, dict):
        return {key: extract_schema(value) for key, value in data.items()}
    elif isinstance(data, list):
        if len(data) > 0:
            # Use first item's schema as template for list items
            return [extract_schema(data[0])]
        return []
    else:
        # Return type name for primitives
        if data is None:
            return "NoneType"
        return type(data).__name__

def validate_schema(actual: Any, expected_schema: Any, check_extra_keys: bool = True) -> Tuple[bool, List[str]]:
    """
    Validate that actual output matches expected schema structure.
    
    Args:
        actual: The actual output data to validate
        expected_schema: The expected schema structure
        check_extra_keys: If True, check for extra keys in actual output that aren't in expected schema
        
    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []
    
    def compare_structure(actual_val, expected_schema_val, path=""):
        if isinstance(expected_schema_val, dict):
            if not isinstance(actual_val, dict):
                errors.append(f"{path}: Expected dict, got {type(actual_val).__name__}")
                return
            # Check for missing keys
            for key in expected_schema_val:
                if key not in actual_val:
                    errors.append(f"{path}.{key}: Missing required key")
                else:
                    compare_structure(actual_val[key], expected_schema_val[key], 
                                    f"{path}.{key}" if path else key)
            
            # Check for extra keys (keys in actual that aren't in expected)
            if check_extra_keys:
                for key in actual_val:
                    if key not in expected_schema_val:
                        errors.append(f"{path}.{key}: Unexpected key (not in expected schema)")
        elif isinstance(expected_schema_val, list):
            if not isinstance(actual_val, list):
                errors.append(f"{path}: Expected list, got {type(actual_val).__name__}")
                return
            if len(expected_schema_val) > 0 and len(actual_val) > 0:
                # Validate first item schema
                compare_structure(actual_val[0], expected_schema_val[0], f"{path}[0]")
        else:
            # Type validation
            expected_type = expected_schema_val
            actual_type = type(actual_val).__name__ if actual_val is not None else "NoneType"
            
            # Allow flexible type matching (int/float, str compatibility)
            type_matches = (
                expected_type == actual_type or
                (expected_type == 'int' and actual_type == 'float') or
                (expected_type == 'float' and actual_type == 'int') or
                (expected_type == 'str' and actual_type in ['int', 'float']) or
                (expected_type == 'NoneType' and actual_val is None)
            )
            
            if not type_matches:
                errors.append(f"{path}: Expected {expected_type}, got {actual_type}")
    
    compare_structure(actual, expected_schema)
    return len(errors) == 0, errors

def extract_tracing_steps(debug_tracing: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract normalized tracing steps from debug_tracing for comparison.
    
    Args:
        debug_tracing: The debug_tracing dictionary from response
        
    Returns:
        List of normalized step dictionaries with key fields for comparison
    """
    steps = []
    
    # Extract step_traces which contain operation details
    if isinstance(debug_tracing, dict) and "step_traces" in debug_tracing:
        step_traces = debug_tracing.get("step_traces", [])
        
        for trace in step_traces:
            if isinstance(trace, dict):
                step_info = {
                    "operation_id": trace.get("operation_id", ""),
                    "operation_type": trace.get("operation_type", ""),
                }
                
                # Extract method and URL from resolved_operation for REST calls
                resolved_operation = trace.get("resolved_operation")
                if isinstance(resolved_operation, dict):
                    step_info["method"] = resolved_operation.get("method", "")
                    step_info["url"] = resolved_operation.get("url", "")
                
                # Extract widdle operations from execution_log if available
                # This captures operations defined in the workflow
                execution_log = debug_tracing.get("execution_log", [])
                for log_entry in execution_log:
                    if isinstance(log_entry, dict) and "widdle" in log_entry:
                        widdle = log_entry.get("widdle", [])
                        for w in widdle:
                            if isinstance(w, dict) and w.get("id") == step_info["operation_id"]:
                                step_info["method"] = w.get("method", step_info.get("method", ""))
                                step_info["operation"] = w.get("operation", "")
                                step_info["url_template"] = w.get("url", step_info.get("url", ""))
                
                steps.append(step_info)
    
    return steps

def normalize_step_for_comparison(step: Dict[str, Any]) -> str:
    """
    Create a normalized string representation of a step for comparison.
    
    Args:
        step: Step dictionary
        
    Returns:
        Normalized string representation
    """
    parts = []
    
    if step.get("operation_id"):
        parts.append(f"id:{step['operation_id']}")
    if step.get("operation_type"):
        parts.append(f"type:{step['operation_type']}")
    if step.get("method"):
        parts.append(f"method:{step['method']}")
    if step.get("operation"):
        parts.append(f"op:{step['operation']}")
    if step.get("url") or step.get("url_template"):
        url = step.get("url") or step.get("url_template", "")
        # Normalize URL by removing query params and path variables for comparison
        normalized_url = url.split("?")[0] if url else ""
        if normalized_url:
            parts.append(f"url:{normalized_url}")
    
    return "|".join(parts)

def normalize_debug_tracing(debug_tracing: Union[Dict, str, Any]) -> str:
    """
    Normalize debug_tracing for similarity comparison.
    Extracts all keys and params, ordering is not important.
    
    Args:
        debug_tracing: The debug_tracing dictionary, string, or parsed dict
        
    Returns:
        Normalized JSON string representation for similarity comparison
    """
    try:
        # Parse if string
        if isinstance(debug_tracing, str):
            try:
                debug_tracing = json.loads(debug_tracing)
            except (json.JSONDecodeError, ValueError):
                try:
                    debug_tracing = ast.literal_eval(debug_tracing)
                except (ValueError, SyntaxError):
                    return json.dumps({"error": "Could not parse debug_tracing"})
        
        if not isinstance(debug_tracing, dict):
            return json.dumps({"error": "debug_tracing is not a dictionary"})
        
        def normalize_value(value: Any) -> Any:
            """Recursively normalize a value, handling dicts, lists, and primitives."""
            if isinstance(value, dict):
                # Sort keys and normalize values
                normalized_dict = {}
                for key in sorted(value.keys()):
                    normalized_dict[key] = normalize_value(value[key])
                return normalized_dict
            elif isinstance(value, list):
                # Normalize each item, then sort if items are comparable
                normalized_list = [normalize_value(item) for item in value]
                # Try to sort if all items are dicts or primitives (for consistent ordering)
                try:
                    # Only sort if items are simple types or dicts with sortable keys
                    if normalized_list and all(isinstance(item, (dict, str, int, float, bool, type(None))) for item in normalized_list):
                        # Sort dicts by their JSON representation, primitives by value
                        normalized_list.sort(key=lambda x: json.dumps(x, sort_keys=True) if isinstance(x, dict) else str(x))
                except (TypeError, ValueError):
                    # If sorting fails, keep original order
                    pass
                return normalized_list
            else:
                # Return primitive values as-is
                return value
        
        # Normalize the entire debug_tracing structure
        normalized = normalize_value(debug_tracing)
        
        # Return as sorted JSON string for consistent representation
        return json.dumps(normalized, sort_keys=True, ensure_ascii=False)
        
    except Exception as e:
        return json.dumps({"error": f"Error normalizing debug_tracing: {str(e)}"})

def compare_tracing(expected_tracing: Dict[str, Any], actual_tracing: Dict[str, Any]) -> Tuple[str, str]:
    """
    Compare expected and actual tracing steps.
    
    Args:
        expected_tracing: Expected debug_tracing dictionary
        actual_tracing: Actual debug_tracing dictionary
        
    Returns:
        Tuple of (tracing_valid, tracing_errors)
        tracing_valid: "yes", "no", or "skipped"
        tracing_errors: Error messages (semicolon-separated) or empty string
    """
    try:
        expected_steps = extract_tracing_steps(expected_tracing)
        actual_steps = extract_tracing_steps(actual_tracing)
        
        if not expected_steps:
            return "skipped", "No expected tracing steps found in debug_tracing"
        
        if not actual_steps:
            return "no", "No actual tracing steps found in debug_tracing"
        
        # Normalize steps for comparison
        expected_normalized = {normalize_step_for_comparison(step): step for step in expected_steps}
        actual_normalized = {normalize_step_for_comparison(step): step for step in actual_steps}
        
        errors = []
        
        # Check for missing steps
        missing_steps = set(expected_normalized.keys()) - set(actual_normalized.keys())
        if missing_steps:
            for missing_step in missing_steps:
                step_info = expected_normalized[missing_step]
                step_desc = f"id:{step_info.get('operation_id')}, type:{step_info.get('operation_type')}"
                errors.append(f"Missing step: {step_desc}")
        
        # Check for additional/unexpected steps
        additional_steps = set(actual_normalized.keys()) - set(expected_normalized.keys())
        if additional_steps:
            for additional_step in additional_steps:
                step_info = actual_normalized[additional_step]
                step_desc = f"id:{step_info.get('operation_id')}, type:{step_info.get('operation_type')}"
                errors.append(f"Unexpected step: {step_desc}")
        
        tracing_valid = "yes" if len(errors) == 0 else "no"
        tracing_errors = "; ".join(errors) if errors else ""
        
        return tracing_valid, tracing_errors
        
    except Exception as e:
        return "error", f"Error comparing tracing: {str(e)}"

def extract_output_type_info(response: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract output_type and related styling information from response.
    
    Args:
        response: The full response dictionary
        
    Returns:
        Dictionary with output_type, data_structure, and format details
    """
    info = {
        "output_type": None,
        "data_structure": None,
        "has_ordered_fields": False,
        "data_item_count": 0
    }
    
    try:
        ai_message = response.get("ai_message", {})
        content = ai_message.get("content", [])
        
        if isinstance(content, list) and len(content) > 0:
            first_content = content[0]
            if isinstance(first_content, dict):
                info["output_type"] = first_content.get("output_type", None)
                data = first_content.get("data", [])
                
                # Analyze data structure
                if isinstance(data, list):
                    info["data_item_count"] = len(data)
                    if len(data) > 0:
                        if isinstance(data[0], dict):
                            info["data_structure"] = "list of dicts"
                        else:
                            info["data_structure"] = f"list of {type(data[0]).__name__}"
                    else:
                        info["data_structure"] = "empty list"
                else:
                    info["data_structure"] = type(data).__name__
                
                # Check for ordered display fields (indicates table structure)
                ordered_fields = first_content.get("ordered_display_fields", [])
                if ordered_fields and isinstance(ordered_fields, list) and len(ordered_fields) > 0:
                    info["has_ordered_fields"] = True
    except Exception:
        pass
    
    return info

def format_style_comparison_for_maxim(expected_info: Dict[str, Any], actual_info: Dict[str, Any]) -> str:
    """
    Format output_type/style comparison as natural language for Maxim semantic evaluation.
    
    Args:
        expected_info: Output type info from expected response
        actual_info: Output type info from actual response
        
    Returns:
        Natural language comparison string for Maxim to evaluate
    """
    expected_type = expected_info.get("output_type", "unknown")
    actual_type = actual_info.get("output_type", "unknown")
    expected_structure = expected_info.get("data_structure", "unknown")
    actual_structure = actual_info.get("data_structure", "unknown")
    
    comparison = f"""Output Format Validation:
Expected format: {expected_type} with {expected_structure}
Actual format: {actual_type} with {actual_structure}

The output format must match exactly. If expected format is 'table', actual must also be 'table' with list of dicts structure. If expected is 'bullets_list', actual must be 'bullets_list'. Format mismatches (like table vs list, or unformatted text) are critical errors."""
    
    return comparison

def validate_tracing(expected_output_str: str, actual_output: Any) -> Tuple[str, str]:
    """
    Validate actual output tracing against expected output tracing.
    
    Args:
        expected_output_str: String representation of expected output (JSON/Python dict)
        actual_output: The actual output data
        
    Returns:
        Tuple of (tracing_valid, tracing_errors)
    """
    try:
        # Parse expected_output
        if isinstance(expected_output_str, str):
            try:
                expected_dict = json.loads(expected_output_str)
            except (json.JSONDecodeError, ValueError):
                try:
                    expected_dict = ast.literal_eval(expected_output_str)
                except (ValueError, SyntaxError):
                    return "error", "Could not parse expected_output as JSON or Python literal"
        else:
            expected_dict = expected_output_str
        
        # Extract debug_tracing from expected
        expected_tracing = expected_dict.get("debug_tracing") if isinstance(expected_dict, dict) else None
        if not expected_tracing:
            return "skipped", "No debug_tracing found in expected_output"
        
        # Parse actual output
        if isinstance(actual_output, str):
            try:
                actual_dict = json.loads(actual_output)
            except (json.JSONDecodeError, ValueError):
                try:
                    actual_dict = ast.literal_eval(actual_output)
                except (ValueError, SyntaxError):
                    return "error", "Could not parse actual output as JSON or Python literal"
        else:
            actual_dict = actual_output
        
        # Extract debug_tracing from actual
        actual_tracing = actual_dict.get("debug_tracing") if isinstance(actual_dict, dict) else None
        if not actual_tracing:
            return "no", "No debug_tracing found in actual output"
        
        # Compare tracing
        return compare_tracing(expected_tracing, actual_tracing)
        
    except Exception as e:
        return "error", f"Unexpected error validating tracing: {str(e)}"

def validate_response_schema(expected_output_str: str, actual_output: Any) -> Tuple[str, str]:
    """
    Validate actual output schema against expected output structure.
    
    Args:
        expected_output_str: String representation of expected output (JSON)
        actual_output: The actual output data
        
    Returns:
        Tuple of (schema_valid, schema_errors)
        schema_valid: "yes", "no", "error", or "skipped"
        schema_errors: Error messages (semicolon-separated) or empty string
    """
    try:
        # Parse expected_output to extract schema
        # Try both JSON and Python literal formats
        if isinstance(expected_output_str, str):
            try:
                # Try JSON first (requires double quotes)
                expected_dict = json.loads(expected_output_str)
            except (json.JSONDecodeError, ValueError):
                # If JSON fails, try Python literal (supports single quotes, True/False, None)
                try:
                    expected_dict = ast.literal_eval(expected_output_str)
                except (ValueError, SyntaxError) as e:
                    return "error", f"Could not parse expected_output as JSON or Python literal: {str(e)}"
        else:
            expected_dict = expected_output_str
        
        expected_schema = extract_schema(expected_dict)
        
        # Try to parse actual output
        try:
            if isinstance(actual_output, str):
                # Try to parse as JSON first
                try:
                    actual_dict = json.loads(actual_output)
                except (json.JSONDecodeError, ValueError):
                    # Try ast.literal_eval for Python literals
                    try:
                        actual_dict = ast.literal_eval(actual_output)
                    except (ValueError, SyntaxError):
                        # If parsing fails, can't validate schema
                        return "error", "Could not parse actual output as JSON or Python literal"
            else:
                actual_dict = actual_output
            
            # Perform schema validation
            is_valid, errors = validate_schema(actual_dict, expected_schema)
            schema_valid = "yes" if is_valid else "no"
            schema_errors = "; ".join(errors) if errors else ""
            return schema_valid, schema_errors
            
        except Exception as e:
            return "error", f"Error validating schema: {str(e)}"
            
    except Exception as e:
        # This shouldn't happen now since we handle parsing errors above,
        # but catch any other unexpected errors
        return "error", f"Unexpected error parsing expected_output: {str(e)}"

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
        
        # Get full response for schema validation (includes status, message, ai_message, debug_tracing)
        if timeout is not None and timeout > 0:
            with ThreadPoolExecutor(max_workers=3) as executor:
                future = executor.submit(run_simple_action_full_response, modified_input, profile, access_token, trace_id)
                try:
                    full_response = future.result(timeout=timeout)
                except FutureTimeoutError:
                    # Timeout occurred, return "timed out" as the response
                    return YieldedOutput(
                        data="timed out",
                        retrieved_context_to_evaluate=data.get("context", ""),
                    )
        else:
            # No timeout specified, call directly
            full_response = run_simple_action_full_response(modified_input, profile, access_token, trace_id)
        
        # Extract the formatted response string for display/Maxim evaluation
        # This maintains backward compatibility with existing evaluation flow
        if "ai_message" in full_response:
            ai_message = full_response["ai_message"]
            if "content" in ai_message and isinstance(ai_message["content"], list):
                response = "\n".join(str(item) for item in ai_message["content"])
            else:
                response = str(ai_message.get("content", ""))
        else:
            response = str(full_response)

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
        
        # Store full_response as JSON string in a special format for schema validation
        # We'll store it in the YieldedOutput data with a way to extract it later
        # For schema validation, we need the full_response, not the formatted string
        # We'll store it in the output so validate_response_schema can access it
        
        # Return the agent's response in the expected YieldedOutput format
        # Store full_response as a tuple with (formatted_data, full_response_dict) for schema validation
        output_data = (response_data, full_response) if isinstance(full_response, dict) else response_data
        
        return YieldedOutput(
            data=output_data,
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
    # Safety check: if Maxim client is not initialized, return None
    if maxim_client is None:
        print("⚠️  Maxim client not initialized - skipping Maxim evaluation")
        return None
    
    # Create lookup for precomputed results
    precomputed_results = {}
    for data, output in all_results:
        precomputed_results[data["input"]] = output
    
    # Filter test_data to only include items that have results
    # This ensures we only send data to Maxim that we have precomputed results for
    # Also extract debug_tracing from expected_output for similarity comparison
    test_data_with_results = []
    for data in test_data:
        if data["input"] in precomputed_results:
            # Extract and normalize debug_tracing from expected_output
            expected_output_str = data.get("expected_output", "")
            try:
                if isinstance(expected_output_str, str):
                    try:
                        expected_dict = json.loads(expected_output_str)
                    except (json.JSONDecodeError, ValueError):
                        try:
                            expected_dict = ast.literal_eval(expected_output_str)
                        except (ValueError, SyntaxError):
                            expected_dict = {}
                else:
                    expected_dict = expected_output_str
                
                # Extract debug_tracing from expected output
                expected_debug_tracing = expected_dict.get("debug_tracing") if isinstance(expected_dict, dict) else None
                if expected_debug_tracing:
                    # Normalize and replace expected_output with just debug_tracing
                    normalized_expected_tracing = normalize_debug_tracing(expected_debug_tracing)
                    data_copy = data.copy()
                    data_copy["expected_output"] = normalized_expected_tracing
                    test_data_with_results.append(data_copy)
                else:
                    # If no debug_tracing in expected, skip this item for similarity comparison
                    # but still include it for other evaluations
                    test_data_with_results.append(data)
            except Exception:
                # If extraction fails, use original data
                test_data_with_results.append(data)
    
    print(f"  Filtered test_data: {len(test_data)} -> {len(test_data_with_results)} items with results")
    
    def get_precomputed_result(data):
        input_key = data["input"]
        if input_key in precomputed_results:
            output = precomputed_results[input_key]
            # Extract debug_tracing from actual output for similarity comparison
            # If output.data is a tuple (formatted_string, full_response_dict), use full_response_dict
            if isinstance(output.data, tuple) and len(output.data) == 2:
                _, full_response = output.data
                # Extract and normalize debug_tracing from actual output
                if isinstance(full_response, dict):
                    actual_debug_tracing = full_response.get("debug_tracing")
                    if actual_debug_tracing:
                        normalized_actual_tracing = normalize_debug_tracing(actual_debug_tracing)
                        # Return normalized debug_tracing for similarity comparison
                        return YieldedOutput(
                            data=normalized_actual_tracing,
                            retrieved_context_to_evaluate=output.retrieved_context_to_evaluate,
                        )
                    else:
                        # If no debug_tracing, return formatted output as fallback
                        formatted_output, _ = output.data
                        return YieldedOutput(
                            data=formatted_output,
                            retrieved_context_to_evaluate=output.retrieved_context_to_evaluate,
                        )
                else:
                    # Fallback to formatted output
                    formatted_output, _ = output.data
                    return YieldedOutput(
                        data=formatted_output,
                        retrieved_context_to_evaluate=output.retrieved_context_to_evaluate,
                    )
            else:
                # Try to extract debug_tracing from string output
                try:
                    if isinstance(output.data, str):
                        try:
                            actual_dict = json.loads(output.data)
                        except (json.JSONDecodeError, ValueError):
                            try:
                                actual_dict = ast.literal_eval(output.data)
                            except (ValueError, SyntaxError):
                                # Return as-is if parsing fails
                                return output
                        
                        if isinstance(actual_dict, dict):
                            actual_debug_tracing = actual_dict.get("debug_tracing")
                            if actual_debug_tracing:
                                normalized_actual_tracing = normalize_debug_tracing(actual_debug_tracing)
                                return YieldedOutput(
                                    data=normalized_actual_tracing,
                                    retrieved_context_to_evaluate=output.retrieved_context_to_evaluate,
                                )
                except Exception:
                    pass
                
                # Return as-is if not a tuple and no debug_tracing found
                return output
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
                .with_evaluators("Bias", "Ragas Answer Semantic Similarity", "Ragas Context Precision")
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
        error_str = str(e)
        # If the error is about Ragas Context Precision not being available, try without it
        if "Ragas Context Precision" in error_str or "Failed to fetch evaluator" in error_str:
            print(f"⚠️  {error_str}")
            print("  Retrying without 'Ragas Context Precision' evaluator...")
            try:
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
                    print("  ✓ Successfully created test run without 'Ragas Context Precision'")
                    return test_run_id
                else:
                    print("⚠️  Maxim returned None on retry - likely a server error")
                    return None
            except Exception as retry_e:
                print(f"⚠️  Failed to send results to Maxim on retry: {retry_e}")
                return None
        else:
            print(f"⚠️  Failed to send results to Maxim: {e}")
            return None


def initialize_raw_csv(csv_filename: str) -> None:
    """Initialize a new CSV file with headers for raw results (without Maxim scores).
    
    Args:
        csv_filename: Path to the CSV file to create
    """
    import csv
    
    with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['input', 'expected_output', 'actual_output', 'schema_valid', 'schema_errors', 'tracing_valid', 'tracing_errors', 'style_valid', 'style_errors', 'bias', 'similarity']
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
        fieldnames = ['input', 'expected_output', 'actual_output', 'schema_valid', 'schema_errors', 'tracing_valid', 'tracing_errors', 'style_valid', 'style_errors', 'bias', 'similarity']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        for data, output in batch_results:
            # Extract formatted output and full response
            # output.data may be a tuple (formatted_string, full_response_dict) or just a string
            if isinstance(output.data, tuple) and len(output.data) == 2:
                formatted_output, full_response = output.data
                # Use full_response for both CSV storage and schema validation
                # Serialize full_response as JSON string for CSV
                actual_output = json.dumps(full_response) if isinstance(full_response, dict) else str(full_response)
                actual_output = actual_output.replace('\n', '\\n')  # Escape newlines for CSV
                schema_validation_input = full_response
            else:
                # Fallback for old format
                actual_output = str(output.data).replace('\n', '\\n') if output.data else ""
                schema_validation_input = output.data
            
            # Perform schema validation using full response structure
            schema_valid, schema_errors = validate_response_schema(
                data['expected_output'],
                schema_validation_input
            )
            
            # Perform tracing validation
            tracing_valid, tracing_errors = validate_tracing(
                data['expected_output'],
                schema_validation_input
            )
            
            # Escape newlines in errors for CSV
            schema_errors_csv = schema_errors.replace('\n', '\\n') if schema_errors else ""
            tracing_errors_csv = tracing_errors.replace('\n', '\\n') if tracing_errors else ""
            
            # Calculate similarity from debug_tracing comparison
            # Similarity compares debug_tracings, which is what tracing_valid does
            # So use tracing_valid as initial similarity indicator
            # Maxim evaluation will override this with semantic similarity if available
            initial_similarity = tracing_valid if tracing_valid in ("yes", "no") else "no"
            
            writer.writerow({
                'input': data['input'],
                'expected_output': data['expected_output'],
                'actual_output': actual_output,
                'schema_valid': schema_valid,
                'schema_errors': schema_errors_csv,
                'tracing_valid': tracing_valid,
                'tracing_errors': tracing_errors_csv,
                'style_valid': '',  # Will be filled by Maxim later
                'style_errors': '',  # Will be filled by Maxim later
                'bias': '',  # Will be filled by Maxim later
                'similarity': initial_similarity  # Initial similarity based on tracing validation, Maxim will override if available
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
    
    # Create lookup for original expected_output (needed for style validation)
    original_expected_output_lookup = {}
    for data in batch_data:
        original_expected_output_lookup[data["input"]] = data.get("expected_output", "")
    
    # Extract and normalize debug_tracing from expected_output for similarity comparison
    batch_data_with_tracing = []
    for data in batch_data:
        expected_output_str = data.get("expected_output", "")
        try:
            if isinstance(expected_output_str, str):
                try:
                    expected_dict = json.loads(expected_output_str)
                except (json.JSONDecodeError, ValueError):
                    try:
                        expected_dict = ast.literal_eval(expected_output_str)
                    except (ValueError, SyntaxError):
                        expected_dict = {}
            else:
                expected_dict = expected_output_str
            
            # Extract debug_tracing from expected output
            expected_debug_tracing = expected_dict.get("debug_tracing") if isinstance(expected_dict, dict) else None
            if expected_debug_tracing:
                # Normalize and replace expected_output with just debug_tracing
                normalized_expected_tracing = normalize_debug_tracing(expected_debug_tracing)
                data_copy = data.copy()
                data_copy["expected_output"] = normalized_expected_tracing
                batch_data_with_tracing.append(data_copy)
            else:
                # If no debug_tracing in expected, skip this item for similarity comparison
                # but still include it for other evaluations
                batch_data_with_tracing.append(data)
        except Exception:
            # If extraction fails, use original data
            batch_data_with_tracing.append(data)
    
    def get_precomputed_result(data):
        input_key = data["input"]
        if input_key in precomputed_results:
            output = precomputed_results[input_key]
            # Extract debug_tracing from actual output for similarity comparison
            # If output.data is a tuple (formatted_string, full_response_dict), use full_response_dict
            if isinstance(output.data, tuple) and len(output.data) == 2:
                formatted_output, full_response = output.data
                
                # Extract and normalize debug_tracing from actual output
                normalized_actual_tracing = None
                if isinstance(full_response, dict):
                    actual_debug_tracing = full_response.get("debug_tracing")
                    if actual_debug_tracing:
                        normalized_actual_tracing = normalize_debug_tracing(actual_debug_tracing)
                
                # Extract output_type info for style validation (keep for context evaluation)
                try:
                    # Parse expected_output to extract style info
                    # Note: data["expected_output"] now contains normalized debug_tracing
                    # Need to get original expected_output from the lookup
                    original_expected_output_str = original_expected_output_lookup.get(input_key)
                    
                    if original_expected_output_str:
                        if isinstance(original_expected_output_str, str):
                            try:
                                expected_dict = json.loads(original_expected_output_str)
                            except (json.JSONDecodeError, ValueError):
                                try:
                                    expected_dict = ast.literal_eval(original_expected_output_str)
                                except (ValueError, SyntaxError):
                                    expected_dict = {}
                        else:
                            expected_dict = original_expected_output_str
                        
                        expected_info = extract_output_type_info(expected_dict)
                        actual_info = extract_output_type_info(full_response if isinstance(full_response, dict) else {})
                        
                        # Format style comparison for Maxim semantic evaluation
                        style_comparison = format_style_comparison_for_maxim(expected_info, actual_info)
                        
                        # Add to context for Maxim to evaluate
                        existing_context = output.retrieved_context_to_evaluate or ""
                        combined_context = f"{existing_context}\n\n{style_comparison}" if existing_context else style_comparison
                    else:
                        combined_context = output.retrieved_context_to_evaluate
                except Exception:
                    # If style extraction fails, use existing context
                    combined_context = output.retrieved_context_to_evaluate
                
                # Return normalized debug_tracing for similarity comparison
                if normalized_actual_tracing:
                    return YieldedOutput(
                        data=normalized_actual_tracing,
                        retrieved_context_to_evaluate=combined_context,
                    )
                else:
                    # Fallback to formatted output if no debug_tracing
                    return YieldedOutput(
                        data=formatted_output,
                        retrieved_context_to_evaluate=combined_context,
                    )
            else:
                # Try to extract debug_tracing from string output
                try:
                    if isinstance(output.data, str):
                        try:
                            actual_dict = json.loads(output.data)
                        except (json.JSONDecodeError, ValueError):
                            try:
                                actual_dict = ast.literal_eval(output.data)
                            except (ValueError, SyntaxError):
                                # Return as-is if parsing fails
                                return output
                        
                        if isinstance(actual_dict, dict):
                            actual_debug_tracing = actual_dict.get("debug_tracing")
                            if actual_debug_tracing:
                                normalized_actual_tracing = normalize_debug_tracing(actual_debug_tracing)
                                return YieldedOutput(
                                    data=normalized_actual_tracing,
                                    retrieved_context_to_evaluate=output.retrieved_context_to_evaluate,
                                )
                except Exception:
                    pass
                
                # Return as-is if not a tuple and no debug_tracing found
                return output
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
                .with_data(batch_data_with_tracing)
                .with_evaluators("Bias", "Ragas Answer Semantic Similarity", "Ragas Context Precision")
                .yields_output(get_precomputed_result)
                .run()
            )
        
        if result is not None and result.test_run_result is not None:
            test_run_id = result.test_run_result.link.split('/')[-1]
            return test_run_id
        else:
            return None
    except Exception as e:
        error_str = str(e)
        # If the error is about Ragas Context Precision not being available, try without it
        if "Ragas Context Precision" in error_str or "Failed to fetch evaluator" in error_str:
            print(f"  ⚠️  Maxim error for batch {batch_number}: {error_str}")
            print(f"  Retrying batch {batch_number} without 'Ragas Context Precision' evaluator...")
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
                        .with_data(batch_data_with_tracing)
                        .with_evaluators("Bias", "Ragas Answer Semantic Similarity")
                        .yields_output(get_precomputed_result)
                        .run()
                    )
                
                if result is not None and result.test_run_result is not None:
                    test_run_id = result.test_run_result.link.split('/')[-1]
                    print(f"  ✓ Successfully created test run for batch {batch_number} without 'Ragas Context Precision'")
                    return test_run_id
                else:
                    return None
            except Exception as retry_e:
                print(f"  ⚠️  Maxim error for batch {batch_number} on retry: {retry_e}")
                return None
        else:
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
            
            # Extract style validation from Ragas Context Precision
            # This evaluates if the context (which includes style comparison) matches
            style_valid = "no"
            context_precision_score = 0
            for result in overall_results:
                if result['name'] == 'Ragas Context Precision':
                    context_precision_score = result['value']
                    # If context precision is high, style likely matches
                    # Threshold: >= 0.7 means styles match
                    style_valid = "yes" if context_precision_score >= 0.7 else "no"
                    break
            
            # Handle duplicates: keep track of all occurrences but use the latest scores
            if input_text in scores_lookup:
                duplicate_count += 1
                # Keep the latest scores (most recent evaluation)
                # Could also average or keep first, but latest is usually most accurate
            
            scores_lookup[input_text] = {
                'bias': bias_score,
                'similarity': similarity,
                'style_valid': style_valid,
                'style_score': context_precision_score
            }
    
    print(f"\n  Total entries fetched from Maxim: {total_entries_fetched}")
    print(f"  Unique inputs in scores lookup: {len(scores_lookup)}")
    if duplicate_count > 0:
        print(f"  ⚠️  Found {duplicate_count} duplicate inputs (kept latest scores)")
    
    # Helper function to calculate similarity from debug_tracing comparison
    def calculate_similarity_from_tracing(expected_output_str: str, actual_output_str: str) -> str:
        """Calculate similarity by comparing normalized debug_tracing from expected and actual outputs."""
        try:
            # Parse expected_output
            if isinstance(expected_output_str, str):
                try:
                    expected_dict = json.loads(expected_output_str)
                except (json.JSONDecodeError, ValueError):
                    try:
                        expected_dict = ast.literal_eval(expected_output_str)
                    except (ValueError, SyntaxError):
                        return "error"
            else:
                expected_dict = expected_output_str
            
            # Parse actual_output
            if isinstance(actual_output_str, str):
                try:
                    actual_dict = json.loads(actual_output_str)
                except (json.JSONDecodeError, ValueError):
                    try:
                        actual_dict = ast.literal_eval(actual_output_str)
                    except (ValueError, SyntaxError):
                        return "error"
            else:
                actual_dict = actual_output_str
            
            # Extract debug_tracing from both
            expected_tracing = expected_dict.get("debug_tracing") if isinstance(expected_dict, dict) else None
            actual_tracing = actual_dict.get("debug_tracing") if isinstance(actual_dict, dict) else None
            
            if not expected_tracing or not actual_tracing:
                return "skipped"
            
            # Normalize both debug_tracing for comparison
            normalized_expected = normalize_debug_tracing(expected_tracing)
            normalized_actual = normalize_debug_tracing(actual_tracing)
            
            # Compare normalized strings - if they match exactly, similarity is "yes"
            # Otherwise, use tracing validation result as a proxy
            if normalized_expected == normalized_actual:
                return "yes"
            else:
                # Use tracing validation as similarity indicator
                # If tracing validation passed, similarity is likely high
                # This is a fallback when Maxim evaluation is not available
                return "partial"
        except Exception:
            return "error"
    
    # Read the raw CSV and update with scores
    updated_rows = []
    matched_count = 0
    unmatched_inputs = []
    similarity_calculated_count = 0
    
    with open(raw_csv_filename, 'r', newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            # Normalize input text for matching (strip whitespace)
            input_text = row['input'].strip()
            
            # Try exact match first
            if input_text in scores_lookup:
                row['bias'] = scores_lookup[input_text]['bias']
                row['similarity'] = scores_lookup[input_text]['similarity']
                # Add style validation if available
                if 'style_valid' in scores_lookup[input_text]:
                    row['style_valid'] = scores_lookup[input_text]['style_valid']
                    # Store style score as error detail if validation failed
                    if scores_lookup[input_text]['style_valid'] == 'no':
                        row['style_errors'] = f"Style mismatch (Context Precision: {scores_lookup[input_text].get('style_score', 0):.2f})"
                    else:
                        row['style_errors'] = ""
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
                        # Add style validation if available
                        if 'style_valid' in scores_lookup[maxim_input]:
                            row['style_valid'] = scores_lookup[maxim_input]['style_valid']
                            if scores_lookup[maxim_input]['style_valid'] == 'no':
                                row['style_errors'] = f"Style mismatch (Context Precision: {scores_lookup[maxim_input].get('style_score', 0):.2f})"
                            else:
                                row['style_errors'] = ""
                        matched_count += 1
                        matched = True
                        break
                
                if not matched:
                    # Try to find partial match for debugging
                    if len(unmatched_inputs) < 10:  # Show more unmatched for debugging
                        unmatched_inputs.append(input_text)
            
            # If similarity is still empty or only whitespace, calculate it from debug_tracing comparison
            if not row.get('similarity') or not row.get('similarity').strip():
                calculated_similarity = calculate_similarity_from_tracing(
                    row.get('expected_output', ''),
                    row.get('actual_output', '')
                )
                # Use calculated similarity if it's "yes", otherwise use tracing_valid as indicator
                if calculated_similarity == "yes":
                    row['similarity'] = "yes"
                elif calculated_similarity == "error":
                    # If calculation failed, use tracing_valid as fallback
                    tracing_valid = row.get('tracing_valid', '').strip().lower()
                    row['similarity'] = "yes" if tracing_valid == "yes" else "no"
                else:
                    # For "partial" or "skipped", use tracing_valid as the indicator
                    # Since similarity should compare debug_tracings, and tracing_valid does that,
                    # we can use tracing_valid as a proxy for similarity
                    tracing_valid = row.get('tracing_valid', '').strip().lower()
                    if tracing_valid == "yes":
                        # Tracing steps match, so debug_tracings are similar
                        row['similarity'] = "yes"
                    elif tracing_valid == "no":
                        # Tracing steps don't match, so debug_tracings are different
                        row['similarity'] = "no"
                    else:
                        # tracing_valid is "skipped" or "error"
                        row['similarity'] = "no"  # Default to "no" if uncertain
                similarity_calculated_count += 1
            
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
    # Preserve schema_valid, schema_errors, tracing_valid, and tracing_errors if they exist in the rows
    all_fieldnames = ['input', 'expected_output', 'actual_output', 'schema_valid', 'schema_errors', 'tracing_valid', 'tracing_errors', 'bias', 'similarity']
    # Check what fields actually exist in the rows (for backward compatibility)
    if updated_rows:
        existing_fields = set(updated_rows[0].keys())
        fieldnames = [f for f in all_fieldnames if f in existing_fields]
        # Add any other unexpected fields
        for row in updated_rows:
            for key in row.keys():
                if key not in fieldnames:
                    fieldnames.append(key)
    else:
        fieldnames = all_fieldnames
    
    with open(raw_csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(updated_rows)
    
    print(f"\n✓ Updated {matched_count}/{len(updated_rows)} rows with Maxim scores")
    if similarity_calculated_count > 0:
        print(f"  Calculated similarity from debug_tracing for {similarity_calculated_count} rows (Maxim scores not available)")
    
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
            actual_output_escaped = actual_output.replace('\n', '\\n')
            
            # Perform schema validation
            schema_valid, schema_errors = validate_response_schema(
                expected_output,
                actual_output
            )
            schema_errors_csv = schema_errors.replace('\n', '\\n') if schema_errors else ""
            
            # Perform tracing validation
            tracing_valid, tracing_errors = validate_tracing(
                expected_output,
                actual_output
            )
            tracing_errors_csv = tracing_errors.replace('\n', '\\n') if tracing_errors else ""
            
            all_csv_data.append({
                'input': input_text,
                'expected_output': expected_output,
                'actual_output': actual_output_escaped,
                'schema_valid': schema_valid,
                'schema_errors': schema_errors_csv,
                'tracing_valid': tracing_valid,
                'tracing_errors': tracing_errors_csv,
                'bias': bias_score,
                'similarity': similarity
            })
    
    if not all_csv_data:
        print("No data collected from test runs")
        return
    
    # Write to CSV file
    try:
        with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['input', 'expected_output', 'actual_output', 'schema_valid', 'schema_errors', 'tracing_valid', 'tracing_errors', 'style_valid', 'style_errors', 'bias', 'similarity']
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
  
  # Skip Maxim evaluation (results saved to CSV without scores)
  python evals/bulk_evals.py --skip-maxim
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
    
    parser.add_argument(
        '--skip-maxim',
        action='store_true',
        help='Skip all Maxim evaluation runs. Results will still be saved to CSV but without Maxim scores.'
    )
    
    args = parser.parse_args()
    
    # Initialize Maxim SDK only if not skipping
    global maxim_client
    if not args.skip_maxim:
        # Check for MAXIM API key (only required if not skipping Maxim)
        if not adopt_env.MAXIM_API_KEY:
            raise ValueError("MAXIM_API_KEY environment variable is required")

        if not adopt_env.MAXIM_WORKSPACE_ID:
            raise ValueError("MAXIM_WORKSPACE_ID environment variable is required")
        
        maxim_client = maxim.Maxim({"api_key": adopt_env.MAXIM_API_KEY })
    else:
        print("⚠️  --skip-maxim flag is set - Maxim evaluation will be skipped")
        maxim_client = None
    
    # ==================== MAXIM-ONLY MODE ====================
    if args.maxim_only:
        print("=" * 60)
        print("🔬 MAXIM-ONLY MODE")
        print("=" * 60)
        print(f"Loading existing results from: {args.maxim_only}")
        
        if args.skip_maxim:
            print("\n⚠️  --skip-maxim flag is set - Maxim evaluation will be skipped")
            print("📄 CSV file remains unchanged (no scores added)")
            return
        
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
    print("✓ Schema validation enabled: Validating actual output structure against expected_output schema")
    print("✓ Tracing validation enabled: Validating execution steps, tools, APIs, and methods from debug_tracing")
    print("✓ Style validation enabled: Validating output_type and format (table/list) via Maxim semantic evaluation")
    
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
        if args.skip_maxim:
            print(f"\n{'='*50}")
            print(f"SKIPPING MAXIM EVALUATION (--skip-maxim flag is set)")
            print(f"{'='*50}")
            print(f"📄 Raw results saved to: {raw_csv_filename}")
            print(f"⚠️  Maxim evaluation skipped - no scores added")
        else:
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
        
        # Display schema validation summary if we have results
        if all_results and os.path.exists(raw_csv_filename):
            try:
                df_results = pd.read_csv(raw_csv_filename)
                if 'schema_valid' in df_results.columns:
                    schema_valid_count = len(df_results[df_results['schema_valid'] == 'yes'])
                    schema_invalid_count = len(df_results[df_results['schema_valid'] == 'no'])
                    schema_error_count = len(df_results[df_results['schema_valid'] == 'error'])
                    schema_skipped_count = len(df_results[df_results['schema_valid'] == 'skipped'])
                    total_schema_tested = len(df_results) - schema_skipped_count
                    
                    print(f"\n{'='*50}")
                    print(f"SCHEMA VALIDATION SUMMARY")
                    print(f"{'='*50}")
                    print(f"✓ Valid schemas:   {schema_valid_count}")
                    print(f"✗ Invalid schemas: {schema_invalid_count}")
                    print(f"⚠️  Schema errors:  {schema_error_count}")
                    if schema_skipped_count > 0:
                        print(f"⊘ Skipped:        {schema_skipped_count} (non-JSON expected_output)")
                    if total_schema_tested > 0:
                        success_rate = (schema_valid_count / total_schema_tested) * 100
                        print(f"\nSchema validation pass rate: {success_rate:.1f}%")
            except Exception as e:
                # If CSV reading fails, just skip the summary
                pass
        
        # Display tracing validation summary if we have results
        if all_results and os.path.exists(raw_csv_filename):
            try:
                df_results = pd.read_csv(raw_csv_filename)
                if 'tracing_valid' in df_results.columns:
                    tracing_valid_count = len(df_results[df_results['tracing_valid'] == 'yes'])
                    tracing_invalid_count = len(df_results[df_results['tracing_valid'] == 'no'])
                    tracing_error_count = len(df_results[df_results['tracing_valid'] == 'error'])
                    tracing_skipped_count = len(df_results[df_results['tracing_valid'] == 'skipped'])
                    total_tracing_tested = len(df_results) - tracing_skipped_count
                    
                    print(f"\n{'='*50}")
                    print(f"TRACING VALIDATION SUMMARY")
                    print(f"{'='*50}")
                    print(f"✓ Valid tracings:   {tracing_valid_count}")
                    print(f"✗ Invalid tracings: {tracing_invalid_count}")
                    print(f"⚠️  Tracing errors:  {tracing_error_count}")
                    if tracing_skipped_count > 0:
                        print(f"⊘ Skipped:        {tracing_skipped_count} (no debug_tracing in expected_output)")
                    if total_tracing_tested > 0:
                        success_rate = (tracing_valid_count / total_tracing_tested) * 100
                        print(f"\nTracing validation pass rate: {success_rate:.1f}%")
            except Exception as e:
                # If CSV reading fails, just skip the summary
                pass
        
        # Display style validation summary if we have results
        if all_results and os.path.exists(raw_csv_filename):
            try:
                df_results = pd.read_csv(raw_csv_filename)
                if 'style_valid' in df_results.columns:
                    style_valid_count = len(df_results[df_results['style_valid'] == 'yes'])
                    style_invalid_count = len(df_results[df_results['style_valid'] == 'no'])
                    style_empty_count = len(df_results[df_results['style_valid'] == ''])
                    total_style_tested = len(df_results) - style_empty_count
                    
                    print(f"\n{'='*50}")
                    print(f"OUTPUT STYLE VALIDATION SUMMARY (via Maxim)")
                    print(f"{'='*50}")
                    print(f"✓ Valid styles:   {style_valid_count}")
                    print(f"✗ Invalid styles: {style_invalid_count}")
                    if style_empty_count > 0:
                        print(f"⊘ Not evaluated: {style_empty_count} (awaiting Maxim results)")
                    if total_style_tested > 0:
                        success_rate = (style_valid_count / total_style_tested) * 100
                        print(f"\nStyle validation pass rate: {success_rate:.1f}%")
            except Exception as e:
                # If CSV reading fails, just skip the summary
                pass
        
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