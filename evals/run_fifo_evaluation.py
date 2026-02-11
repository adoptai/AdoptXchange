#!/usr/bin/env python3
"""
Command-line interface for FIFO Evals Client.

This script provides a convenient CLI for running evaluations without writing Python code.

Examples:
    # Basic usage with all required arguments
    python run_fifo_evaluation.py \\
        --csv-file test.csv \\
        --action-id action_rallyup_assistant \\
        --base-url https://go.rallyup.com \\
        --cookie "session=abc123" \\
        --api-key your_api_key \\
        --output results.csv

    # Using API key from environment
    export ADOPT_API_KEY=your_api_key
    python run_fifo_evaluation.py \\
        --csv-file test.csv \\
        --action-id action_rallyup_assistant \\
        --base-url https://go.rallyup.com \\
        --cookie "session=abc123"

    # With custom batch size and Maxim disabled
    python run_fifo_evaluation.py \\
        --csv-file large_test.csv \\
        --action-id action_rallyup_assistant \\
        --base-url https://go.rallyup.com \\
        --cookie "session=abc123" \\
        --batch-size 10 \\
        --skip-maxim \\
        --output results_large.csv

    # With timestamped output filename
    python run_fifo_evaluation.py \\
        --csv-file test.csv \\
        --action-id action_rallyup_assistant \\
        --base-url https://go.rallyup.com \\
        --cookie "session=abc123" \\
        --output results.csv \\
        --auto-timestamp

    # List all evaluation jobs
    python run_fifo_evaluation.py --list-jobs --api-key your_api_key

    # List completed jobs only
    python run_fifo_evaluation.py --list-jobs --status completed --api-key your_api_key

    # Check status of specific job
    python run_fifo_evaluation.py --check-status abc-123 --api-key your_api_key

    # Cancel a running job
    python run_fifo_evaluation.py --cancel-job abc-123 --api-key your_api_key
"""

import sys
import os
import argparse
from pathlib import Path

# Add parent directory to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from AdoptXchange.evals.fifo_client import FIFOEvalsClient, FIFOClientError


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="FIFO Evals Client - Async evaluation job submission",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Submit evaluation job
  python run_fifo_evaluation.py \\
      --csv-file test.csv \\
      --action-id action_rallyup_assistant \\
      --base-url https://go.rallyup.com \\
      --cookie "session=abc123" \\
      --api-key your_api_key

  # List all jobs
  python run_fifo_evaluation.py --list-jobs --api-key your_api_key

  # Check job status
  python run_fifo_evaluation.py --check-status abc-123 --api-key your_api_key

  # Cancel job
  python run_fifo_evaluation.py --cancel-job abc-123 --api-key your_api_key

