"""
OpenTelemetry Logging Example

This file demonstrates how to use the OpenTelemetry logging module
in your ProjectA3 application.

Prerequisites:
1. Install dependencies: poetry install
2. Set environment variables or configure programmatically
3. Have access to an OpenTelemetry endpoint

Environment Variables:
    OTEL_ENDPOINT: Your OpenTelemetry endpoint URL
    OTEL_BEARER_TOKEN: Your bearer token for authentication
    OTEL_LOGGER_NAME: Name for your logger
    OTEL_SERVICE_NAME: Name of your service (optional, defaults to projecta3)
    OTEL_LOG_LEVEL: Logging level (optional, defaults to INFO)
"""

import os
import time
from utils.otel_logging import (
    configure_otel_logging,
    get_otel_logger,
    configure_from_environment,
    is_otel_configured,
    disable_otel_logging
)
from utils.context_manager import conversation_scope


def example_basic_usage():
    """
    Basic usage example - configure and use OpenTelemetry logging.
    """
    print("=== Basic Usage Example ===")
    
    # Configure OpenTelemetry logging
    configure_otel_logging(
        endpoint="https://your-otel-endpoint.com/v1/logs",
        bearer_token="your-bearer-token",
        logger_name="projecta3",
        service_name="projecta3"
    )
    
    # Get logger instance
    logger = get_otel_logger()
    
    # Log different levels
    logger.info("Application started", version="1.0.0", environment="production")
    logger.debug("Debug information", component="auth", user_id="user123")
    logger.warning("This is a warning", component="database", query_time=1.5)
    logger.error("An error occurred", component="api", status_code=500)
    
    print("Basic usage example completed.")


def example_with_conversation_context():
    """
    Example using conversation context (integrates with existing ProjectA3 context).
    """
    print("=== Conversation Context Example ===")
    
    if not is_otel_configured():
        print("OpenTelemetry not configured. Skipping example.")
        return
    
    logger = get_otel_logger()
    
    # Log without conversation context
    logger.info("System startup", component="system")
    
    # Log with conversation context
    with conversation_scope("user-session-123"):
        logger.info("User logged in", user_id="user123", action="login")
        logger.info("User performed action", action="search", query="python tutorial")
        
        # Nested conversation scope
        with conversation_scope("sub-conversation-456"):
            logger.info("Sub-action performed", sub_action="filter_results")
    
    # Back to no conversation context
    logger.info("System shutdown", component="system")
    
    print("Conversation context example completed.")


def example_structured_logging():
    """
    Example of structured logging with rich metadata.
    """
    print("=== Structured Logging Example ===")
    
    if not is_otel_configured():
        print("OpenTelemetry not configured. Skipping example.")
        return
    
    logger = get_otel_logger()
    
    # Log with structured data
    logger.info(
        "API request processed",
        method="POST",
        endpoint="/api/v1/users",
        status_code=201,
        response_time=0.245,
        user_id="user123",
        request_id="req-456",
        ip_address="192.168.1.100"
    )
    
    # Log database operation
    logger.info(
        "Database query executed",
        operation="SELECT",
        table="users",
        query_time=0.012,
        rows_returned=1,
        connection_id="conn-789"
    )
    
    # Log business event
    logger.info(
        "Business event occurred",
        event_type="user_registration",
        user_id="user123",
        email="user@example.com",
        registration_source="web",
        timestamp=time.time()
    )
    
    print("Structured logging example completed.")


def example_error_handling():
    """
    Example of error logging with exceptions.
    """
    print("=== Error Handling Example ===")
    
    if not is_otel_configured():
        print("OpenTelemetry not configured. Skipping example.")
        return
    
    logger = get_otel_logger()
    
    # Log error without exception
    logger.error("Failed to connect to database", component="database", retry_count=3)
    
    # Log error with exception
    try:
        # Simulate an error
        raise ValueError("Invalid input parameter")
    except ValueError as e:
        logger.exception(
            "Error processing request",
            component="api",
            error_type="ValueError",
            user_id="user123",
            request_id="req-789"
        )
    
    # Log critical error
    logger.critical(
        "System failure detected",
        component="system",
        failure_type="memory_exhaustion",
        memory_usage="95%"
    )
    
    print("Error handling example completed.")


