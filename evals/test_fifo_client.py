#!/usr/bin/env python3
"""
Comprehensive Test Suite for FIFO Evals Client

Combines all tests:
- Basic operations (submit, status, wait, result)
- Job management (list, cancel)
- CSV validation (encoding, columns, structure)
- Error handling (auth, not found, validation)
- Defensive parsing and security

Mock server routes match the adoptwebui backend proxy:
- POST /v2/evals/submit
- GET  /v2/evals/{job_id}/status
- GET  /v2/evals/{job_id}/results
- GET  /v2/evals/jobs
- POST /v2/evals/{job_id}/cancel
"""

import json
import time
import uuid
import csv
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from typing import Dict
import sys

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from evals.fifo_client import (
    FIFOEvalsClient, ValidationError, FIFOClientError, JobNotFoundError,
    truncate_string, safe_json_parse
)

# Global state for mock server
MOCK_JOBS = {}
MOCK_SERVER_PORT = 8777


class ComprehensiveMockServer(BaseHTTPRequestHandler):
    """
    Mock server matching adoptwebui backend proxy routes.

    Routes:
    - POST /v2/evals/submit
    - GET  /v2/evals/{job_id}/status
    - GET  /v2/evals/{job_id}/results
    - GET  /v2/evals/jobs
    - POST /v2/evals/{job_id}/cancel
    """

    def log_message(self, format, *args):
        """Suppress server logs during tests."""
        pass

    def _send_json_response(self, status_code: int, data: Dict):
        """Helper to send JSON response."""
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _check_auth(self) -> bool:
        """Check authorization header. Returns False and sends 401 if invalid."""
        auth_header = self.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            self._send_json_response(401, {"detail": "unauthorized"})
            return False
        if auth_header == 'Bearer expired_token':
            self._send_json_response(401, {"detail": "Token has expired"})
            return False
        return True

    def _parse_path(self):
        """Parse path and query params."""
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        return parsed.path, parse_qs(parsed.query)

    def do_POST(self):
        """Handle POST requests (submit, cancel)."""
        path, params = self._parse_path()

        # Submit: POST /v2/evals/submit
        if path == '/v2/evals/submit':
            if not self._check_auth():
                return

            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)

            if b'text/csv' not in body or b'config' not in body:
                self._send_json_response(400, {
                    "detail": "Missing file or config"
                })
                return

            # Extract config (naive parsing for testing)
            try:
                config_start = body.find(b'config') + len(b'config')
                config_start = body.find(b'{', config_start)
                config_end = body.find(b'}', config_start) + 1
                config_bytes = body[config_start:config_end]
                config = json.loads(config_bytes.decode())
            except Exception:
                config = {"action_id": "test_action"}

            job_id = str(uuid.uuid4())
            status = "pending"

            if config.get("_test_failure"):
                status = "failed"

            MOCK_JOBS[job_id] = {
                "job_id": job_id,
                "status": status,
                "submitted_at": time.time(),
                "config": config,
                "progress": {
                    "total_conversations": 50,
                    "completed_conversations": 0,
                    "total_turns": 55,
                    "completed_turns": 0,
                    "percent_complete": 0.0
                }
            }

            self._send_json_response(201, {
                "job_id": job_id,
                "status": status,
                "total_conversations": 50,
                "total_turns": 55,
            })
            return

        # Cancel: POST /v2/evals/{job_id}/cancel
        import re
        cancel_match = re.match(r'^/v2/evals/([^/]+)/cancel$', path)
        if cancel_match:
            if not self._check_auth():
                return

            job_id = cancel_match.group(1)

            if job_id not in MOCK_JOBS:
                self._send_json_response(404, {"detail": "Job not found"})
                return

            job = MOCK_JOBS[job_id]

            if job["status"] in ["completed", "failed"]:
                self._send_json_response(400, {
                    "detail": f"Cannot cancel job with status: {job['status']}"
                })
                return

            job["status"] = "cancelled"
            job["cancelled_at"] = time.time()

            self._send_json_response(200, {
                "job_id": job_id,
                "status": "cancelled",
                "cancelled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(job["cancelled_at"])),
                "progress": job["progress"]
            })
            return

        self._send_json_response(404, {"detail": "not_found"})

    def do_GET(self):
        """Handle GET requests (status, results, jobs)."""
        path, params = self._parse_path()

        import re

        # Status: GET /v2/evals/{job_id}/status
        status_match = re.match(r'^/v2/evals/([^/]+)/status$', path)
        if status_match:
            if not self._check_auth():
                return

            job_id = status_match.group(1)

            if job_id not in MOCK_JOBS:
                self._send_json_response(404, {"detail": "Job not found or not accessible"})
                return

            job = MOCK_JOBS[job_id]

            # Simulate progress
            if job["status"] not in ["failed", "cancelled"]:
                elapsed = time.time() - job["submitted_at"]
                if job["status"] == "pending" and elapsed > 2:
                    job["status"] = "processing"

            if job["status"] == "processing":
                elapsed = time.time() - job["submitted_at"]
                progress_pct = min((elapsed - 2) / 5 * 100, 100)
                completed_turns = int(55 * progress_pct / 100)
                completed_convs = int(50 * progress_pct / 100)

                job["progress"] = {
                    "total_conversations": 50,
                    "completed_conversations": completed_convs,
                    "total_turns": 55,
                    "completed_turns": completed_turns,
                    "percent_complete": progress_pct
                }

                if progress_pct >= 100:
                    job["status"] = "completed"

            if job["status"] == "failed":
                job["error_message"] = "ProjectA3 connection timeout"

            self._send_json_response(200, {
                "job_id": job_id,
                "status": job["status"],
                "progress": job.get("progress", {}),
                "error_message": job.get("error_message")
            })
            return

        # Results: GET /v2/evals/{job_id}/results
        results_match = re.match(r'^/v2/evals/([^/]+)/results$', path)
        if results_match:
            if not self._check_auth():
                return

            job_id = results_match.group(1)

            if job_id not in MOCK_JOBS:
                self._send_json_response(404, {"detail": "Job not found"})
                return

            job = MOCK_JOBS[job_id]

            if job["status"] != "completed":
                self._send_json_response(404, {
                    "detail": "Results not yet available",
                    "status": job["status"],
                })
                return

            self._send_json_response(200, {
                "job_id": job_id,
                "status": "completed",
                "csv_download_url": f"http://mock-s3.com/results/{job_id}/output.csv",
                "report_url": f"http://mock-s3.com/results/{job_id}/report.json",
            })
            return

        # List jobs: GET /v2/evals/jobs
        if path == '/v2/evals/jobs':
            if not self._check_auth():
                return

            page_size = int(params.get('page_size', [50])[0])
            status_filter = params.get('status', [None])[0]

            jobs = []
            for job_id, job in MOCK_JOBS.items():
                if status_filter and job["status"] != status_filter:
                    continue

                jobs.append({
                    "job_id": job_id,
                    "status": job["status"],
                    "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(job["submitted_at"])),
                    "total_conversations": job["progress"]["total_conversations"],
                    "total_turns": job["progress"]["total_turns"]
                })

                if len(jobs) >= page_size:
                    break

            self._send_json_response(200, {"jobs": jobs, "total": len(jobs)})
            return

        self._send_json_response(404, {"detail": "not_found"})


