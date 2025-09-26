"""
OpenTelemetry Logging Module

This module provides OpenTelemetry logging capabilities for the ProjectA3 application.
It integrates with the existing logging infrastructure and provides structured logging
to OpenTelemetry endpoints.

Usage:
    from utils.otel_logging import get_otel_logger, configure_otel_logging
    
    # Configure OpenTelemetry logging
    configure_otel_logging(
        endpoint="https://your-otel-endpoint.com/v1/logs",
        bearer_token="your-bearer-token",
        logger_name="your-logger-name"
    )
    
    # Get logger instance
    logger = get_otel_logger()
    logger.info("Your log message", extra={"key": "value"})
"""

import os
import logging
import json
from typing import Any, Dict, Optional, Union
from datetime import datetime
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Import existing conversation context utilities
from utils.context_manager import get_conversation_id, conversation_scope


class OpenTelemetryLogHandler(logging.Handler):
    """
    Custom logging handler that sends logs to OpenTelemetry endpoint.
    """
    
    def __init__(
        self,
        endpoint: str,
        bearer_token: str,
        logger_name: str,
        service_name: str = "projecta3",
        timeout: int = 30,
        max_retries: int = 3
    ):
        super().__init__()
        self.endpoint = endpoint
        self.bearer_token = bearer_token
        self.logger_name = logger_name
        self.service_name = service_name
        self.timeout = timeout
        
        # Configure session with retry strategy
        self.session = requests.Session()
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # Set headers
        self.session.headers.update({
            'Authorization': f'Bearer {bearer_token}',
            'Content-Type': 'application/json'
        })
    
    def emit(self, record: logging.LogRecord) -> None:
        """
        Emit a log record to the OpenTelemetry endpoint.
        """
        try:
            # Convert log record to OpenTelemetry format
            otel_log = self._format_log_record(record)
            
            # Send to endpoint
            response = self.session.post(
                self.endpoint,
                json=otel_log,
                timeout=self.timeout
            )
            response.raise_for_status()
            
        except Exception as e:
            # Log the error to avoid infinite recursion
            print(f"Failed to send log to OpenTelemetry: {e}")
    
    def _format_log_record(self, record: logging.LogRecord) -> Dict[str, Any]:
        """
        Format a Python log record into OpenTelemetry log format.
        """
        # Get conversation ID from context
        conversation_id = get_conversation_id()
        
        # Extract message and any extra data
        message = record.getMessage()
        extra_data = {}
        
        # Process any extra attributes from the log record
        for key, value in record.__dict__.items():
            if key not in [
                'name', 'msg', 'args', 'levelname', 'levelno', 'pathname',
                'filename', 'module', 'lineno', 'funcName', 'created',
                'msecs', 'relativeCreated', 'thread', 'threadName',
                'processName', 'process', 'getMessage', 'exc_info',
                'exc_text', 'stack_info'
            ]:
                extra_data[key] = value
        
        # Build OpenTelemetry log structure
        otel_log = {
            "resourceLogs": [{
                "resource": {
                    "attributes": [
                        {
                            "key": "service.name",
                            "value": {"stringValue": self.service_name}
                        },
                        {
                            "key": "service.version",
                            "value": {"stringValue": "1.0.0"}
                        }
                    ]
                },
                "scopeLogs": [{
                    "scope": {
                        "name": self.logger_name,
                        "version": "1.0.0"
                    },
                    "logRecords": [{
                        "timeUnixNano": str(int(record.created * 1_000_000_000)),
                        "severityNumber": self._get_severity_number(record.levelno),
                        "severityText": record.levelname,
                        "body": {
                            "stringValue": message
                        },
                        "attributes": self._build_attributes(record, conversation_id, extra_data)
                    }]
                }]
            }]
        }
        
        return otel_log
    
    def _get_severity_number(self, level: int) -> int:
        """
        Convert Python logging level to OpenTelemetry severity number.
        """
        severity_map = {
            logging.DEBUG: 5,
            logging.INFO: 9,
            logging.WARNING: 13,
            logging.ERROR: 17,
            logging.CRITICAL: 21
        }
        return severity_map.get(level, 9)  # Default to INFO
    
    def _build_attributes(
        self,
        record: logging.LogRecord,
        conversation_id: Optional[str],
        extra_data: Dict[str, Any]
    ) -> list:
        """
        Build OpenTelemetry attributes from log record.
        """
        attributes = [
            {
                "key": "logger.name",
                "value": {"stringValue": record.name}
            },
            {
                "key": "code.filepath",
                "value": {"stringValue": record.pathname}
            },
            {
                "key": "code.lineno",
                "value": {"intValue": str(record.lineno)}
            },
            {
                "key": "code.function",
                "value": {"stringValue": record.funcName}
            },
            {
                "key": "thread.name",
                "value": {"stringValue": record.threadName}
            }
        ]
        
        # Add conversation ID if available
        if conversation_id:
            attributes.append({
                "key": "conversation.id",
                "value": {"stringValue": conversation_id}
            })
        
        # Add any extra data as attributes
        for key, value in extra_data.items():
            if isinstance(value, (str, int, float, bool)):
                value_type = "stringValue" if isinstance(value, str) else "intValue" if isinstance(value, int) else "doubleValue" if isinstance(value, float) else "boolValue"
                attributes.append({
                    "key": f"extra.{key}",
                    "value": {value_type: str(value)}
                })
        
        # Add exception information if present
        if record.exc_info:
            import traceback
            attributes.append({
                "key": "exception.type",
                "value": {"stringValue": record.exc_info[0].__name__ if record.exc_info[0] else "Unknown"}
            })
            attributes.append({
                "key": "exception.message",
                "value": {"stringValue": str(record.exc_info[1]) if record.exc_info[1] else ""}
            })
            attributes.append({
                "key": "exception.stacktrace",
                "value": {"stringValue": traceback.format_exception(*record.exc_info)}
            })
        
        return attributes


