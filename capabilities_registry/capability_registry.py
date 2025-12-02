# capabilities/registry.py
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Callable

from examples.action_api_samples.adopt_client import AdoptClient
from examples.models import AdoptAction, AdoptActionListResponse  # your types
from .capability_config import CAPABILITY_KEY_TO_ID
from examples.tool_calling_samples.tool_factory import create_adopt_tool
# We left create_adopt_tool, create_tool_schema, sanitize_tool_name, etc. outside the class because they're:
# Stateless, pure helpers (they don't care about registry state)
# Generally useful beyond just CapabilityRegistry
# Easier to test / reuse / swap if they're not tied to one class

logger = logging.getLogger(__name__)

class CapabilityRegistry:
    """
        Registry that:
        - loads all Adopt capabilities once via AdoptClient
        - maps friendly keys -> capability IDs (CAPABILITY_KEY_TO_ID)
        - builds LangChain tools for a given list of keys
    """

    def __init__(self, client: AdoptClient) -> None:
        self._client = client
        self._loaded: bool = False
        self._actions_by_id: Dict[str, AdoptAction] = {}

    async def _ensure_loaded(self, execution_type: str = "DEFAULT") -> None:
        if self._loaded:
            return

        resp: AdoptActionListResponse = await self._client.fetch_adopt_actions(
            execution_type=execution_type
        )
        capabilities: List[AdoptAction] = resp.capabilities
        self._actions_by_id = {c.id: c for c in capabilities}
        self._loaded = True
        print("Loaded %d Adopt capabilities into registry", len(capabilities))

    async def get_tools_for_keys(
        self,
        capability_keys: List[str],
        profile: Dict[str, Any],
        execution_type: str = "DEFAULT",
    ) -> List[Callable]:
        """
        High-level API:
        - AI engineer passes names like ["campaign_details", "deactivate_a_keyword_from_track"].
        - We look up IDs, find AdoptAction objects, and return LangChain tools.
        """
        await self._ensure_loaded(execution_type)

        tools: List[Callable] = []
        for key in capability_keys:
            cap_id = CAPABILITY_KEY_TO_ID.get(key)
            if not cap_id:
                logger.warning("No capability ID found for key=%s", key)
                continue

            capability = self._actions_by_id.get(cap_id)
            if not capability:
                logger.error(
                    "Capability id=%s (key=%s) not found in fetched actions. "
                    "It may have been removed or changed in Adopt.",
                    cap_id,
                    key,
                )
                # Optional: you could create a stub tool here instead of skipping.
                continue

            tools.append(create_adopt_tool(self._client, capability, profile))

        return tools

    async def get_all_tools(
        self,
        profile: Dict[str, Any],
        execution_type: str = "DEFAULT",
    ) -> List[Callable]:
        """
        Return tools for all capabilities (rarely used in prod, but nice for POC).
        """
        await self._ensure_loaded(execution_type)
        return [
            create_adopt_tool(self._client, cap, profile)
            for cap in self._actions_by_id.values()
        ]