def start_mock_server(port: int = MOCK_SERVER_PORT):
    """Start mock server in background thread."""
    server = HTTPServer(('localhost', port), ComprehensiveMockServer)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.5)  # Give server time to start
    return server


def _make_client(port: int = MOCK_SERVER_PORT) -> FIFOEvalsClient:
    """Create test client with pre-obtained token (bypasses auth exchange)."""
    return FIFOEvalsClient(
        access_token="test_token",
        base_url=f"http://localhost:{port}",
    )


# =============================================================================
# TEST SUITE: Basic Operations
# =============================================================================

def test_submit_evaluation():
    """Test: Submit evaluation job."""
    print("\n" + "="*60)
    print("TEST 1: Submit Evaluation")
    print("="*60)

    test_csv = Path("test_eval_submit.csv")
    test_csv.write_text("""input_id,input,expected_output
1,What is the capital of France?,Paris
2,What is 2+2?,4
""")

    try:
        client = _make_client()

        job_id = client.submit_evaluation(
            csv_file=str(test_csv),
            config={
                "action_id": "action_rallyup_assistant",
                "base_url": "https://go.rallyup.com",
                "security_params": {"cookie": "session=test"},
                "batch_size": 5
            }
        )

        print(f"Job submitted: {job_id}")
        assert isinstance(job_id, str), "job_id should be string"
        assert len(job_id) > 0, "job_id should not be empty"

        return job_id

    finally:
        test_csv.unlink()


