#!/usr/bin/env python3
"""
Bulk Evaluations V2 — Server-Side FIFO Job Queue

Submits evaluation jobs to the Adopt.AI backend, which processes them
asynchronously via a Temporal FIFO queue. Unlike bulk_evals.py (v1),
all LLM execution happens server-side — the client just submits, polls,
and downloads results.

Auth: Set ADOPT_CLIENT_ID and ADOPT_CLIENT_SECRET in your environment
(or pass --client-id / --client-secret).

Examples:

  # Submit and wait for results
  python evals/bulk_evals_v2.py \\
      --csv-file test_data.csv \\
      --action-id action_rallyup_assistant \\
      --base-url https://go.rallyup.com \\
      --cookie "session=abc123"

  # Skip Maxim scoring
  python evals/bulk_evals_v2.py \\
      --csv-file test_data.csv \\
      --action-id action_rallyup_assistant \\
      --base-url https://go.rallyup.com \\
      --cookie "session=abc123" \\
      --skip-maxim

  # Custom output file with timestamp
  python evals/bulk_evals_v2.py \\
      --csv-file test_data.csv \\
      --action-id action_rallyup_assistant \\
      --base-url https://go.rallyup.com \\
      --cookie "session=abc123" \\
      --output results.csv --auto-timestamp

  # List all jobs
  python evals/bulk_evals_v2.py --list-jobs

  # List only completed jobs
  python evals/bulk_evals_v2.py --list-jobs --status completed

  # Check status of a specific job
  python evals/bulk_evals_v2.py --check-status JOB_ID

  # Cancel a running job
  python evals/bulk_evals_v2.py --cancel-job JOB_ID
"""

import sys
import os
import argparse

# Auto-add project root to Python path so imports work from any directory
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from evals.fifo_client import FIFOEvalsClient, FIFOClientError


def main():
    parser = argparse.ArgumentParser(
        description="Bulk Evaluations V2 — server-side FIFO job queue",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Submit evaluation
  python evals/bulk_evals_v2.py --csv-file test.csv \\
      --action-id action_rallyup_assistant \\
      --base-url https://go.rallyup.com \\
      --cookie "session=abc123"

  # List jobs           python evals/bulk_evals_v2.py --list-jobs
  # Check status        python evals/bulk_evals_v2.py --check-status JOB_ID
  # Cancel job          python evals/bulk_evals_v2.py --cancel-job JOB_ID

Environment variables:
  ADOPT_CLIENT_ID       Frontegg API client ID
  ADOPT_CLIENT_SECRET   Frontegg API client secret
  ADOPT_API_BASE_URL    Backend URL (default: https://api.adopt.ai)
        """,
    )

    # Auth (from env by default)
    parser.add_argument("--client-id", default=os.environ.get("ADOPT_CLIENT_ID"),
                        help="Frontegg client ID (default: $ADOPT_CLIENT_ID)")
    parser.add_argument("--client-secret", default=os.environ.get("ADOPT_CLIENT_SECRET"),
                        help="Frontegg client secret (default: $ADOPT_CLIENT_SECRET)")
    parser.add_argument("--api-base-url", default=os.environ.get("ADOPT_API_BASE_URL", "https://api.adopt.ai"),
                        help="Backend proxy URL (default: https://api.adopt.ai)")

    # Job submission
    submit = parser.add_argument_group("Job Submission")
    submit.add_argument("--csv-file", help="Path to CSV file with test data")
    submit.add_argument("--action-id", help="Action ID to evaluate")
    submit.add_argument("--base-url", help="Customer API base URL (e.g. https://go.rallyup.com)")
    submit.add_argument("--cookie", help='Session cookie (e.g. "session=abc123")')
    submit.add_argument("--output", default="results.csv", help="Output CSV path (default: results.csv)")
    submit.add_argument("--batch-size", type=int, default=5, help="Batch size (default: 5)")
    submit.add_argument("--skip-maxim", action="store_true", help="Skip Maxim evaluation")
    submit.add_argument("--skip-validation", action="store_true", help="Skip client-side CSV validation")
    submit.add_argument("--poll-interval", type=int, default=30, help="Poll interval in seconds (default: 30)")
    submit.add_argument("--auto-timestamp", action="store_true", help="Append timestamp to output filename")
    submit.add_argument("--quiet", action="store_true", help="Suppress progress output")

    # Job management
    manage = parser.add_argument_group("Job Management")
    manage.add_argument("--list-jobs", action="store_true", help="List evaluation jobs")
    manage.add_argument("--status", choices=["pending", "processing", "completed", "failed", "cancelled"],
                        help="Filter by status (use with --list-jobs)")
    manage.add_argument("--limit", type=int, default=50, help="Max jobs to list (default: 50)")
    manage.add_argument("--check-status", metavar="JOB_ID", help="Check status of a job")
    manage.add_argument("--cancel-job", metavar="JOB_ID", help="Cancel a running job")

    args = parser.parse_args()

    # --- Validate credentials ---
    if not args.client_id or not args.client_secret:
        parser.error(
            "Credentials required. Set ADOPT_CLIENT_ID and ADOPT_CLIENT_SECRET "
            "in your environment, or pass --client-id / --client-secret."
        )

    try:
        client = FIFOEvalsClient(
            client_id=args.client_id,
            client_secret=args.client_secret,
            base_url=args.api_base_url,
        )

        # --- List jobs ---
        if args.list_jobs:
            jobs = client.list_jobs(page_size=args.limit, status_filter=args.status)
            if not jobs:
                print("No jobs found.")
                return 0
            print(f"Found {len(jobs)} job(s):\n")
            for job in jobs:
                print(f"  {job['job_id']}  {job['status']:12s}  {job.get('created_at', 'N/A')}")
            return 0

        # --- Check status ---
        if args.check_status:
            status = client.get_status(args.check_status)
            progress = status.get("progress", {})
            print(f"Job:      {args.check_status}")
            print(f"Status:   {status['status']}")
            print(f"Progress: {progress.get('percent_complete', 0):.1f}%  "
                  f"({progress.get('completed_conversations', 0)}/{progress.get('total_conversations', 0)} conversations)")
            if status.get("error_message"):
                print(f"Error:    {status['error_message']}")
            return 0

        # --- Cancel job ---
        if args.cancel_job:
            result = client.cancel_job(args.cancel_job)
            print(f"Cancelled: {result.get('status')}")
            return 0

        # --- Submit evaluation ---
        missing = [name for name, val in [
            ("--csv-file", args.csv_file),
            ("--action-id", args.action_id),
            ("--base-url", args.base_url),
            ("--cookie", args.cookie),
        ] if not val]

        if missing:
            parser.error(f"Missing required arguments for submission: {', '.join(missing)}")

        result_file = client.submit_and_wait(
            csv_file=args.csv_file,
            config={
                "action_id": args.action_id,
                "base_url": args.base_url,
                "security_params": {"cookie": args.cookie},
                "batch_size": args.batch_size,
                "skip_maxim": args.skip_maxim,
            },
            output_file=args.output,
            poll_interval=args.poll_interval,
            verbose=not args.quiet,
            skip_validation=args.skip_validation,
            auto_timestamp=args.auto_timestamp,
        )

        print(f"\nResults saved to: {result_file}")
        return 0

    except FIFOClientError as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