class OpenTelemetryLogger:
    """
    Wrapper around Python logger that provides OpenTelemetry integration.
    """
    
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self._otel_handler = None
    
    def add_otel_handler(
        self,
        endpoint: str,
        bearer_token: str,
        logger_name: str,
        service_name: str = "projecta3"
    ) -> None:
        """
        Add OpenTelemetry handler to the logger.
        """
        self._otel_handler = OpenTelemetryLogHandler(
            endpoint=endpoint,
            bearer_token=bearer_token,
            logger_name=logger_name,
            service_name=service_name
        )
        
        # Remove existing OpenTelemetry handlers
        for handler in self.logger.handlers[:]:
            if isinstance(handler, OpenTelemetryLogHandler):
                self.logger.removeHandler(handler)
        
        self.logger.addHandler(self._otel_handler)
    
    def remove_otel_handler(self) -> None:
        """
        Remove OpenTelemetry handler from the logger.
        """
        if self._otel_handler:
            self.logger.removeHandler(self._otel_handler)
            self._otel_handler = None
    
    def debug(self, message: str, **kwargs) -> None:
        """Log debug message."""
        self.logger.debug(message, extra=kwargs)
    
    def info(self, message: str, **kwargs) -> None:
        """Log info message."""
        self.logger.info(message, extra=kwargs)
    
    def warning(self, message: str, **kwargs) -> None:
        """Log warning message."""
        self.logger.warning(message, extra=kwargs)
    
    def error(self, message: str, **kwargs) -> None:
        """Log error message."""
        self.logger.error(message, extra=kwargs)
    
    def critical(self, message: str, **kwargs) -> None:
        """Log critical message."""
        self.logger.critical(message, extra=kwargs)
    
    def exception(self, message: str, **kwargs) -> None:
        """Log exception with traceback."""
        self.logger.exception(message, extra=kwargs)


# Global logger instance
_otel_logger: Optional[OpenTelemetryLogger] = None


def configure_otel_logging(
    endpoint: str,
    bearer_token: str,
    logger_name: str,
    service_name: str = "projecta3",
    log_level: int = logging.INFO
) -> None:
    """
    Configure OpenTelemetry logging.
    
    Args:
        endpoint: OpenTelemetry endpoint URL
        bearer_token: Bearer token for authentication
        logger_name: Name of the logger
        service_name: Name of the service (default: projecta3)
        log_level: Logging level (default: INFO)
    """
    global _otel_logger
    
    _otel_logger = OpenTelemetryLogger("projecta3.otel")
    _otel_logger.add_otel_handler(
        endpoint=endpoint,
        bearer_token=bearer_token,
        logger_name=logger_name,
        service_name=service_name
    )
    
    # Set log level
    _otel_logger.logger.setLevel(log_level)