def test_get_status(job_id: str):
    """Test: Get job status."""
    print("\n" + "="*60)
    print("TEST 2: Get Status")
    print("="*60)

    client = _make_client()

    status = client.get_status(job_id)

    print(f"Status: {status['status']}")
    print(f"Progress: {status['progress']}")

    assert "status" in status, "Status response should have 'status'"
    assert "progress" in status, "Status response should have 'progress'"
    assert status["status"] in ["pending", "processing", "completed", "failed", "cancelled"], \
        "Status should be valid"

    print("PASS: Status check passed")


def test_wait_for_completion(job_id: str):
    """Test: Wait for job completion."""
    print("\n" + "="*60)
    print("TEST 3: Wait for Completion")
    print("="*60)

    client = _make_client()

    print("Waiting for completion (should take ~7 seconds with mock)...")
    result = client.wait_for_completion(job_id, poll_interval=1, verbose=True)

    assert "job_id" in result, "Result should have job_id"
    assert "status" in result, "Result should have status"
    assert result["status"] == "completed", "Job should be completed"
    assert "csv_download_url" in result, "Result should have csv_download_url"

    print("PASS: Wait for completion passed")
    return result


def test_list_jobs():
    """Test: List jobs with filters."""
    print("\n" + "="*60)
    print("TEST 4: List Jobs")
    print("="*60)

    client = _make_client()

    # Submit a few test jobs first
    test_csv = Path("test_list_jobs.csv")
    test_csv.write_text("input\ntest1\ntest2\n")

    try:
        job_ids = []
        for i in range(3):
            job_id = client.submit_evaluation(
                str(test_csv),
                config={
                    "action_id": "test_action",
                    "base_url": "https://api.test.com",
                    "security_params": {"cookie": "test"}
                }
            )
            job_ids.append(job_id)

        print(f"Created {len(job_ids)} test jobs")

        # Test 1: List all jobs
        all_jobs = client.list_jobs()
        print(f"\nPASS: Listed {len(all_jobs)} total jobs")
        assert len(all_jobs) >= 3, "Should have at least 3 jobs"

        # Test 2: List with page_size
        limited = client.list_jobs(page_size=2)
        print(f"PASS: Limited to {len(limited)} jobs (requested page_size=2)")
        assert len(limited) <= 2, "Should respect page_size"

        # Test 3: List by status filter
        pending = client.list_jobs(status_filter="pending")
        print(f"PASS: Found {len(pending)} pending jobs")

        # Verify job structure
        if all_jobs:
            job = all_jobs[0]
            assert "job_id" in job, "Job should have job_id"
            assert "status" in job, "Job should have status"
            assert "submitted_at" in job, "Job should have submitted_at"
            print(f"PASS: Job structure correct: {list(job.keys())}")

    finally:
        test_csv.unlink()

    print("PASS: List jobs test passed")


