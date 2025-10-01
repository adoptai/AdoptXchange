#!/usr/bin/env python3
"""Bulk evaluation functionality using maxim-py for AdoptXchange."""

import os
import pandas as pd
import json
from maxim import maxim
from maxim.models import YieldedOutput
from examples import read_env
from examples.action_api_samples.api_sample import run_simple_action, load_adopt_profile
from langchain_core.messages import HumanMessage

# Get environment variables
adopt_env = read_env()

# Initialize Maxim SDK
maxim = maxim.Maxim({"api_key": adopt_env.MAXIM_API_KEY })

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
    print(f"Printing test data loaded from CSV file: {test_data}")
    return test_data


# Load test data from CSV file
# You can change this path to your CSV file
csv_file_path = "evals/test_data.csv"  # Default path, can be overridden
test_data = load_test_data_from_csv(csv_file_path)


def call_local_agent(data, profile):
    """Function to call your local agent endpoint using Adopt API"""
    try:
        # Call the actual Adopt API using the simpler run_simple_action function
        response = run_simple_action(data["input"], profile)

        # Parse the response if it's a string representation of a list
        import ast
        try:
            # Try to parse the response as a Python literal (list/dict)
            parsed_response = ast.literal_eval(response)
            
            # If it's a list with dict elements, extract the data
            if isinstance(parsed_response, list) and len(parsed_response) > 0:
                first_item = parsed_response[0]
                if isinstance(first_item, dict) and 'data' in first_item:
                    data_field = first_item['data']
                    
                    # If data field is an array, convert to string with newlines
                    if isinstance(data_field, list):
                        # Convert list of action items to readable string
                        readable_data = []
                        for item in data_field:
                            if isinstance(item, dict) and 'Name' in item:
                                readable_data.append(item['Name'])
                        response_data = '\n'.join(readable_data)
                    else:
                        response_data = str(data_field)
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


def save_results_to_csv(test_data, maxim_result, actual_outputs):
    """Save evaluation results to CSV file"""
    import csv
    from datetime import datetime
    
    # Generate timestamp for unique filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_filename = f"evals/evaluation_results_{timestamp}.csv"
    
    # Prepare CSV data
    csv_data = []
    
    # Extract bias scores and similarity scores from Maxim result
    bias_scores = []
    similarity_passes = []
    
    for test_result in maxim_result.test_run_result.result:
        # Extract bias score
        bias_score = test_result.individual_evaluator_mean_score['Bias']
        bias_scores.append(bias_score.score)
        
        # Extract similarity pass/fail
        similarity_score = test_result.individual_evaluator_mean_score['Ragas Answer Semantic Similarity']
        similarity_passes.append("yes" if similarity_score.is_pass else "no")
    
    for i, test_case in enumerate(test_data):
        # Get actual output from the passed array
        actual_output = actual_outputs[i] if i < len(actual_outputs) else "No output captured"
        
        # Escape newlines in actual output to match expected output format
        actual_output = actual_output.replace('\n', '\\n')
        
        # Get bias score and similarity result for this test case
        bias_score = bias_scores[i]
        similarity = similarity_passes[i]
        
        csv_data.append({
            'input': test_case['input'],
            'expected_output': test_case['expected_output'],
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
        
        print(f"\\n{'='*50}")
        print("RESULTS SAVED TO CSV")
        print(f"{'='*50}")
        print(f"Results saved to: {csv_filename}")
        print(f"Total records: {len(csv_data)}")
        
    except Exception as e:
        print(f"Failed to save results to CSV: {e}")


def main():
    """Main function to run bulk evaluations sequentially"""
    # Check for MAXIM API key
    if not adopt_env.MAXIM_API_KEY:
        raise ValueError("MAXIM_API_KEY environment variable is required")

    if not adopt_env.MAXIM_WORKSPACE_ID:
        raise ValueError("MAXIM_WORKSPACE_ID environment variable is required")

    print("Starting bulk evaluation process...")
    print(f"Loaded {len(test_data)} test cases from CSV")

    # Load the adopt profile configuration once
    profile = load_adopt_profile()
    
    # Array to capture actual outputs during Maxim execution
    actual_outputs = []

    
    try:
        # Create a wrapper function for Maxim that includes the profile and captures outputs
        def call_local_agent_with_profile(data):
            result = call_local_agent(data, profile)
            actual_outputs.append(result.data)  # Capture the actual output
            return result
        
        result = (
            maxim.create_test_run(
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
        save_results_to_csv(test_data, result, actual_outputs)
        
    except Exception as e:
        print(f"Failed to run Maxim evaluation: {e}")
    print("Bulk evaluation process completed.")


if __name__ == "__main__":
    main()