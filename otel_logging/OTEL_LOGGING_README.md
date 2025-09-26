# OpenTelemetry Logging Module

This module provides OpenTelemetry logging capabilities for the ProjectA3 application, integrating with your existing logging infrastructure.

## Features

- **Structured Logging**: Send structured logs to OpenTelemetry endpoints
- **Conversation Context**: Integrates with ProjectA3's conversation context system
- **Error Handling**: Comprehensive error logging with stack traces
- **Environment Configuration**: Configure via environment variables
- **Retry Logic**: Built-in retry mechanism for network failures
- **Type Safety**: Full type hints for better development experience

## Installation

The required dependencies are already added to `pyproject.toml`:

```bash
poetry install
```

## Quick Start

### 1. Environment Variables (Recommended)

Set these environment variables:

```bash
export OTEL_ENDPOINT="https://your-otel-endpoint.com/v1/logs"
export OTEL_BEARER_TOKEN="your-bearer-token"
export OTEL_LOGGER_NAME="your-logger-name"
export OTEL_SERVICE_NAME="projecta3"  # optional
export OTEL_LOG_LEVEL="INFO"  # optional
```

Then use in your code:

```python
from utils.otel_logging import configure_from_environment, get_otel_logger

# Configure from environment
configure_from_environment()

# Get logger
logger = get_otel_logger()
logger.info("Hello OpenTelemetry!")
```

### 2. Programmatic Configuration

```python
from utils.otel_logging import configure_otel_logging, get_otel_logger

# Configure OpenTelemetry logging
configure_otel_logging(
    endpoint="https://your-otel-endpoint.com/v1/logs",
    bearer_token="your-bearer-token",
    logger_name="your-logger-name",
    service_name="projecta3"
)

# Get logger
logger = get_otel_logger()
logger.info("Application started", version="1.0.0")
```

## Usage Examples

### Basic Logging

```python
from utils.otel_logging import get_otel_logger

logger = get_otel_logger()

# Different log levels
logger.debug("Debug information", component="auth")
logger.info("Application started", version="1.0.0")
logger.warning("This is a warning", component="database")
logger.error("An error occurred", status_code=500)
logger.critical("System failure", component="system")
```

### With Conversation Context

```python
from utils.otel_logging import get_otel_logger
from utils.context_manager import conversation_scope

logger = get_otel_logger()

# Log with conversation context
with conversation_scope("user-session-123"):
    logger.info("User action", user_id="user123", action="login")
```

### Structured Logging

```python
logger.info(
    "API request processed",
    method="POST",
    endpoint="/api/v1/users",
    status_code=201,
    response_time=0.245,
    user_id="user123"
)
```

### Error Logging

```python
try:
    # Some operation that might fail
    result = risky_operation()
except ValueError as e:
    logger.exception(
        "Operation failed",
        component="api",
        error_type="ValueError",
        user_id="user123"
    )
```

## API Reference

### Functions

#### `configure_otel_logging(endpoint, bearer_token, logger_name, service_name="projecta3", log_level=logging.INFO)`

Configure OpenTelemetry logging programmatically.

**Parameters:**
- `endpoint` (str): OpenTelemetry endpoint URL
- `bearer_token` (str): Bearer token for authentication
- `logger_name` (str): Name of the logger
- `service_name` (str): Name of the service (default: "projecta3")
- `log_level` (int): Logging level (default: logging.INFO)

#### `get_otel_logger() -> OpenTelemetryLogger`

Get the configured OpenTelemetry logger instance.

**Returns:** `OpenTelemetryLogger` instance

**Raises:** `RuntimeError` if logger is not configured

#### `configure_from_environment() -> bool`

Configure OpenTelemetry logging from environment variables.

**Returns:** `True` if configuration was successful, `False` otherwise

#### `is_otel_configured() -> bool`

Check if OpenTelemetry logging is configured.

**Returns:** `True` if configured, `False` otherwise

#### `disable_otel_logging()`

Disable OpenTelemetry logging by removing the handler.

### OpenTelemetryLogger Class

The logger provides these methods:

- `debug(message, **kwargs)`: Log debug message
- `info(message, **kwargs)`: Log info message  
- `warning(message, **kwargs)`: Log warning message
- `error(message, **kwargs)`: Log error message
- `critical(message, **kwargs)`: Log critical message
- `exception(message, **kwargs)`: Log exception with traceback

All methods accept additional keyword arguments that will be included as structured attributes in the OpenTelemetry log.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OTEL_ENDPOINT` | Yes | - | OpenTelemetry endpoint URL |
| `OTEL_BEARER_TOKEN` | Yes | - | Bearer token for authentication |
| `OTEL_LOGGER_NAME` | Yes | - | Name of the logger |
| `OTEL_SERVICE_NAME` | No | "projecta3" | Name of the service |
| `OTEL_LOG_LEVEL` | No | "INFO" | Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL) |

## Integration with Existing Logging

This module integrates seamlessly with your existing ProjectA3 logging infrastructure:

- Uses the same conversation context system
- Compatible with existing log patterns
- Can be used alongside `utils.adopt_logging`
- Maintains the same structured logging approach

## Error Handling

The module includes robust error handling:

- **Network Failures**: Automatic retry with exponential backoff
- **Authentication Errors**: Graceful handling of auth failures
- **Configuration Errors**: Clear error messages for misconfiguration
- **Logging Failures**: Prevents infinite recursion on logging errors

## Testing

Run the example file to test your configuration:

```bash
python utils/otel_logging_example.py
```

This will run through various logging scenarios and help verify your OpenTelemetry setup.

## Troubleshooting

### Common Issues

1. **"OpenTelemetry logger not configured"**
   - Make sure to call `configure_otel_logging()` or `configure_from_environment()` first

2. **"Failed to send log to OpenTelemetry"**
   - Check your endpoint URL and bearer token
   - Verify network connectivity
   - Check OpenTelemetry endpoint logs

3. **Environment variables not working**
   - Ensure all required variables are set
   - Check variable names (case-sensitive)
   - Verify the `configure_from_environment()` call

### Debug Mode

Enable debug logging to see detailed information:

```python
import logging
logging.getLogger("projecta3.otel").setLevel(logging.DEBUG)
```

## Examples

See `utils/otel_logging_example.py` for comprehensive examples including:

- Basic usage
- Conversation context integration
- Structured logging
- Error handling
- Performance monitoring
- Environment configuration

## Support

For issues or questions about this module, please check:

1. The example file: `utils/otel_logging_example.py`
2. Your OpenTelemetry endpoint configuration
3. Network connectivity and authentication
4. Environment variable setup