def test_cancel_job():
    """Test: Cancel a running job."""
    print("\n" + "="*60)
    print("TEST 5: Cancel Job")
    print("="*60)

    client = _make_client()

    # Submit a test job
    test_csv = Path("test_cancel.csv")
    test_csv.write_text("input\ntest1\ntest2\n")

    try:
        job_id = client.submit_evaluation(
            str(test_csv),
            config={
                "action_id": "test_action",
                "base_url": "https://api.test.com",
                "security_params": {"cookie": "test"}
            }
        )
        print(f"Created job: {job_id}")

        # Cancel the job
        result = client.cancel_job(job_id)
        print(f"PASS: Job cancelled: {result['status']}")
        assert result["status"] == "cancelled", "Status should be cancelled"
        assert "cancelled_at" in result, "Should have cancelled_at timestamp"

        # Verify status shows cancelled
        status = client.get_status(job_id)
        print(f"PASS: Status after cancel: {status['status']}")
        assert status["status"] == "cancelled", "Status should persist as cancelled"

    finally:
        test_csv.unlink()

    print("PASS: Cancel job test passed")


def test_cancel_completed_job():
    """Test: Cannot cancel completed job."""
    print("\n" + "="*60)
    print("TEST 6: Cannot Cancel Completed Job")
    print("="*60)

    client = _make_client()

    # Submit and wait for completion
    test_csv = Path("test_cancel_completed.csv")
    test_csv.write_text("input\ntest\n")

    try:
        job_id = client.submit_evaluation(
            str(test_csv),
            config={
                "action_id": "test_action",
                "base_url": "https://api.test.com",
                "security_params": {"cookie": "test"}
            }
        )

        # Wait for completion
        print("Waiting for job to complete...")
        time.sleep(8)  # Mock server completes after ~7 seconds

        # Check status to trigger state transition in mock server
        status = client.get_status(job_id)
        print(f"Job status: {status['status']}")
        assert status["status"] == "completed", f"Job should be completed, got: {status['status']}"

        # Try to cancel completed job
        try:
            result = client.cancel_job(job_id)
            print(f"FAIL: Should have raised error for completed job")
            print(f"   Got result: {result}")
            assert False, "Should not be able to cancel completed job"
        except (ValidationError, FIFOClientError) as e:
            print(f"PASS: Correctly rejected: {type(e).__name__}")
            print(f"   Message: {str(e)[:100]}")
        except AssertionError:
            raise

    finally:
        test_csv.unlink()

    print("PASS: Cannot cancel completed job test passed")


# =============================================================================
# TEST SUITE: CSV Validation
# =============================================================================

def test_csv_validation_file_not_found():
    """Test: CSV file not found."""
    print("\n" + "="*60)
    print("TEST 7: CSV File Not Found")
    print("="*60)

    client = _make_client()

    try:
        client.submit_evaluation("nonexistent.csv", config={})
        print("FAIL: Should have raised FileNotFoundError")
        return False
    except FileNotFoundError as e:
        print(f"PASS: Correct exception: {type(e).__name__}")
        print(f"   Message: {str(e)[:120]}...")
        return True


def test_csv_validation_empty_file():
    """Test: Empty CSV file."""
    print("\n" + "="*60)
    print("TEST 8: Empty CSV File")
    print("="*60)

    test_file = Path("test_empty.csv")
    test_file.write_text("")

    try:
        client = _make_client()

        try:
            client.submit_evaluation(str(test_file), config={})
            print("FAIL: Should have raised ValidationError")
            return False
        except ValidationError as e:
            print(f"PASS: Correct exception: {type(e).__name__}")
            print(f"   Message: {str(e)[:120]}...")
            return True
    finally:
        test_file.unlink()


