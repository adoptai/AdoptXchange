# middleware_registry/custom_middleware.py
"""Custom middleware implementations for Adopt agents.

These middleware classes extend the built-in LangChain middleware with
custom functionality specific to Adopt use cases.

All custom middleware can be used via MiddlewareSpec:
    MiddlewareSpec("cache", {})
    MiddlewareSpec("tool_access_control", {"allowed_tools": ["tool1", "tool2"]})
    MiddlewareSpec("tool_log", {"verbose": True})
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Tuple
from datetime import datetime
import json
import hashlib
import logging

from langchain.agents.middleware import wrap_tool_call, before_model, after_model

logger = logging.getLogger(__name__)


# ============================================================================
# Context Classes
# ============================================================================

@dataclass
class UserContext:
    """Context schema for tracking user information across middleware.
    
    This can be passed to middleware that needs user-specific behavior.
    """
    user_id: str = "unknown"
    expertise_level: str = "beginner"  # beginner, intermediate, expert
    session_start: str = field(default_factory=lambda: datetime.now().isoformat())
    token_count: int = 0
    request_count: int = 0
    
    def increment_request(self):
        self.request_count += 1
    
    def add_tokens(self, count: int):
        self.token_count += count


# ============================================================================
# Custom Middleware Classes
# ============================================================================

class ToolLoggingMiddleware:
    """Logs all tool calls for debugging and monitoring.
    
    Params:
        verbose: Whether to print detailed logs (default: True)
        log_args: Whether to log tool arguments (default: True)
    """
    
    def __init__(self, verbose: bool = True, log_args: bool = True):
        self.verbose = verbose
        self.log_args = log_args
        self.call_count = 0
        self.tool_stats: Dict[str, int] = {}
    
    def __call__(self, request, handler):
        """Wrap tool call with logging."""
        self.call_count += 1
        tool_name = request.tool_call.get("name", "unknown")
        tool_args = request.tool_call.get("args", {})
        
        # Track stats
        self.tool_stats[tool_name] = self.tool_stats.get(tool_name, 0) + 1
        
        if self.verbose:
            print(f"\n{'='*60}")
            print(f"[TOOL LOG] Call #{self.call_count}")
            print(f"[TIMESTAMP] {datetime.now().isoformat()}")
            print(f"[TOOL] {tool_name}")
            if self.log_args:
                print(f"[ARGS] {json.dumps(tool_args, indent=2)}")
            print(f"{'='*60}")
        
        logger.info("[TOOL LOG] Calling %s (call #%d)", tool_name, self.call_count)
        
        try:
            result = handler(request)
            if self.verbose:
                print(f"[TOOL LOG] {tool_name} completed successfully")
            logger.info("[TOOL LOG] %s completed", tool_name)
            return result
        except Exception as e:
            if self.verbose:
                print(f"[TOOL LOG] {tool_name} FAILED: {e}")
            logger.exception("[TOOL LOG] %s failed", tool_name)
            raise
    
    def get_stats(self) -> Dict[str, Any]:
        """Get tool call statistics."""
        return {
            "total_calls": self.call_count,
            "by_tool": self.tool_stats.copy(),
        }


class ToolAccessControlMiddleware:
    """Controls which tools the agent can access based on permissions.
    
    Implements role-based access control (RBAC) for agent tools.
    
    Params:
        allowed_tools: List of tool names that are allowed
        user_context: Optional UserContext for tracking
        block_message: Message to return when tool is blocked
    """
    
    def __init__(
        self,
        allowed_tools: List[str],
        user_context: UserContext | None = None,
        block_message: str | None = None,
    ):
        self.allowed_tools = set(allowed_tools)
        self.context = user_context or UserContext()
        self.block_message = block_message
        self.blocked_attempts = 0
        self.allowed_attempts = 0
    
    def __call__(self, request, handler):
        """Check if tool access is allowed before execution."""
        tool_name = request.tool_call.get("name", "unknown")
        
        if tool_name in self.allowed_tools:
            self.allowed_attempts += 1
            logger.info("[ACCESS CONTROL] Tool '%s' - ALLOWED for user %s", tool_name, self.context.user_id)
            return handler(request)
        else:
            self.blocked_attempts += 1
            logger.warning(
                "[ACCESS CONTROL] Tool '%s' - BLOCKED for user %s. Allowed: %s",
                tool_name,
                self.context.user_id,
                list(self.allowed_tools),
            )
            
            message = self.block_message or (
                f"Access denied: Tool '{tool_name}' is not permitted for user '{self.context.user_id}'. "
                f"Allowed tools: {', '.join(sorted(self.allowed_tools))}"
            )
            
            # Return error message instead of raising
            return message
    
    def get_stats(self) -> Dict[str, Any]:
        """Get access control statistics."""
        return {
            "allowed_attempts": self.allowed_attempts,
            "blocked_attempts": self.blocked_attempts,
            "allowed_tools": list(self.allowed_tools),
        }


class CachingMiddleware:
    """Caches model responses to avoid redundant API calls.
    
    Uses message content hash as cache key for fast lookups.
    
    Params:
        ttl_seconds: Time-to-live for cache entries (default: None = no expiry)
        max_size: Maximum cache size (default: 1000)
    """
    
    def __init__(self, ttl_seconds: int | None = None, max_size: int = 1000):
        self.cache: Dict[str, Tuple[Any, datetime]] = {}
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        self.hit_count = 0
        self.miss_count = 0
    
    def _get_cache_key(self, messages: list) -> str:
        """Generate cache key from messages."""
        # Convert messages to serializable format
        serializable = []
        for msg in messages:
            if hasattr(msg, 'content'):
                serializable.append({"type": type(msg).__name__, "content": msg.content})
            elif isinstance(msg, dict):
                serializable.append(msg)
            else:
                serializable.append(str(msg))
        
        content = json.dumps(serializable, sort_keys=True)
        return hashlib.md5(content.encode()).hexdigest()
    
    def _is_expired(self, timestamp: datetime) -> bool:
        """Check if cache entry is expired."""
        if self.ttl_seconds is None:
            return False
        age = (datetime.now() - timestamp).total_seconds()
        return age > self.ttl_seconds
    
    def _evict_if_needed(self):
        """Evict oldest entries if cache is full."""
        if len(self.cache) >= self.max_size:
            # Remove oldest 10% of entries
            sorted_keys = sorted(
                self.cache.keys(),
                key=lambda k: self.cache[k][1]
            )
            for key in sorted_keys[:len(sorted_keys) // 10 + 1]:
                del self.cache[key]
    
    def before_model_call(self, state, config, **kwargs):
        """Check cache before making API call."""
        messages = state.get("messages", [])
        cache_key = self._get_cache_key(messages)
        
        if cache_key in self.cache:
            cached_response, timestamp = self.cache[cache_key]
            
            if not self._is_expired(timestamp):
                self.hit_count += 1
                hit_rate = self.hit_count / (self.hit_count + self.miss_count) * 100
                logger.info(
                    "[CACHE] HIT - Returning cached response (hit rate: %.1f%%)",
                    hit_rate
                )
                # Store key for after_model to skip caching
                state["_cache_hit"] = True
                state["_cached_response"] = cached_response
                return state
            else:
                # Expired, remove from cache
                del self.cache[cache_key]
        
        self.miss_count += 1
        state["_cache_key"] = cache_key
        state["_cache_hit"] = False
        logger.info("[CACHE] MISS - Making new API call (cache size: %d)", len(self.cache))
        return state
    
    def after_model_call(self, state, config, response, **kwargs):
        """Store response in cache."""
        if state.get("_cache_hit"):
            return state.get("_cached_response", response)
        
        cache_key = state.get("_cache_key")
        if cache_key:
            self._evict_if_needed()
            self.cache[cache_key] = (response, datetime.now())
            logger.debug("[CACHE] Stored response with key %s", cache_key[:8])
        
        return response
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total = self.hit_count + self.miss_count
        return {
            "hit_count": self.hit_count,
            "miss_count": self.miss_count,
            "hit_rate": (self.hit_count / total * 100) if total > 0 else 0,
            "cache_size": len(self.cache),
            "max_size": self.max_size,
        }
    
    def clear(self):
        """Clear the cache."""
        self.cache.clear()
        logger.info("[CACHE] Cleared")


class RateLimitMiddleware:
    """Rate limits tool calls to prevent abuse.
    
    Params:
        max_calls_per_minute: Maximum calls allowed per minute (default: 60)
        max_calls_per_tool: Maximum calls per tool per minute (default: 20)
    """
    
    def __init__(
        self,
        max_calls_per_minute: int = 60,
        max_calls_per_tool: int = 20,
    ):
        self.max_calls_per_minute = max_calls_per_minute
        self.max_calls_per_tool = max_calls_per_tool
        self.call_timestamps: List[datetime] = []
        self.tool_timestamps: Dict[str, List[datetime]] = {}
    
    def _clean_old_timestamps(self, timestamps: List[datetime]) -> List[datetime]:
        """Remove timestamps older than 1 minute."""
        cutoff = datetime.now()
        one_minute_ago = datetime.fromtimestamp(cutoff.timestamp() - 60)
        return [ts for ts in timestamps if ts > one_minute_ago]
    
    def __call__(self, request, handler):
        """Check rate limits before executing tool."""
        tool_name = request.tool_call.get("name", "unknown")
        now = datetime.now()
        
        # Clean old timestamps
        self.call_timestamps = self._clean_old_timestamps(self.call_timestamps)
        if tool_name in self.tool_timestamps:
            self.tool_timestamps[tool_name] = self._clean_old_timestamps(
                self.tool_timestamps[tool_name]
            )
        
        # Check global rate limit
        if len(self.call_timestamps) >= self.max_calls_per_minute:
            logger.warning("[RATE LIMIT] Global limit exceeded (%d/min)", self.max_calls_per_minute)
            return f"Rate limit exceeded: Maximum {self.max_calls_per_minute} calls per minute"
        
        # Check per-tool rate limit
        tool_calls = self.tool_timestamps.get(tool_name, [])
        if len(tool_calls) >= self.max_calls_per_tool:
            logger.warning(
                "[RATE LIMIT] Tool '%s' limit exceeded (%d/min)",
                tool_name,
                self.max_calls_per_tool
            )
            return f"Rate limit exceeded for tool '{tool_name}': Maximum {self.max_calls_per_tool} calls per minute"
        
        # Record this call
        self.call_timestamps.append(now)
        if tool_name not in self.tool_timestamps:
            self.tool_timestamps[tool_name] = []
        self.tool_timestamps[tool_name].append(now)
        
        return handler(request)


# ============================================================================
# Middleware Factory Functions (for registry integration)
# ============================================================================

def build_tool_log(params: Dict[str, Any]):
    """Build ToolLoggingMiddleware from params."""
    return wrap_tool_call(ToolLoggingMiddleware(
        verbose=params.get("verbose", True),
        log_args=params.get("log_args", True),
    ))


def build_cache(params: Dict[str, Any]):
    """Build CachingMiddleware from params."""
    return CachingMiddleware(
        ttl_seconds=params.get("ttl_seconds"),
        max_size=params.get("max_size", 1000),
    )


def build_tool_access_control(params: Dict[str, Any]):
    """Build ToolAccessControlMiddleware from params."""
    allowed_tools = params.get("allowed_tools", [])
    user_context = params.get("user_context")
    
    if user_context and isinstance(user_context, dict):
        user_context = UserContext(**user_context)
    
    return wrap_tool_call(ToolAccessControlMiddleware(
        allowed_tools=allowed_tools,
        user_context=user_context,
        block_message=params.get("block_message"),
    ))


def build_rate_limit(params: Dict[str, Any]):
    """Build RateLimitMiddleware from params."""
    return wrap_tool_call(RateLimitMiddleware(
        max_calls_per_minute=params.get("max_calls_per_minute", 60),
        max_calls_per_tool=params.get("max_calls_per_tool", 20),
    ))


# Registry of custom middleware factories
CUSTOM_MIDDLEWARE_FACTORIES: Dict[str, Callable[[Dict[str, Any]], Any]] = {
    "tool_log": build_tool_log,
    "cache": build_cache,
    "tool_access_control": build_tool_access_control,
    "rate_limit": build_rate_limit,
}

# Default configurations for custom middleware
CUSTOM_DEFAULT_CONFIGS: Dict[str, Dict[str, Any]] = {
    "tool_log": {
        "verbose": True,
        "log_args": True,
    },
    "cache": {
        "ttl_seconds": None,
        "max_size": 1000,
    },
    "tool_access_control": {
        "allowed_tools": [],
        "block_message": None,
    },
    "rate_limit": {
        "max_calls_per_minute": 60,
        "max_calls_per_tool": 20,
    },
}