Environment Variables:
  ADOPT_API_KEY       - API key (alternative to --api-key)
  ADOPT_API_BASE_URL  - Base URL (default: https://api.adopt.ai)
        """
    )

    # API configuration
    parser.add_argument(
        '--api-key',
        type=str,
        default=os.environ.get('ADOPT_API_KEY'),
        help='API key for authentication (or set ADOPT_API_KEY env var)'
    )

    parser.add_argument(
        '--api-base-url',
        type=str,
        default=os.environ.get('ADOPT_API_BASE_URL', 'https://api.adopt.ai'),
        help='Base URL for API (default: https://api.adopt.ai)'
    )

    # Job submission arguments
    submission_group = parser.add_argument_group('Job Submission')

    submission_group.add_argument(
        '--csv-file',
        type=str,
        help='Path to CSV file with test data'
    )

    submission_group.add_argument(
        '--action-id',
        type=str,
        help='Action ID to evaluate (e.g., action_rallyup_assistant)'
    )

    submission_group.add_argument(
        '--base-url',
        type=str,
        help='Customer API base URL (e.g., https://go.rallyup.com)'
    )

    submission_group.add_argument(
        '--cookie',
        type=str,
        help='Session cookie for authentication (e.g., "session=abc123")'
    )

    submission_group.add_argument(
        '--output',
        type=str,
        default='results.csv',
        help='Output CSV filename (default: results.csv)'
    )

    submission_group.add_argument(
        '--batch-size',
        type=int,
        default=5,
        help='Batch size for processing (default: 5)'
    )

    submission_group.add_argument(
        '--skip-maxim',
        action='store_true',
        help='Skip Maxim evaluation'
    )

    submission_group.add_argument(
        '--poll-interval',
        type=int,
        default=30,
        help='Status polling interval in seconds (default: 30)'
    )

    submission_group.add_argument(
        '--auto-timestamp',
        action='store_true',
        help='Append timestamp to output filename'
    )

    submission_group.add_argument(
        '--quiet',
        action='store_true',
        help='Suppress progress output'
    )

    submission_group.add_argument(
        '--skip-validation',
        action='store_true',
        help='Skip client-side CSV validation (not recommended)'
    )

    # Job management arguments
    management_group = parser.add_argument_group('Job Management')

    management_group.add_argument(
        '--list-jobs',
        action='store_true',
        help='List all evaluation jobs'
    )

    management_group.add_argument(
        '--status',
        type=str,
        choices=['pending', 'processing', 'completed', 'failed', 'cancelled'],
        help='Filter jobs by status (use with --list-jobs)'
    )

    management_group.add_argument(
        '--limit',
        type=int,
        default=50,
        help='Maximum number of jobs to list (default: 50, max: 100)'
    )

    management_group.add_argument(
        '--check-status',
        type=str,
        metavar='JOB_ID',
        help='Check status of specific job'
    )

    management_group.add_argument(
        '--cancel-job',
        type=str,
        metavar='JOB_ID',
        help='Cancel a running or pending job'
    )

    args = parser.parse_args()

    # Validate API key
    if not args.api_key:
        parser.error(
            "API key required. Provide via --api-key or set ADOPT_API_KEY environment variable.\n\n"
            "Example:\n"
            "  export ADOPT_API_KEY=your_api_key\n"
            "  python run_fifo_evaluation.py --list-jobs"
        )

    try:
        # Create client
        client = FIFOEvalsClient(
            api_key=args.api_key,
            base_url=args.api_base_url
        )

        # Handle job management operations
        if args.list_jobs:
            print(f"📋 Listing jobs (limit: {args.limit})")
            if args.status:
                print(f"   Filter: status={args.status}")
            print()

            jobs = client.list_jobs(limit=args.limit, status_filter=args.status)

            if not jobs:
                print("No jobs found.")
                return 0

            print(f"Found {len(jobs)} job(s):\n")
            for job in jobs:
                status_emoji = {
                    'pending': '⏳',
                    'processing': '🔄',
                    'completed': '✅',
                    'failed': '❌',
                    'cancelled': '⚠️'
                }.get(job['status'], '❓')

                print(f"{status_emoji} {job['job_id']}")
                print(f"   Status: {job['status']}")
                print(f"   Submitted: {job.get('submitted_at', 'N/A')}")
                if 'total_conversations' in job:
                    print(f"   Conversations: {job['total_conversations']}")
                print()

            return 0

        elif args.check_status:
            print(f"🔍 Checking status of job: {args.check_status}\n")
            status = client.get_status(args.check_status)

            status_emoji = {
                'pending': '⏳',
                'processing': '🔄',
                'completed': '✅',
                'failed': '❌',
                'cancelled': '⚠️'
            }.get(status['status'], '❓')

            print(f"{status_emoji} Status: {status['status']}")
            print(f"   Job ID: {args.check_status}")

            progress = status.get('progress', {})
            if progress:
                print(f"   Progress: {progress.get('percent_complete', 0):.1f}%")
                print(f"   Conversations: {progress.get('completed_conversations', 0)}/{progress.get('total_conversations', 0)}")
                print(f"   Turns: {progress.get('completed_turns', 0)}/{progress.get('total_turns', 0)}")

            return 0

        elif args.cancel_job:
            print(f"⚠️  Cancelling job: {args.cancel_job}\n")
            result = client.cancel_job(args.cancel_job)
            print(f"✅ Job cancelled successfully")
            print(f"   Cancelled at: {result.get('cancelled_at', 'N/A')}")
            return 0

        # Handle job submission
        else:
            # Validate required arguments for submission
            required_args = ['csv_file', 'action_id', 'base_url', 'cookie']
            missing = [arg for arg in required_args if not getattr(args, arg)]

            if missing:
                parser.error(
                    f"Missing required arguments for job submission: {', '.join('--' + arg.replace('_', '-') for arg in missing)}\n\n"
                    "For job submission, you must provide:\n"
                    "  --csv-file PATH\n"
                    "  --action-id ACTION_ID\n"
                    "  --base-url BASE_URL\n"
                    "  --cookie COOKIE\n\n"
                    "Or use job management commands:\n"
                    "  --list-jobs\n"
                    "  --check-status JOB_ID\n"
                    "  --cancel-job JOB_ID"
                )

            # Submit and wait for completion
            result_file = client.submit_and_wait(
                csv_file=args.csv_file,
                config={
                    'action_id': args.action_id,
                    'base_url': args.base_url,
                    'security_params': {'cookie': args.cookie},
                    'batch_size': args.batch_size,
                    'skip_maxim': args.skip_maxim
                },
                output_file=args.output,
                poll_interval=args.poll_interval,
                verbose=not args.quiet,
                skip_validation=args.skip_validation,
                auto_timestamp=args.auto_timestamp
            )

            print(f"\n✅ Evaluation complete!")
            print(f"📄 Results saved to: {result_file}")
            return 0

    except FIFOClientError as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        return 1

    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user", file=sys.stderr)
        return 130

    except Exception as e:
        print(f"\n❌ Unexpected error: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