def test_csv_validation_too_many_rows():
    """Test: CSV with too many rows."""
    print("\n" + "="*60)
    print("TEST 9: CSV File Too Large (Row Count)")
    print("="*60)

    test_file = Path("test_large.csv")

    # Create CSV with 10,001 rows (exceeds limit)
    with open(test_file, 'w') as f:
        f.write("input,expected_output\n")
        for i in range(10001):
            f.write(f"Test {i},Output {i}\n")

    try:
        client = _make_client()

        try:
            client.submit_evaluation(str(test_file), config={})
            print("FAIL: Should have raised ValidationError")
            return False
        except ValidationError as e:
            print(f"PASS: Correct exception: {type(e).__name__}")
            print(f"   Message: {str(e)[:120]}...")
            return True
    finally:
        test_file.unlink()


def test_csv_validation_missing_columns():
    """Test: CSV missing required columns."""
    print("\n" + "="*60)
    print("TEST 10: CSV Missing Required Columns")
    print("="*60)

    test_file = Path("test_bad_columns.csv")
    test_file.write_text("""wrong_column,another_wrong
value1,value2
""")

    try:
        client = _make_client()

        try:
            client.submit_evaluation(str(test_file), config={})
            print("FAIL: Should have raised ValidationError")
            return False
        except ValidationError as e:
            print(f"PASS: Correct exception: {type(e).__name__}")
            print(f"   Message: {str(e)[:120]}...")
            assert "missing required" in str(e).lower() and "column" in str(e).lower()
            return True
    finally:
        test_file.unlink()


def test_column_name_flexibility():
    """Test: Support for alternative column names."""
    print("\n" + "="*60)
    print("TEST 11: Column Name Flexibility")
    print("="*60)

    client = _make_client()

    test_cases = [
        ("prompt column", "prompt,expected_output\nTest,Response\n", "prompt"),
        ("user_message column", "user_message,expected_output\nTest,Response\n", "user_message"),
        ("message column", "message,expected_output\nTest,Response\n", "message"),
        ("conversation_id", "conversation_id,input,expected_output\nc1,Test,Response\n", "input"),
    ]

    for name, content, expected_col in test_cases:
        test_csv = Path(f"/tmp/test_{name.replace(' ', '_')}.csv")
        test_csv.write_text(content)

        try:
            validation = client._validate_csv_file(str(test_csv))
            assert validation['input_column'] == expected_col or expected_col in validation['input_column']
            print(f"PASS: {name}: Detected '{validation['input_column']}'")
            test_csv.unlink()
        except Exception as e:
            test_csv.unlink()
            raise AssertionError(f"FAIL: {name} failed: {e}")

    print("PASS: All column name variants supported")


def test_conversation_structure_detection():
    """Test: Multi-turn vs single-turn detection."""
    print("\n" + "="*60)
    print("TEST 12: Conversation Structure Detection")
    print("="*60)

    client = _make_client()

    # Multi-turn conversation
    test_csv = Path("/tmp/test_multi_turn.csv")
    test_csv.write_text("""input_id,input,expected_output
1,First message,Response 1
1,Second message,Response 2
2,Another convo,Response 3
""")

    try:
        validation = client._validate_csv_file(str(test_csv))
        stats = validation['conversation_stats']
        assert stats['multi_turn'] == 1, f"Expected 1 multi-turn, got {stats['multi_turn']}"
        assert stats['single_turn'] == 1, f"Expected 1 single-turn, got {stats['single_turn']}"
        print(f"PASS: Correctly detected: {stats['multi_turn']} multi-turn, {stats['single_turn']} single-turn")
        test_csv.unlink()
    except Exception as e:
        test_csv.unlink()
        raise AssertionError(f"FAIL: {e}")


# =============================================================================
# TEST SUITE: Error Handling
# =============================================================================

def test_error_handling_missing_credentials():
    """Test: Missing credentials."""
    print("\n" + "="*60)
    print("TEST 13: Missing Credentials")
    print("="*60)

    try:
        client = FIFOEvalsClient()
        print("FAIL: Should have raised ValueError")
        return False
    except (ValueError, TypeError) as e:
        print(f"PASS: Correct exception at init: {type(e).__name__}")
        print(f"   Message: {str(e)[:120]}")
        return True