def get_otel_logger() -> OpenTelemetryLogger:
    """
    Get the configured OpenTelemetry logger.
    
    Returns:
        OpenTelemetryLogger instance
        
    Raises:
        RuntimeError: If logger is not configured
    """
    if _otel_logger is None:
        raise RuntimeError(
            "OpenTelemetry logger not configured. Call configure_otel_logging() first."
        )
    return _otel_logger


def disable_otel_logging() -> None:
    """
    Disable OpenTelemetry logging by removing the handler.
    """
    global _otel_logger
    if _otel_logger:
        _otel_logger.remove_otel_handler()


def is_otel_configured() -> bool:
    """
    Check if OpenTelemetry logging is configured.
    
    Returns:
        True if configured, False otherwise
    """
    return _otel_logger is not None and _otel_logger._otel_handler is not None


# Environment-based configuration
def configure_from_environment() -> bool:
    """
    Configure OpenTelemetry logging from environment variables.
    
    Environment variables:
        OTEL_ENDPOINT: OpenTelemetry endpoint URL
        OTEL_BEARER_TOKEN: Bearer token for authentication
        OTEL_LOGGER_NAME: Name of the logger
        OTEL_SERVICE_NAME: Name of the service (default: projecta3)
        OTEL_LOG_LEVEL: Logging level (default: INFO)
    
    Returns:
        True if configuration was successful, False otherwise
    """
    endpoint = os.getenv("OTEL_ENDPOINT")
    bearer_token = os.getenv("OTEL_BEARER_TOKEN")
    logger_name = os.getenv("OTEL_LOGGER_NAME")
    
    if not all([endpoint, bearer_token, logger_name]):
        return False
    
    service_name = os.getenv("OTEL_SERVICE_NAME", "projecta3")
    log_level_str = os.getenv("OTEL_LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    
    configure_otel_logging(
        endpoint=endpoint,  # type: ignore
        bearer_token=bearer_token,  # type: ignore
        logger_name=logger_name,  # type: ignore
        service_name=service_name,
        log_level=log_level
    )
    
    return True


# Example usage and testing functions
def example_usage() -> None:
    """
    Example of how to use the OpenTelemetry logging module.
    """
    # Configure logging
    configure_otel_logging(
        endpoint="https://your-otel-endpoint.com/v1/logs",
        bearer_token="your-bearer-token",
        logger_name="projecta3",
        service_name="projecta3"
    )
    
    # Get logger
    logger = get_otel_logger()
    
    # Log messages
    logger.info("Application started", version="1.0.0", environment="production")
    logger.warning("This is a warning message", component="auth")
    
    # Log with conversation context
    with conversation_scope("test-conversation-123"):
        logger.info("User action performed", action="login", user_id="user123")
    
    # Log error with exception
    try:
        raise ValueError("Something went wrong")
    except ValueError as e:
        logger.exception("An error occurred", error_type="ValueError")


def test_otel_logging() -> None:
    """
    Test function to verify OpenTelemetry logging is working.
    """
    if not is_otel_configured():
        print("OpenTelemetry logging not configured. Skipping test.")
        return
    
    logger = get_otel_logger()
    
    # Test different log levels
    logger.debug("Debug message", test="debug")
    logger.info("Info message", test="info")
    logger.warning("Warning message", test="warning")
    logger.error("Error message", test="error")
    
    # Test with conversation context
    with conversation_scope("test-conversation"):
        logger.info("Message with conversation context", test="conversation")
    
    print("OpenTelemetry logging test completed. Check your OpenTelemetry endpoint for logs.")


if __name__ == "__main__":
    # Try to configure from environment variables
    if configure_from_environment():
        print("OpenTelemetry logging configured from environment variables.")
        test_otel_logging()
    else:
        print("OpenTelemetry logging not configured. Set environment variables:")
        print("  OTEL_ENDPOINT")
        print("  OTEL_BEARER_TOKEN") 
        print("  OTEL_LOGGER_NAME")
        example_usage()
