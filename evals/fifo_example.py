#!/usr/bin/env python3
"""
Example: Using FIFO Evals Service Client

This demonstrates the migration from bulk_evals.py to fifo_client.py
"""

from fifo_client import FIFOEvalsClient, run_fifo_evaluation


# Example 1: Simple usage (convenience function)
def example_simple():
    """
    Simplest way to run an evaluation.

    This replaces the old bulk_evals synchronous flow.
    """
    print("=" * 60)
    print("Example 1: Simple Usage (Convenience Function)")
    print("=" * 60)

    result_file = run_fifo_evaluation(
        csv_file="test_data.csv",
        action_id="action_rallyup_assistant",
        base_url="https://go.rallyup.com",
        security_params={"cookie": "session=abc123"},
        api_key="your_api_key_here",
        output_file="results.csv",
        batch_size=5,
        skip_maxim=False,
        verbose=True
    )

    print(f"\n✅ Results saved to: {result_file}")


# Example 2: Step-by-step control
def example_detailed():
    """
    Full control over submission, monitoring, and download.

    Use this when you need more control over the process.
    """
    print("=" * 60)
    print("Example 2: Detailed Control")
    print("=" * 60)

    # Initialize client
    client = FIFOEvalsClient(
        api_key="your_api_key_here",
        org_id="your_org_id_here",
        base_url="https://api.adopt.ai"
    )

    # 1. Submit job (returns immediately)
    print("\n1. Submitting evaluation job...")
    job_id = client.submit_evaluation(
        csv_file="test_data.csv",
        config={
            "action_id": "action_rallyup_assistant",
            "base_url": "https://go.rallyup.com",
            "security_params": {"cookie": "session=abc123"},
            "batch_size": 5,
            "skip_maxim": False
        }
    )
    print(f"✅ Job submitted: {job_id}")

    # 2. Check status
    print("\n2. Checking status...")
    status = client.get_status(job_id)
    print(f"Status: {status['status']}")
    print(f"Progress: {status['progress']}")

    # 3. Wait for completion (with progress)
    print("\n3. Waiting for completion...")
    result = client.wait_for_completion(job_id, poll_interval=30)

    # 4. Download results
    print("\n4. Downloading results...")
    output_file = client.download_results(result, "results.csv")
    print(f"✅ Results saved to: {output_file}")


# Example 3: Context manager (automatic cleanup)
def example_context_manager():
    """
    Using context manager for automatic resource cleanup.
    """
    print("=" * 60)
    print("Example 3: Context Manager")
    print("=" * 60)

    with FIFOEvalsClient(api_key="your_api_key_here", org_id="your_org_id_here") as client:
        result_file = client.submit_and_wait(
            csv_file="test_data.csv",
            config={
                "action_id": "action_rallyup_assistant",
                "base_url": "https://go.rallyup.com",
                "security_params": {"cookie": "session=abc123"}
            },
            output_file="results.csv"
        )
        print(f"\n✅ Results saved to: {result_file}")

    # Client automatically closed when exiting context


# Example 4: Migration from bulk_evals.py
def example_migration():
    """
    Before and after: migrating from bulk_evals to fifo_client.
    """
    print("=" * 60)
    print("Example 4: Migration Guide")
    print("=" * 60)

    print("\n--- OLD CODE (bulk_evals.py) ---")
    print("""
    # OLD: Synchronous, times out on 990+ prompts
    from AdoptXchange.evals.bulk_evals import run_bulk_evaluation

    result = run_bulk_evaluation(
        csv_file="evaluation_test_cases.csv",
        action_id="action_rallyup_assistant",
        # ... times out after 60s ❌
    )
    """)

    print("\n--- NEW CODE (fifo_client.py) ---")
    print("""
    # NEW: Async job submission, succeeds on any size
    from AdoptXchange.evals.fifo_client import run_fifo_evaluation

    result_file = run_fifo_evaluation(
        csv_file="evaluation_test_cases.csv",
        action_id="action_rallyup_assistant",
        base_url="https://go.rallyup.com",
        security_params={"cookie": "session=..."},
        api_key="your_api_key",
        output_file="results.csv"
        # ... completes in ~85 minutes for 990 prompts ✅
    )
    """)

    print("\n✅ Key differences:")
    print("  - Instant submission (no blocking)")
    print("  - Progress tracking during execution")
    print("  - No timeout failures")
    print("  - Handles 990+ prompts successfully")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("FIFO Evals Service Client - Examples")
    print("=" * 60)

    # Uncomment the example you want to run:

    # example_simple()
    # example_detailed()
    # example_context_manager()
    example_migration()

    print("\n" + "=" * 60)
    print("Note: Update api_key and other credentials before running")
    print("=" * 60)
