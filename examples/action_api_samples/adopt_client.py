"""
Adopt API Client
Async HTTP client for authenticating and interacting with Adopt service APIs.
Uses httpx for async HTTP operations and supports OAuth2 client credentials flow.
Configuration via environment variables:
- ADOPT_API_ENDPOINT: Base URL for Adopt API (default: https://adopt.dev.6si.com)
- ADOPT_CLIENT_ID: OAuth2 client ID (required)
- ADOPT_CLIENT_SECRET: OAuth2 client secret (required)
- ADOPT_TIMEOUT_SECONDS: Request timeout in seconds (default: 30)
Example usage:
    client = AdoptClient()
    await client.authenticate()
    response = await client.get("/v1/actions/list")
    data = response.json()
"""
import logging
import time
from typing import Any, Dict, Optional, Union, List
import httpx
from examples.action_api_samples.api_constants import ADOPT_TOKEN_PATH, ADOPT_ACTIONS_LIST_PATH, ADOPT_RUN_ACTION_PATH
from examples.models import AdoptRunActionByIdRequest, AdoptActionListResponse
from examples.read_env import read_env, AdoptEnv
from langchain_core.messages import HumanMessage, AIMessage

logger = logging.getLogger(__name__)

def get_adopt_env() -> AdoptEnv:
    """Get the Adopt environment variables."""
    return read_env()

class AdoptAuthError(Exception):
    """Raised when authentication with Adopt service fails."""
    pass