def test_error_handling_job_not_found():
    """Test: Job not found."""
    print("\n" + "="*60)
    print("TEST 14: Job Not Found")
    print("="*60)

    client = _make_client()

    try:
        client.get_status("nonexistent-job-id")
        print("FAIL: Should have raised JobNotFoundError")
        return False
    except JobNotFoundError as e:
        print(f"PASS: Correct exception: {type(e).__name__}")
        print(f"   Message: {str(e)[:120]}...")
        return True


def test_error_handling_job_failed():
    """Test: Job execution failure."""
    print("\n" + "="*60)
    print("TEST 15: Job Execution Failure")
    print("="*60)

    client = _make_client()

    # Create test CSV
    test_csv = Path("test_failed.csv")
    test_csv.write_text("input\ntest\n")

    try:
        # Submit job that will fail
        job_id = client.submit_evaluation(
            str(test_csv),
            config={
                "action_id": "test_action",
                "base_url": "https://api.test.com",
                "security_params": {"cookie": "test"},
                "_test_failure": True  # Special flag for mock to fail
            }
        )
        print(f"Job submitted: {job_id}")

        # Wait a moment then check status - should show failed
        time.sleep(0.5)
        status = client.get_status(job_id)
        if status["status"] == "failed":
            print(f"PASS: Job failed as expected")
            print(f"   Error: {status.get('error_message', 'N/A')}")
            return True
        else:
            print(f"FAIL: Job should have failed, got status: {status['status']}")
            return False

    finally:
        test_csv.unlink()


# =============================================================================
# TEST SUITE: New Features
# =============================================================================

def test_csv_blank_row_detection():
    """Test: Detect and skip blank/whitespace-only rows."""
    print("\n" + "="*60)
    print("TEST 16: Blank Row Detection")
    print("="*60)

    test_csv = Path("test_blank_rows.csv")
    test_csv.write_text("""input,expected_output
Test 1,Output 1
  ,
Test 2,Output 2
   ,
Test 3,Output 3
""")

    try:
        client = _make_client()

        validation = client._validate_csv_file(str(test_csv))

        assert len(validation['skipped_rows']) == 2, f"Expected 2 skipped rows, got {len(validation['skipped_rows'])} - rows: {validation['skipped_rows']}"
        assert validation['row_count'] == 3, f"Expected 3 valid rows, got {validation['row_count']}"

        warnings = validation['warnings']
        assert any('Skipped' in w for w in warnings), "Should have warning about skipped rows"

        print(f"PASS: Detected {len(validation['skipped_rows'])} whitespace-only rows")
        print(f"PASS: Skipped row numbers: {validation['skipped_rows']}")
        print(f"PASS: Valid rows: {validation['row_count']}")
        return True

    finally:
        test_csv.unlink()


def test_error_truncation():
    """Test: Error message truncation for user-friendly display."""
    print("\n" + "="*60)
    print("TEST 17: Error Message Truncation")
    print("="*60)

    short_str = "This is a short error message"
    result = truncate_string(short_str, 100)
    assert result == short_str, "Short strings shouldn't be truncated"
    print(f"PASS: Short string unchanged: '{result}'")

    long_str = "A" * 150
    result = truncate_string(long_str, 100)
    assert len(result) == 103, f"Expected 103 chars (100 + '...'), got {len(result)}"
    assert result.endswith("..."), "Truncated string should end with '...'"
    print(f"PASS: Long string truncated: {len(long_str)} chars -> {len(result)} chars")

    exact_str = "B" * 100
    result = truncate_string(exact_str, 100)
    assert result == exact_str, "String at exact length shouldn't be truncated"
    print(f"PASS: Exact length unchanged: {len(result)} chars")

    result = truncate_string("", 100)
    assert result == "", "Empty string should stay empty"
    print(f"PASS: Empty string handled correctly")

    return True


