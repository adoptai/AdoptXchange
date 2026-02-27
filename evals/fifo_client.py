"""
FIFO Evals Service Client for AdoptXchange

Submits evaluation jobs to the Adopt.AI backend proxy (api.adopt.ai),
which forwards them to the adoptai-workflows FIFO engine.

Authentication uses client_id + client_secret, exchanged for a Frontegg JWT
via POST /v1/users/api-token. Tokens auto-refresh before expiry.

Usage:
    from AdoptXchange.evals.fifo_client import FIFOEvalsClient

    client = FIFOEvalsClient(client_id="your_id", client_secret="your_secret")
    job_id = client.submit_evaluation("test.csv", config={...})
    result = client.wait_for_completion(job_id)

    # Or with environment variables (ADOPT_CLIENT_ID, ADOPT_CLIENT_SECRET):
    client = FIFOEvalsClient.from_env()
"""

import sys
import os
import ast
from datetime import datetime

# Windows console encoding fix for Unicode output (emojis, progress indicators)
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

import httpx
import time
import json
import csv
from typing import Dict, Optional, Any, List
from pathlib import Path


# Custom Exceptions
class FIFOClientError(Exception):
    """Base exception for FIFO client errors."""
    pass


class ValidationError(FIFOClientError):
    """CSV validation failed."""
    pass


class AuthenticationError(FIFOClientError):
    """Authentication failed (invalid or expired token)."""
    pass


class JobNotFoundError(FIFOClientError):
    """Job not found or not accessible."""
    pass


class JobFailedError(FIFOClientError):
    """Job execution failed."""
    def __init__(self, job_id: str, error_message: str, status_data: Dict = None):
        self.job_id = job_id
        self.error_message = error_message
        self.status_data = status_data or {}
        super().__init__(f"Job {job_id} failed: {error_message}")


# Helper functions
def truncate_string(text: str, max_length: int, suffix: str = "...") -> str:
    """
    Truncate a string to max_length characters for user-friendly display.

    Args:
        text: String to truncate
        max_length: Maximum length before truncation
        suffix: Suffix to append when truncated (default: "...")

    Returns:
        Truncated string with suffix if needed
    """
    if not text or len(text) <= max_length:
        return text
    return text[:max_length] + suffix


def safe_json_parse(json_str: str, fallback: Any = None) -> Any:
    """
    Parse JSON string with fallback to ast.literal_eval for malformed JSON.

    This handles cases where the server returns Python dict strings instead of JSON,
    or where JSON has trailing commas or other minor issues.

    Args:
        json_str: String to parse
        fallback: Value to return if all parsing fails (default: None)

    Returns:
        Parsed object or fallback value
    """
    if not json_str:
        return fallback

    # Try json.loads first (standard)
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback to ast.literal_eval (handles Python dict strings)
    try:
        return ast.literal_eval(json_str)
    except (ValueError, SyntaxError):
        pass

    # All parsing failed
    return fallback