class AdoptClient:
    """
    Async client for Adopt API with OAuth2 client credentials authentication.
    
    Handles token management, automatic refresh, and authenticated HTTP requests.
    All operations are async and use httpx for HTTP communication.
    
    Attributes:
        base_url: Base URL for the Adopt API
        client_id: OAuth2 client ID for authentication
        client_secret: OAuth2 client secret for authentication
        timeout: Request timeout in seconds
        verify_tls: Whether to verify SSL/TLS certificates
    """
    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        verify_tls: bool = False,
    ) -> None:
        """
        Initialize the Adopt API client.
        
        Args:
            client_id: OAuth2 client ID (defaults to ADOPT_CLIENT_ID env var)
            client_secret: OAuth2 client secret (defaults to ADOPT_CLIENT_SECRET env var)
            base_url: Base URL for API (defaults to ADOPT_API_ENDPOINT env var)
            timeout_seconds: Request timeout (defaults to ADOPT_TIMEOUT_SECONDS env var)
            verify_tls: Whether to verify SSL/TLS certificates (default: False)
        """


        adopt_env = get_adopt_env()

        self.base_url = (base_url or adopt_env.ADOPT_API_ENDPOINT).rstrip("/")
        self.client_id = client_id or adopt_env.ADOPT_CLIENT_ID
        self.client_secret = client_secret or adopt_env.ADOPT_CLIENT_SECRET
        self.timeout = timeout_seconds or adopt_env.ADOPT_TIMEOUT_SECONDS
        self.verify_tls = verify_tls
        
        # Token management
        self._access_token: Optional[str] = None
        self._token_type: str = "Bearer"
        self._token_expires_at: Optional[float] = None  # epoch seconds
        if not self.client_id or not self.client_secret:
            logger.warning(
                "AdoptClient initialized without client credentials. "
                "Set ADOPT_CLIENT_ID/ADOPT_CLIENT_SECRET or pass them explicitly."
            )
    async def authenticate(self) -> None:
        """
        Authenticate using OAuth2 client credentials flow.
        
        Obtains an access token from the Adopt API token endpoint and stores it
        for use in subsequent authenticated requests. Automatically called by
        other methods if no valid token exists.
        
        Raises:
            AdoptAuthError: If authentication fails or no access token is returned
        """
        payload = {
            "grant_type": "client_credentials",
            "clientId": self.client_id,
            "secret": self.client_secret,
        }
        headers = {"Accept": "application/json"}
        url = self._abs_url(ADOPT_TOKEN_PATH)
        
        logger.debug("Authenticating with Adopt token endpoint", extra={"url": url})
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=self.verify_tls) as client:
                # Try JSON payload first
                resp = await client.post(url, json=payload, headers=headers)
                
                # If JSON fails, retry with form-encoded payload
                if resp.status_code >= 400:
                    logger.debug("JSON auth failed, retrying with form-encoded payload")
                    resp = await client.post(url, data=payload, headers=headers)
                
                resp.raise_for_status()
                body = resp.json()
                
        except httpx.HTTPError as e:
            logger.exception("Adopt authentication failed: %s", str(e))
            raise AdoptAuthError(f"Adopt auth failed: {e}") from e
        duration_ms = int((time.perf_counter() - start) * 1000)
        
        # Extract token from response
        token = body.get("access_token") or body.get("token")
        token_type = body.get("token_type", "Bearer")
        expires_in = body.get("expires_in")
        if not token:
            logger.error(
                "Adopt authentication response missing access_token. Body keys: %s",
                list(body.keys()),
            )
            raise AdoptAuthError("Adopt auth succeeded but no access_token was returned")
        # Store token and expiration
        self._access_token = token
        self._token_type = token_type
        if isinstance(expires_in, (int, float)):
            self._token_expires_at = time.time() + float(expires_in)
        else:
            self._token_expires_at = None
        logger.info(
            "Adopt authentication successful",
            extra={
                "duration_ms": duration_ms,
                "token_type": self._token_type,
                "has_expiry": self._token_expires_at is not None,
            },
        )
    async def _ensure_token(self) -> None:
        """
        Ensure a valid access token exists.
        
        Authenticates if no token exists or if the current token is expired
        or about to expire (within 30 seconds).
        """
        if not self._access_token:
            await self.authenticate()
            return
            
        # Refresh token 30 seconds before expiry
        if self._token_expires_at and time.time() >= self._token_expires_at - 30:
            logger.debug("Token expiring soon, refreshing authentication")
            await self.authenticate()
    def _auth_header(self) -> Dict[str, str]:
        """
        Get authorization header with current access token.
        
        Returns:
            Dictionary containing Authorization header
            
        Note:
            Does not perform async token refresh. Call _ensure_token() first.
        """
        if not self._access_token:
            raise AdoptAuthError("No access token available. Call authenticate() first.")
        return {"Authorization": f"{self._token_type} {self._access_token}"}
    def _abs_url(self, path: str) -> str:
        """
        Convert a relative path to an absolute URL.
        
        Args:
            path: API path (relative or absolute)
            
        Returns:
            Absolute URL with base URL prepended
        """
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"
    async def get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[Union[int, float]] = None,
    ) -> httpx.Response:
        """
        Perform an authenticated GET request.
        
        Args:
            path: API endpoint path (relative or absolute URL)
            params: Query parameters to include in the request
            headers: Additional headers to send with the request
            timeout: Request timeout in seconds (overrides default)
            
        Returns:
            httpx.Response object with the API response
            
        Raises:
            httpx.HTTPError: If the request fails
            AdoptAuthError: If authentication fails
        """
        await self._ensure_token()
        
        url = self._abs_url(path)
        req_headers = {"Accept": "application/json"}
        req_headers.update(self._auth_header())
        if headers:
            req_headers.update(headers)
        logger.debug("Adopt GET request", extra={"url": url, "has_params": params is not None})
        
        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=timeout or self.timeout, verify=self.verify_tls) as client:
            resp = await client.get(url, params=params, headers=req_headers)
        
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "Adopt GET completed",
            extra={"status_code": resp.status_code, "duration_ms": duration_ms, "url": url}
        )
        
        resp.raise_for_status()
        return resp
    async def post(
        self,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[Union[int, float]] = None,
    ) -> httpx.Response:
        """
        Perform an authenticated POST request.
        
        Args:
            path: API endpoint path (relative or absolute URL)
            json: JSON data to send in the request body
            data: Form data to send in the request body (mutually exclusive with json)
            headers: Additional headers to send with the request
            timeout: Request timeout in seconds (overrides default)
            
        Returns:
            httpx.Response object with the API response
            
        Raises:
            httpx.HTTPError: If the request fails
            AdoptAuthError: If authentication fails
        """
        await self._ensure_token()
        
        url = self._abs_url(path)
        req_headers = {"Accept": "application/json"}
        req_headers.update(self._auth_header())
        if headers:
            req_headers.update(headers)
        logger.debug(
            "Adopt POST request",
            extra={"url": url, "has_json": json is not None, "has_data": data is not None}
        )
        
        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=timeout or self.timeout, verify=self.verify_tls) as client:
            resp = await client.post(url, json=json, data=data, headers=req_headers)
        
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "Adopt POST completed",
            extra={"status_code": resp.status_code, "duration_ms": duration_ms, "url": url}
        )
        
        resp.raise_for_status()
        return resp
    async def put(
        self,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[Union[int, float]] = None,
    ) -> httpx.Response:
        """
        Perform an authenticated PUT request.
        
        Args:
            path: API endpoint path (relative or absolute URL)
            json: JSON data to send in the request body
            data: Form data to send in the request body (mutually exclusive with json)
            headers: Additional headers to send with the request
            timeout: Request timeout in seconds (overrides default)
            
        Returns:
            httpx.Response object with the API response
            
        Raises:
            httpx.HTTPError: If the request fails
            AdoptAuthError: If authentication fails
        """
        await self._ensure_token()
        
        url = self._abs_url(path)
        req_headers = {"Accept": "application/json"}
        req_headers.update(self._auth_header())
        if headers:
            req_headers.update(headers)
        logger.debug(
            "Adopt PUT request",
            extra={"url": url, "has_json": json is not None, "has_data": data is not None}
        )
        
        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=timeout or self.timeout, verify=self.verify_tls) as client:
            resp = await client.put(url, json=json, data=data, headers=req_headers)
        
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "Adopt PUT completed",
            extra={"status_code": resp.status_code, "duration_ms": duration_ms, "url": url}
        )
        
        resp.raise_for_status()
        return resp
    async def delete(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[Union[int, float]] = None,
    ) -> httpx.Response:
        """
        Perform an authenticated DELETE request.
        
        Args:
            path: API endpoint path (relative or absolute URL)
            params: Query parameters to include in the request
            headers: Additional headers to send with the request
            timeout: Request timeout in seconds (overrides default)
            
        Returns:
            httpx.Response object with the API response
            
        Raises:
            httpx.HTTPError: If the request fails
            AdoptAuthError: If authentication fails
        """
        await self._ensure_token()
        
        url = self._abs_url(path)
        req_headers = {"Accept": "application/json"}
        req_headers.update(self._auth_header())
        if headers:
            req_headers.update(headers)
        logger.debug("Adopt DELETE request", extra={"url": url, "has_params": params is not None})
        
        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=timeout or self.timeout, verify=self.verify_tls) as client:
            resp = await client.delete(url, params=params, headers=req_headers)
        
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "Adopt DELETE completed",
            extra={"status_code": resp.status_code, "duration_ms": duration_ms, "url": url}
        )
        
        resp.raise_for_status()
        return resp
    async def patch(
        self,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[Union[int, float]] = None,
    ) -> httpx.Response:
        """
        Perform an authenticated PATCH request.
        
        Args:
            path: API endpoint path (relative or absolute URL)
            json: JSON data to send in the request body
            data: Form data to send in the request body (mutually exclusive with json)
            headers: Additional headers to send with the request
            timeout: Request timeout in seconds (overrides default)
            
        Returns:
            httpx.Response object with the API response
            
        Raises:
            httpx.HTTPError: If the request fails
            AdoptAuthError: If authentication fails
        """
        await self._ensure_token()
        
        url = self._abs_url(path)
        req_headers = {"Accept": "application/json"}
        req_headers.update(self._auth_header())
        if headers:
            req_headers.update(headers)
        logger.debug(
            "Adopt PATCH request",
            extra={"url": url, "has_json": json is not None, "has_data": data is not None}
        )
        
        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=timeout or self.timeout, verify=self.verify_tls) as client:
            resp = await client.patch(url, json=json, data=data, headers=req_headers)
        
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "Adopt PATCH completed",
            extra={"status_code": resp.status_code, "duration_ms": duration_ms, "url": url}
        )
        
        resp.raise_for_status()
        return resp

    async def close(self) -> None:
        """
        Close the client and clean up resources.
        
        Note: httpx.AsyncClient is used as a context manager in each request,
        so this method is mainly for future extensibility and consistency.
        """
        logger.debug("AdoptClient closed")

    async def fetch_adopt_actions(self, execution_type: str = "DEFAULT") -> List[Dict[str, Any]]:
        """
        Fetch all available Adopt actions from the list endpoint.
        
        Args:
            execution_type: Optional execution type to filter actions
            
        Returns:
            List of action capabilities
            
        Raises:
            AdoptActionFilterError: If fetching actions fails
        """
        try:
            logger.info(f"Fetching Adopt actions from list endpoint with execution_type={execution_type}")
            url = f"{ADOPT_ACTIONS_LIST_PATH}?execution_type={execution_type}"
            response = await self.get(url)
            data = response.json()
            capabilities = data.get("capabilities", [])
            logger.info(f"Fetched {len(capabilities)} Adopt {execution_type} actions")
            return AdoptActionListResponse(capabilities=capabilities)
        except Exception as e:
            error_msg = f"Failed to fetch Adopt actions: {str(e)}"
            logger.exception(error_msg)

    async def run_action_by_id(
        self,
        request: AdoptRunActionByIdRequest,
    ) -> str:
        """Execute a specific action by its ID.
        
        This function is designed for tool calling scenarios where you want to
        execute a specific action directly by its ID.
        
        Args:
            action_id: The unique ID of the action to execute
            user_input: Natural language description of what to do
            profile: The adopt profile configuration
            workflow_params: Optional workflow parameters for actions with required inputs
            access_token: Optional authentication token to reuse
            
        Returns:
            The response from the action execution
        """        
        # Create message with user input
        message = HumanMessage(content=request.user_input)
        
        # Merge workflow_params with profile workflow_params
        combined_workflow_params = {**request.profile.get("workflow_params", {})}
        if request.workflow_params:
            combined_workflow_params.update(request.workflow_params)
        
        # Build request payload with action_id and execution_type
        # NOTE: We use DEFAULT execution type for running actions, even if they were
        # discovered using TOOL execution type. The backend will determine tool mode
        # based on the action's is_tool_mode flag in the database.
        request_payload = {
            "messages": [message.model_dump()],
            "action_id": request.action_id,
            "execution_type": "TOOL",
            "base_url": request.profile.get("base_url", ""),
            "application_base_url": request.profile.get("application_base_url", ""),
            "workflow_params": combined_workflow_params,
            "security_params": request.profile.get("security_params", {})
        }
        
        response = await self.post(ADOPT_RUN_ACTION_PATH, json=request_payload)

        if response.status_code != 200:
            raise ValueError(f"API request failed with status code {response.status_code}: {response.text}")
        
        json_response = response.json()
        
        if json_response.get("status") != True:
            print(f"API returned unsuccessful status: {json_response}")
            raise ValueError(f"API returned unsuccessful status: {json_response}")
        
        # Check for expected content in response
        if "ai_message" not in json_response:
            raise ValueError(f"API response missing 'ai_message' field: {json_response}")
        
        ai_message = AIMessage(**json_response["ai_message"])
        if not isinstance(ai_message.content, list): # pyright: ignore
            raise ValueError(f"Action message content is not a list. It is: {type(ai_message.content)}") # pyright: ignore
        return "\n".join(str(item) for item in ai_message.content) # pyright: ignore