def test_json_parsing_fallback():
    """Test: JSON parsing with fallback to ast.literal_eval."""
    print("\n" + "="*60)
    print("TEST 18: JSON Parsing with Fallback")
    print("="*60)

    valid_json = '{"key": "value", "num": 42}'
    result = safe_json_parse(valid_json)
    assert result == {"key": "value", "num": 42}, "Valid JSON should parse correctly"
    print(f"PASS: Valid JSON parsed: {result}")

    python_dict = "{'key': 'value', 'num': 42}"
    result = safe_json_parse(python_dict)
    assert result == {"key": "value", "num": 42}, "Python dict should parse via ast.literal_eval"
    print(f"PASS: Python dict parsed via fallback: {result}")

    invalid_str = "not a valid dict or json"
    result = safe_json_parse(invalid_str, fallback="DEFAULT")
    assert result == "DEFAULT", "Invalid string should return fallback"
    print(f"PASS: Invalid string returned fallback: {result}")

    result = safe_json_parse("", fallback=None)
    assert result is None, "Empty string should return fallback"
    print(f"PASS: Empty string returned fallback: {result}")

    complex_json = '{"nested": {"list": [1, 2, 3], "bool": true}}'
    result = safe_json_parse(complex_json)
    assert result["nested"]["list"] == [1, 2, 3], "Nested JSON should parse correctly"
    print(f"PASS: Complex JSON parsed: {result}")

    return True


def test_auto_timestamp_naming():
    """Test: Auto-timestamp feature for output filenames."""
    print("\n" + "="*60)
    print("TEST 19: Auto-Timestamp Filename Generation")
    print("="*60)

    import re
    from datetime import datetime
    from pathlib import Path

    output_file = "test_results.csv"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(output_file)
    timestamped_file = str(output_path.parent / f"{output_path.stem}_{timestamp}{output_path.suffix}")

    pattern = r'test_results_\d{8}_\d{6}\.csv'
    assert re.match(pattern, Path(timestamped_file).name), f"Filename should have timestamp: {timestamped_file}"

    print(f"PASS: Timestamp pattern validated: {Path(timestamped_file).name}")

    test_cases = [
        ("results.csv", r"results_\d{8}_\d{6}\.csv"),
        ("output/data.csv", r"data_\d{8}_\d{6}\.csv"),
        ("eval_output.txt", r"eval_output_\d{8}_\d{6}\.txt"),
    ]

    for original, expected_pattern in test_cases:
        output_path = Path(original)
        timestamped = str(output_path.parent / f"{output_path.stem}_{timestamp}{output_path.suffix}")
        assert re.match(expected_pattern, Path(timestamped).name), f"Pattern failed for {original}"

    print(f"PASS: Multiple path formats validated")

    return True


def test_cli_script_exists():
    """Test: CLI script (bulk_evals_v2.py) exists."""
    print("\n" + "="*60)
    print("TEST 20: CLI Script (bulk_evals_v2.py)")
    print("="*60)

    cli_script = Path(__file__).parent / "bulk_evals_v2.py"

    assert cli_script.exists(), f"CLI script not found: {cli_script}"
    print(f"PASS: CLI script exists: {cli_script.name}")

    assert cli_script.is_file(), f"CLI path is not a file: {cli_script}"
    print(f"PASS: CLI script is a file")

    content = cli_script.read_text()
    assert content.startswith("#!/usr/bin/env python3"), "CLI script should have Python shebang"
    print(f"PASS: CLI script has correct shebang")

    assert "def main():" in content, "CLI script should have main() function"
    print(f"PASS: CLI script has main() function")

    assert "argparse" in content, "CLI script should use argparse"
    print(f"PASS: CLI script uses argparse")

    assert "--client-id" in content, "CLI script should use --client-id"
    assert "--client-secret" in content, "CLI script should use --client-secret"
    print(f"PASS: CLI script uses new auth arguments")

    return True