class FIFOEvalsClient:
    """
    Client for FIFO Evals Service via the Adopt.AI backend proxy.

    Authenticates with client_id + client_secret (Frontegg API credentials),
    then submits evaluation jobs with progress tracking.

    The backend proxy extracts org_id from the JWT — the client never
    sends it explicitly.
    """

    # Validation constants
    MAX_CSV_SIZE_MB = 100
    MAX_CSV_ROWS = 10000
    REQUIRED_COLUMNS = ['input', 'prompt', 'user_message']  # At least one required

    # Refresh token 5 minutes before expiry
    _TOKEN_REFRESH_BUFFER_SECS = 300

    def __init__(
        self,
        client_id: str = None,
        client_secret: str = None,
        *,
        access_token: str = None,
        base_url: str = "https://api.adopt.ai",
        timeout: float = 30.0
    ):
        """
        Initialize FIFO Evals client.

        Provide either client_id + client_secret (recommended) for automatic
        token management, or a pre-obtained access_token for testing.

        Args:
            client_id: Frontegg API client ID
            client_secret: Frontegg API client secret
            access_token: Pre-obtained JWT (bypasses token exchange, no auto-refresh)
            base_url: Backend proxy URL (default: https://api.adopt.ai)
            timeout: HTTP timeout for API calls (not job execution timeout)
        """
        if access_token:
            # Pre-obtained token mode (no auto-refresh)
            self._client_id = None
            self._client_secret = None
            self._access_token = access_token
            self._token_expires_at = None  # Unknown expiry, no refresh
        elif client_id and client_secret:
            # Credential mode (auto token exchange + refresh)
            self._client_id = client_id
            self._client_secret = client_secret
            self._access_token = None
            self._token_expires_at = 0  # Force immediate auth on first call
        else:
            raise ValueError(
                "Provide either (client_id + client_secret) or access_token.\n\n"
                "Example:\n"
                "  client = FIFOEvalsClient(client_id='...', client_secret='...')\n"
                "  # or\n"
                "  client = FIFOEvalsClient(access_token='pre-obtained-jwt')"
            )

        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.client = httpx.Client(timeout=timeout)

    @classmethod
    def from_env(cls, base_url: str = "https://api.adopt.ai", **kwargs) -> "FIFOEvalsClient":
        """
        Create client from environment variables.

        Reads ADOPT_CLIENT_ID and ADOPT_CLIENT_SECRET from environment
        (or .env file via dotenv).

        Args:
            base_url: Backend proxy URL override
            **kwargs: Additional arguments passed to constructor
        """
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass

        client_id = os.environ.get("ADOPT_CLIENT_ID")
        client_secret = os.environ.get("ADOPT_CLIENT_SECRET")

        if not client_id or not client_secret:
            raise ValueError(
                "ADOPT_CLIENT_ID and ADOPT_CLIENT_SECRET environment variables are required.\n"
                "Set them in your environment or in a .env file."
            )

        return cls(client_id=client_id, client_secret=client_secret, base_url=base_url, **kwargs)

    def _authenticate(self):
        """
        Exchange client_id + client_secret for a JWT via the backend token endpoint.

        Raises:
            AuthenticationError: If token exchange fails
        """
        try:
            response = self.client.post(
                f"{self.base_url}/v1/users/api-token",
                json={"client_id": self._client_id, "secret": self._client_secret},
            )

            if response.status_code == 401:
                raise AuthenticationError(
                    "Invalid client credentials.\n"
                    "Check your ADOPT_CLIENT_ID and ADOPT_CLIENT_SECRET."
                )

            response.raise_for_status()
            data = response.json()

            self._access_token = data["access_token"]
            # expires_in is seconds from now; store absolute expiry time
            expires_in = data.get("expires_in", 3600)
            self._token_expires_at = time.time() + expires_in

        except AuthenticationError:
            raise
        except httpx.HTTPStatusError as e:
            raise AuthenticationError(
                f"Token exchange failed: HTTP {e.response.status_code}\n"
                f"Response: {e.response.text}"
            ) from e
        except httpx.ConnectError as e:
            raise FIFOClientError(
                f"Cannot connect to {self.base_url} for authentication.\n"
                f"Check that the URL is correct and the service is running."
            ) from e

    def _get_auth_headers(self) -> Dict[str, str]:
        """
        Get authorization headers, refreshing the token if needed.

        Returns:
            Dict with Authorization header
        """
        if self._client_id and self._client_secret:
            # Auto-refresh if token is missing or about to expire
            if (
                self._access_token is None
                or (self._token_expires_at and time.time() > self._token_expires_at - self._TOKEN_REFRESH_BUFFER_SECS)
            ):
                self._authenticate()

        return {"Authorization": f"Bearer {self._access_token}"}

    def _validate_csv_file(self, csv_file: str) -> Dict[str, Any]:
        """
        Validate CSV file before submission.

        Args:
            csv_file: Path to CSV file

        Returns:
            Dict with validation info (row_count, size_mb, columns)

        Raises:
            ValidationError: If validation fails
            FileNotFoundError: If file doesn't exist
        """
        # Resolve and validate path
        try:
            csv_path = Path(csv_file).resolve()
        except Exception as e:
            raise ValidationError(f"Invalid file path: {csv_file}") from e

        # Check file exists
        if not csv_path.exists():
            raise FileNotFoundError(
                f"CSV file not found: {csv_file}\n"
                f"Resolved path: {csv_path}"
            )

        # Check it's a file (not directory)
        if not csv_path.is_file():
            raise ValidationError(
                f"Not a file: {csv_file}\n"
                f"Expected a CSV file, got: {csv_path}"
            )

        # Check file extension (optional but recommended)
        if csv_path.suffix.lower() not in ['.csv', '.txt', '']:
            raise ValidationError(
                f"Unexpected file extension: {csv_path.suffix}\n"
                f"Expected .csv file. If this is a CSV, rename it to {csv_path.stem}.csv"
            )

        # Check file size
        size_bytes = csv_path.stat().st_size
        size_mb = size_bytes / 1024 / 1024

        if size_mb > self.MAX_CSV_SIZE_MB:
            raise ValidationError(
                f"CSV file too large: {size_mb:.1f} MB (max {self.MAX_CSV_SIZE_MB} MB)\n\n"
                f"Solution: Split your CSV into smaller files:\n"
                f"  from AdoptXchange.evals.csv_utils import split_csv\n"
                f"  chunks = split_csv('{csv_file}', max_rows={self.MAX_CSV_ROWS})\n"
                f"  # Then submit each chunk separately"
            )

        # Check row count and columns with encoding fallback
        header = None
        row_count = 0
        rows_data = []
        encoding_used = None
        skipped_rows = []  # Track blank/whitespace-only rows

        # Try multiple encodings
        for encoding in ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252', 'iso-8859-1']:
            try:
                with open(csv_path, 'r', encoding=encoding, errors='replace') as f:
                    reader = csv.DictReader(f)
                    try:
                        # Read all rows and filter blank/whitespace-only rows
                        raw_rows = list(reader)
                        header = reader.fieldnames

                        # Filter out blank rows and whitespace-only rows
                        for idx, row in enumerate(raw_rows, start=2):  # Start at 2 (after header)
                            # Check if row is completely empty or all values are whitespace
                            is_blank = all(
                                not value or not str(value).strip()
                                for value in row.values()
                            )

                            if is_blank:
                                skipped_rows.append(idx)
                            else:
                                # Strip whitespace from all values
                                cleaned_row = {
                                    key: str(value).strip() if value else ''
                                    for key, value in row.items()
                                }
                                rows_data.append(cleaned_row)

                        row_count = len(rows_data)
                        encoding_used = encoding
                        break
                    except StopIteration:
                        raise ValidationError("CSV file is empty")
            except Exception as e:
                if encoding == 'iso-8859-1':  # Last attempt
                    raise ValidationError(
                        f"Cannot read CSV file with any supported encoding.\n"
                        f"Tried: utf-8, utf-8-sig, latin-1, cp1252, iso-8859-1\n"
                        f"Error: {e}"
                    ) from e
                continue

        if not header:
            raise ValidationError("Could not parse CSV file header")

        # Check row count
        if row_count == 0:
            raise ValidationError("CSV file has no data rows (only header)")

        if row_count > self.MAX_CSV_ROWS:
            raise ValidationError(
                f"CSV has too many rows: {row_count} (max {self.MAX_CSV_ROWS})\n\n"
                f"Solution: Split your CSV:\n"
                f"  from AdoptXchange.evals.csv_utils import split_csv\n"
                f"  chunks = split_csv('{csv_file}', max_rows={self.MAX_CSV_ROWS})\n"
                f"  # Submit {(row_count + self.MAX_CSV_ROWS - 1) // self.MAX_CSV_ROWS} jobs"
            )

        # Check required columns with flexible matching
        header_lower = {col.lower(): col for col in header}

        # Check for input column variants
        input_variants = ['input', 'prompt', 'user_message', 'message']
        input_col = next((header_lower.get(variant) for variant in input_variants if variant in header_lower), None)

        if not input_col:
            variants_str = ', '.join(f"'{v}'" for v in input_variants)
            raise ValidationError(
                f"CSV missing required input column.\n"
                f"Found columns: {', '.join(header)}\n"
                f"Required: At least one of: {variants_str}"
            )

        # Check for ID column variants (optional but check if present)
        id_variants = ['input_id', 'conversation_id', 'id']
        id_col = next((header_lower.get(variant) for variant in id_variants if variant in header_lower), None)

        # Report skipped rows
        warnings = []
        if skipped_rows:
            if len(skipped_rows) <= 5:
                skipped_rows_str = ", ".join(str(r) for r in skipped_rows)
                warnings.append(
                    f"Skipped {len(skipped_rows)} blank/whitespace-only row(s) at line(s): {skipped_rows_str}"
                )
            else:
                warnings.append(
                    f"Skipped {len(skipped_rows)} blank/whitespace-only rows "
                    f"(first 5 at lines: {', '.join(str(r) for r in skipped_rows[:5])}, ...)"
                )

        # Analyze ID structure if ID column exists
        multi_turn_count = 0
        single_turn_count = 0
        empty_id_count = 0

        if id_col:
            from collections import Counter
            ids = [row[id_col].strip() for row in rows_data if row.get(id_col, '').strip()]
            empty_id_count = sum(1 for row in rows_data if not row.get(id_col, '').strip())

            if ids:
                id_counts = Counter(ids)
                multi_turn_count = sum(1 for count in id_counts.values() if count > 1)
                single_turn_count = sum(1 for count in id_counts.values() if count == 1)

                # Generate warnings for edge cases
                if empty_id_count > 0:
                    warnings.append(
                        f"Found {empty_id_count} rows with empty '{id_col}'. "
                        f"These will be treated as separate single-turn conversations."
                    )

                if multi_turn_count > 0 and single_turn_count > 0:
                    warnings.append(
                        f"Mixed conversation structure: {multi_turn_count} multi-turn, "
                        f"{single_turn_count} single-turn conversations."
                    )
        else:
            # No ID column - all single-turn
            single_turn_count = row_count
            warnings.append(
                f"No ID column found. All {row_count} rows will be treated as separate single-turn conversations. "
                f"To enable multi-turn conversations, add an '{id_variants[0]}' column."
            )

        validation_result = {
            "path": str(csv_path),
            "row_count": row_count,
            "size_mb": size_mb,
            "columns": header,
            "encoding": encoding_used,
            "input_column": input_col,
            "id_column": id_col,
            "skipped_rows": skipped_rows,  # List of line numbers that were skipped
            "conversation_stats": {
                "multi_turn": multi_turn_count,
                "single_turn": single_turn_count,
                "empty_ids": empty_id_count,
                "total_conversations": multi_turn_count + single_turn_count + empty_id_count
            },
            "warnings": warnings
        }

        return validation_result

    def _handle_http_error(self, error: httpx.HTTPStatusError, context: str = ""):
        """
        Convert HTTP errors to user-friendly exceptions.

        Args:
            error: HTTP error from httpx
            context: Additional context about what failed

        Raises:
            Specific exception based on error type
        """
        status_code = error.response.status_code

        # Try to parse error response
        # FastAPI returns {"detail": "..."}, support both FastAPI and generic formats
        try:
            error_data = error.response.json()
            error_message = (
                error_data.get('detail')
                or error_data.get('message')
                or str(error)
            )
            error_details = error_data.get('details', {})
        except Exception:
            error_message = str(error)
            error_details = {}

        # 400: Validation errors
        if status_code == 400:
            raise ValidationError(
                f"CSV validation failed: {error_message}\n"
                f"Details: {error_details}"
            ) from error

        # 401: Authentication errors
        elif status_code == 401:
            raise AuthenticationError(
                f"Authentication failed: {error_message}\n\n"
                f"Possible causes:\n"
                f"  1. Invalid client credentials\n"
                f"  2. Expired token (tokens expire after 1 hour)\n"
                f"  3. Missing Authorization header\n\n"
                f"Solution: Check your ADOPT_CLIENT_ID and ADOPT_CLIENT_SECRET,\n"
                f"or create a new client:\n"
                f"  client = FIFOEvalsClient(client_id='...', client_secret='...')"
            ) from error

        # 404: Not found
        elif status_code == 404:
            raise JobNotFoundError(
                f"Job not found: {error_message}\n"
                f"Context: {context}"
            ) from error

        # 413: Payload too large
        elif status_code == 413:
            raise ValidationError(
                f"File too large: {error_message}\n\n"
                f"Solution: Split your CSV into smaller chunks:\n"
                f"  from AdoptXchange.evals.csv_utils import split_csv\n"
                f"  chunks = split_csv('large_file.csv', max_rows={self.MAX_CSV_ROWS})"
            ) from error

        # Other errors
        else:
            raise FIFOClientError(
                f"HTTP {status_code} error: {error_message}\n"
                f"Context: {context}"
            ) from error

    def submit_evaluation(
        self,
        csv_file: str,
        config: Dict,
        skip_validation: bool = False
    ) -> str:
        """
        Submit evaluation job (returns immediately in <1 second).

        Args:
            csv_file: Path to CSV file with evaluation data
            config: Job configuration
            skip_validation: Skip client-side validation (not recommended)

        Returns:
            job_id: Job identifier for status tracking

        Raises:
            ValidationError: If CSV validation fails
            AuthenticationError: If authentication fails
            FileNotFoundError: If CSV file not found
            FIFOClientError: For other errors

        Example:
            >>> client = FIFOEvalsClient(client_id="...", client_secret="...")
            >>> job_id = client.submit_evaluation(
            ...     csv_file="test.csv",
            ...     config={
            ...         "action_id": "action_rallyup_assistant",
            ...         "base_url": "https://go.rallyup.com",
            ...         "security_params": {"cookie": "session=abc123"}
            ...     }
            ... )
        """
        # Validate CSV file
        if not skip_validation:
            validation_info = self._validate_csv_file(csv_file)
            csv_path = Path(validation_info["path"])

            # Display validation warnings if any
            if validation_info.get("warnings"):
                print("\n  CSV Validation Warnings:")
                for warning in validation_info["warnings"]:
                    print(f"   - {warning}")
                print()

            # Display conversation stats
            stats = validation_info.get("conversation_stats", {})
            if stats:
                total_convs = stats.get("total_conversations", 0)
                multi = stats.get("multi_turn", 0)
                single = stats.get("single_turn", 0)
                print(f"CSV Analysis:")
                print(f"   - {validation_info['row_count']} total rows")
                print(f"   - {total_convs} conversations ({multi} multi-turn, {single} single-turn)")
                print(f"   - Input column: '{validation_info['input_column']}'")
                if validation_info.get('id_column'):
                    print(f"   - ID column: '{validation_info['id_column']}'")
                print()
        else:
            csv_path = Path(csv_file).resolve()

        # Submit job
        try:
            with open(csv_path, 'rb') as f:
                response = self.client.post(
                    f"{self.base_url}/v2/evals/submit",
                    files={"file": (csv_path.name, f, "text/csv")},
                    data={"config": json.dumps(config)},
                    headers=self._get_auth_headers(),
                )

            response.raise_for_status()
            result = response.json()

            # Validate response has required fields
            if "job_id" not in result:
                raise FIFOClientError(
                    "Invalid server response: missing 'job_id' field"
                )

            return result["job_id"]

        except httpx.HTTPStatusError as e:
            self._handle_http_error(e, context="submitting evaluation")

        except httpx.TimeoutException as e:
            raise FIFOClientError(
                f"Request timed out after {self.timeout}s. "
                f"Check network connection or try again."
            ) from e

        except httpx.ConnectError as e:
            raise FIFOClientError(
                f"Cannot connect to {self.base_url}. "
                f"Service may be down or URL is incorrect."
            ) from e

    def get_status(self, job_id: str) -> Dict:
        """
        Get current job status and progress.

        Args:
            job_id: Job identifier from submit_evaluation()

        Returns:
            Status dictionary with progress metrics (with safe defaults)

        Raises:
            AuthenticationError: If authentication fails
            JobNotFoundError: If job not found
            FIFOClientError: For other errors
        """
        try:
            response = self.client.get(
                f"{self.base_url}/v2/evals/{job_id}/status",
                headers=self._get_auth_headers(),
            )

            response.raise_for_status()
            raw = response.json()

            # Defensive: ensure required fields exist
            if "status" not in raw:
                raise FIFOClientError("Invalid server response: missing 'status' field")

            # Server returns flat EvalJobProgressResponse; reshape into
            # the nested format the client exposes:
            #   { "status": "...", "progress": { ... }, "error_message": "...", ... }
            result = {
                "job_id": raw.get("job_id", ""),
                "status": raw["status"],
                "error_message": raw.get("error_message"),
                "started_at": raw.get("started_at"),
                "completed_at": raw.get("completed_at"),
                "progress": {
                    "total_conversations": raw.get("total_conversations", 0) or 0,
                    "completed_conversations": raw.get("completed_conversations", 0) or 0,
                    "total_turns": raw.get("total_turns", 0) or 0,
                    "completed_turns": raw.get("completed_turns", 0) or 0,
                    "percent_complete": raw.get("percent_complete", 0.0) or 0.0,
                },
                "metrics": {
                    "successful_conversations": raw.get("successful_conversations"),
                    "failed_conversations": raw.get("failed_conversations"),
                    "successful_turns": raw.get("successful_turns"),
                    "failed_turns": raw.get("failed_turns"),
                    "average_latency_ms": raw.get("average_latency_ms"),
                },
            }

            return result

        except httpx.HTTPStatusError as e:
            self._handle_http_error(e, context=f"getting status for job {job_id}")

        except httpx.TimeoutException as e:
            raise FIFOClientError(
                f"Status check timed out. Try again."
            ) from e

    def wait_for_completion(
        self,
        job_id: str,
        poll_interval: int = 30,
        verbose: bool = True
    ) -> Dict:
        """
        Wait for job to complete (blocks until done).

        Args:
            job_id: Job identifier
            poll_interval: Seconds between status checks (default: 30)
            verbose: Print progress updates (default: True)

        Returns:
            Result dictionary with download URLs

        Raises:
            JobFailedError: If job execution fails
            AuthenticationError: If authentication fails
            FIFOClientError: For other errors
        """
        start_time = time.time()
        last_completed = 0

        while True:
            status = self.get_status(job_id)

            # Check if completed
            if status["status"] == "completed":
                elapsed = time.time() - start_time
                if verbose:
                    print(f"\nJob completed in {elapsed / 60:.1f} minutes")
                return self.get_result(job_id)

            # Check if failed
            if status["status"] == "failed":
                error_msg = status.get("error_message") or "Unknown error"
                # Truncate error message for display
                truncated_error = truncate_string(error_msg, 100)
                if verbose:
                    print(f"\nJob failed: {truncated_error}")
                raise JobFailedError(
                    job_id=job_id,
                    error_message=error_msg,
                    status_data=status
                )

            # Check if cancelled
            if status["status"] == "cancelled":
                if verbose:
                    print(f"\nJob was cancelled")
                raise FIFOClientError(f"Job {job_id} was cancelled")

            # Print progress (only if changed)
            progress = status.get("progress", {})
            completed_convs = progress.get("completed_conversations", 0)
            total_convs = progress.get("total_conversations", 0)
            percent = progress.get("percent_complete", 0.0)

            if verbose and completed_convs != last_completed:
                print(
                    f"Progress: {percent:.1f}% "
                    f"({completed_convs} of {total_convs} conversations)"
                )
                last_completed = completed_convs

            # Wait before next poll
            time.sleep(poll_interval)

    def get_result(self, job_id: str) -> Dict:
        """
        Get job result with download URLs.

        Args:
            job_id: Job identifier

        Returns:
            Result dictionary with csv_download_url and report_url

        Raises:
            JobNotFoundError: If job not found or not ready
            AuthenticationError: If authentication fails
            FIFOClientError: For other errors
        """
        try:
            response = self.client.get(
                f"{self.base_url}/v2/evals/{job_id}/results",
                headers=self._get_auth_headers(),
            )

            response.raise_for_status()
            result = response.json()

            # Validate required fields -- server returns csv_download_url
            if "csv_download_url" not in result:
                raise FIFOClientError(
                    f"Invalid server response: missing 'csv_download_url'\n"
                    f"Job status: {result.get('status', 'unknown')}. "
                    f"Job may not be completed yet. Check status first."
                )

            return result

        except httpx.HTTPStatusError as e:
            self._handle_http_error(e, context=f"getting result for job {job_id}")

    def list_jobs(
        self,
        page: int = 1,
        page_size: int = 20,
        status_filter: str = None
    ) -> List[Dict]:
        """
        List all evaluation jobs for current org.

        Args:
            page: Page number, 1-indexed (default: 1)
            page_size: Number of jobs per page (default: 20, max: 100)
            status_filter: Filter by status (pending, processing, completed, failed, cancelled)

        Returns:
            List of job summaries

        Raises:
            AuthenticationError: If authentication fails
            ValidationError: If parameters are invalid
            FIFOClientError: For other errors

        Example:
            >>> # List all jobs
            >>> jobs = client.list_jobs()
            >>>
            >>> # List only completed jobs
            >>> completed = client.list_jobs(status_filter="completed")
            >>>
            >>> # List with pagination
            >>> page2 = client.list_jobs(page=2, page_size=50)
        """
        # Validate parameters
        if page < 1:
            raise ValidationError("page must be >= 1")
        if page_size < 1 or page_size > 100:
            raise ValidationError("page_size must be between 1 and 100")

        # Validate status_filter if provided
        valid_statuses = ["pending", "processing", "completed", "failed", "cancelled"]
        if status_filter and status_filter not in valid_statuses:
            raise ValidationError(
                f"Invalid status_filter: '{status_filter}'\n"
                f"Valid values: {', '.join(valid_statuses)}"
            )

        try:
            # Build query parameters (no org_id -- proxy extracts from JWT)
            params = {
                "page": page,
                "page_size": page_size,
            }
            if status_filter:
                params["status"] = status_filter

            response = self.client.get(
                f"{self.base_url}/v2/evals/jobs",
                params=params,
                headers=self._get_auth_headers(),
            )

            response.raise_for_status()
            result = response.json()

            # Validate response format
            if "jobs" not in result:
                # Defensive: return empty list if malformed response
                return []

            return result["jobs"]

        except httpx.HTTPStatusError as e:
            self._handle_http_error(e, context="listing jobs")

    def cancel_job(self, job_id: str) -> Dict:
        """
        Cancel a running or pending evaluation job.

        Args:
            job_id: Job identifier to cancel

        Returns:
            Updated job status with cancellation details

        Raises:
            AuthenticationError: If authentication fails
            JobNotFoundError: If job doesn't exist
            ValidationError: If job cannot be cancelled (already completed/failed)
            FIFOClientError: For other errors

        Example:
            >>> result = client.cancel_job("abc-123")
            >>> print(f"Cancelled at: {result['cancelled_at']}")
        """
        try:
            response = self.client.post(
                f"{self.base_url}/v2/evals/{job_id}/cancel",
                headers=self._get_auth_headers(),
            )

            response.raise_for_status()
            result = response.json()

            # Validate response has required fields
            if "status" not in result:
                # Defensive: provide default
                result["status"] = "cancelled"

            return result

        except httpx.HTTPStatusError as e:
            self._handle_http_error(e, context=f"cancelling job {job_id}")

    def download_results(self, result: Dict, output_file: str) -> str:
        """
        Download result CSV from presigned URL.

        Args:
            result: Result dictionary from get_result()
            output_file: Local path to save CSV

        Returns:
            Path to downloaded file

        Raises:
            ValidationError: If result missing csv_download_url
            FIFOClientError: For download errors
        """
        # Validate result has URL -- server returns csv_download_url
        if "csv_download_url" not in result:
            raise ValidationError(
                "Result missing 'csv_download_url'. "
                f"Job status: {result.get('status', 'unknown')}\n"
                f"Job may not be completed yet. Check status first."
            )

        url = result["csv_download_url"]

        try:
            # Download using presigned URL (no auth needed)
            response = self.client.get(url)
            response.raise_for_status()

            # Write to file
            output_path = Path(output_file)
            output_path.write_bytes(response.content)

            # Print confirmation
            size_kb = len(response.content) / 1024
            print(f"Downloaded: {output_file} ({size_kb:.1f} KB)")

            return str(output_path)

        except httpx.HTTPStatusError as e:
            raise FIFOClientError(
                f"Failed to download results: HTTP {e.response.status_code}"
            ) from e

        except Exception as e:
            raise FIFOClientError(
                f"Failed to write file: {output_file}\n"
                f"Error: {e}"
            ) from e

    def submit_and_wait(
        self,
        csv_file: str,
        config: Dict,
        output_file: str = "results.csv",
        poll_interval: int = 30,
        verbose: bool = True,
        skip_validation: bool = False,
        auto_timestamp: bool = False
    ) -> str:
        """
        Convenience method: submit, wait, and download in one call.

        Args:
            csv_file: Input CSV path
            config: Job configuration
            output_file: Output CSV path (default: "results.csv")
            poll_interval: Status poll interval (default: 30s)
            verbose: Print progress (default: True)
            skip_validation: Skip CSV validation (default: False)
            auto_timestamp: Auto-generate timestamped filename (default: False)

        Returns:
            Path to downloaded results file

        Raises:
            ValidationError: If CSV validation fails
            JobFailedError: If job execution fails
            AuthenticationError: If authentication fails
            FIFOClientError: For other errors
        """
        # Apply timestamp if requested
        if auto_timestamp:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = Path(output_file)
            output_file = str(output_path.parent / f"{output_path.stem}_{timestamp}{output_path.suffix}")

        # Submit job
        if verbose:
            print(f"Submitting evaluation job: {csv_file}")

        job_id = self.submit_evaluation(csv_file, config, skip_validation)

        if verbose:
            print(f"Job submitted: {job_id}\n")

        # Wait for completion
        result = self.wait_for_completion(job_id, poll_interval, verbose)

        # Download results
        return self.download_results(result, output_file)

    def __enter__(self):
        """Context manager support."""
        return self

    def __exit__(self, _exc_type, _exc_val, _exc_tb):
        """Close HTTP client on exit."""
        self.client.close()


# Convenience function for simple usage
def run_fifo_evaluation(
    csv_file: str,
    action_id: str,
    base_url: str,
    security_params: Dict,
    client_id: str,
    client_secret: str,
    output_file: str = "results.csv",
    batch_size: int = 5,
    skip_maxim: bool = False,
    verbose: bool = True
) -> str:
    """
    Simple function to run evaluation (convenience wrapper).

    Example:
        >>> result_file = run_fifo_evaluation(
        ...     csv_file="test.csv",
        ...     action_id="action_rallyup_assistant",
        ...     base_url="https://go.rallyup.com",
        ...     security_params={"cookie": "session=..."},
        ...     client_id="your_client_id",
        ...     client_secret="your_client_secret"
        ... )
    """
    with FIFOEvalsClient(client_id=client_id, client_secret=client_secret) as client:
        return client.submit_and_wait(
            csv_file=csv_file,
            config={
                "action_id": action_id,
                "base_url": base_url,
                "security_params": security_params,
                "batch_size": batch_size,
                "skip_maxim": skip_maxim
            },
            output_file=output_file,
            verbose=verbose
        )