def example_environment_configuration():
    """
    Example of configuring from environment variables.
    """
    print("=== Environment Configuration Example ===")
    
    # Set environment variables (in real usage, these would be set externally)
    os.environ["OTEL_ENDPOINT"] = "https://your-otel-endpoint.com/v1/logs"
    os.environ["OTEL_BEARER_TOKEN"] = "your-bearer-token"
    os.environ["OTEL_LOGGER_NAME"] = "projecta3"
    os.environ["OTEL_SERVICE_NAME"] = "projecta3"
    os.environ["OTEL_LOG_LEVEL"] = "INFO"
    
    # Configure from environment
    if configure_from_environment():
        print("OpenTelemetry configured from environment variables.")
        
        logger = get_otel_logger()
        logger.info("Configuration loaded from environment", source="env_vars")
    else:
        print("Failed to configure from environment variables.")
    
    print("Environment configuration example completed.")


def example_integration_with_existing_logging():
    """
    Example of integrating with existing ProjectA3 logging patterns.
    """
    print("=== Integration Example ===")
    
    if not is_otel_configured():
        print("OpenTelemetry not configured. Skipping example.")
        return
    
    logger = get_otel_logger()
    
    # Simulate typical ProjectA3 workflow
    with conversation_scope("workflow-123"):
        # Action execution
        logger.info("Action started", action="process_document", document_id="doc-456")
        
        # API calls
        logger.info("API call initiated", api="external_service", endpoint="/process")
        
        # Processing steps
        logger.info("Processing step completed", step="validation", duration=0.1)
        logger.info("Processing step completed", step="transformation", duration=0.3)
        
        # Results
        logger.info("Action completed", action="process_document", result="success", total_duration=0.4)
    
    print("Integration example completed.")


def example_performance_monitoring():
    """
    Example of using OpenTelemetry logging for performance monitoring.
    """
    print("=== Performance Monitoring Example ===")
    
    if not is_otel_configured():
        print("OpenTelemetry not configured. Skipping example.")
        return
    
    logger = get_otel_logger()
    
    # Simulate performance monitoring
    start_time = time.time()
    
    # Simulate some work
    time.sleep(0.1)
    
    end_time = time.time()
    duration = end_time - start_time
    
    logger.info(
        "Performance metric recorded",
        metric_type="operation_duration",
        operation="data_processing",
        duration=duration,
        status="success"
    )
    
    # Log resource usage
    logger.info(
        "Resource usage recorded",
        metric_type="resource_usage",
        cpu_percent=45.2,
        memory_mb=128.5,
        disk_usage_percent=67.8
    )
    
    print("Performance monitoring example completed.")


def run_all_examples():
    """
    Run all examples to demonstrate OpenTelemetry logging capabilities.
    """
    print("OpenTelemetry Logging Examples")
    print("=" * 50)
    
    # Check if configured from environment first
    if not is_otel_configured():
        print("OpenTelemetry not configured. Please configure first.")
        print("You can either:")
        print("1. Set environment variables (OTEL_ENDPOINT, OTEL_BEARER_TOKEN, OTEL_LOGGER_NAME)")
        print("2. Call configure_otel_logging() programmatically")
        return
    
    # Run examples
    example_basic_usage()
    print()
    
    example_with_conversation_context()
    print()
    
    example_structured_logging()
    print()
    
    example_error_handling()
    print()
    
    example_integration_with_existing_logging()
    print()
    
    example_performance_monitoring()
    print()
    
    print("All examples completed!")


def cleanup_example():
    """
    Example of cleaning up OpenTelemetry logging.
    """
    print("=== Cleanup Example ===")
    
    if is_otel_configured():
        print("Disabling OpenTelemetry logging...")
        disable_otel_logging()
        print("OpenTelemetry logging disabled.")
    else:
        print("OpenTelemetry logging was not configured.")


if __name__ == "__main__":
    # Try to configure from environment first
    configure_from_environment()
    
    # Run examples
    run_all_examples()
    
    # Cleanup
    cleanup_example()