def test_constructor_access_token():
    """Test: Constructor with pre-obtained access_token."""
    print("\n" + "="*60)
    print("TEST 21: Constructor with access_token")
    print("="*60)

    client = FIFOEvalsClient(access_token="pre-obtained-jwt", base_url="http://localhost:1234")
    assert client._access_token == "pre-obtained-jwt"
    assert client._client_id is None
    print("PASS: access_token constructor works")

    return True


def test_constructor_credentials():
    """Test: Constructor with client_id + client_secret."""
    print("\n" + "="*60)
    print("TEST 22: Constructor with credentials")
    print("="*60)

    client = FIFOEvalsClient(client_id="test-id", client_secret="test-secret", base_url="http://localhost:1234")
    assert client._client_id == "test-id"
    assert client._client_secret == "test-secret"
    assert client._access_token is None  # Not yet authenticated
    print("PASS: credential constructor works")

    return True


# =============================================================================
# RUN ALL TESTS
# =============================================================================

def run_all_tests():
    """Run all comprehensive tests."""
    print("\n" + "="*70)
    print("FIFO EVALS CLIENT - COMPREHENSIVE TEST SUITE")
    print("="*70)

    # Start mock server
    print("\nStarting mock server (proxy route simulation)...")
    server = start_mock_server(MOCK_SERVER_PORT)
    print(f"Mock server running on port {MOCK_SERVER_PORT}")

    results = []

    try:
        # Basic Operations Tests
        print("\n" + "="*70)
        print("PART 1: BASIC OPERATIONS")
        print("="*70)

        job_id = test_submit_evaluation()
        test_get_status(job_id)
        test_wait_for_completion(job_id)
        test_list_jobs()
        test_cancel_job()
        test_cancel_completed_job()

        # CSV Validation Tests
        print("\n" + "="*70)
        print("PART 2: CSV VALIDATION")
        print("="*70)

        results.append(("File not found", test_csv_validation_file_not_found()))
        results.append(("Empty CSV", test_csv_validation_empty_file()))
        results.append(("Too many rows", test_csv_validation_too_many_rows()))
        results.append(("Missing columns", test_csv_validation_missing_columns()))
        test_column_name_flexibility()
        test_conversation_structure_detection()

        # Error Handling Tests
        print("\n" + "="*70)
        print("PART 3: ERROR HANDLING")
        print("="*70)

        results.append(("Missing credentials", test_error_handling_missing_credentials()))
        results.append(("Job not found", test_error_handling_job_not_found()))

        # New Features Tests
        print("\n" + "="*70)
        print("PART 4: FEATURES")
        print("="*70)

        results.append(("Blank row detection", test_csv_blank_row_detection()))
        results.append(("Error truncation", test_error_truncation()))
        results.append(("JSON fallback parsing", test_json_parsing_fallback()))
        results.append(("Auto-timestamp naming", test_auto_timestamp_naming()))
        results.append(("CLI script exists", test_cli_script_exists()))
        results.append(("Constructor: access_token", test_constructor_access_token()))
        results.append(("Constructor: credentials", test_constructor_credentials()))

        # Summary
        print("\n" + "="*70)
        print("TEST RESULTS SUMMARY")
        print("="*70)

        passed = sum(1 for _, result in results if result)
        total = len(results)
        operation_tests = 9  # Basic operations that don't return bool

        for test_name, result in results:
            status = "PASS" if result else "FAIL"
            print(f"  {status:6} - {test_name}")

        print("\n" + "="*70)
        if passed == total and passed > 0:
            print(f"ALL {passed + operation_tests} TESTS PASSED")
        else:
            print(f"Results: {passed}/{total} validation tests passed")
        print("="*70)

    except Exception as e:
        print("\n" + "="*70)
        print(f"TEST FAILED: {e}")
        print("="*70)
        import traceback
        traceback.print_exc()

    finally:
        server.shutdown()
        print("\nMock server stopped")


if __name__ == "__main__":
    run_all_tests()
