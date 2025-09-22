"""Module to define the models for the Adopt API"""

from typing import List
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from typing import Union
from typing import Any

class AdoptAction(BaseModel):
    """Class to define the models for the Adopt API"""
    id: str = Field(default="", description="Action ID")
    title: str = Field(default="", description="Action name")
    description: str = Field(default="", description="Action description")

class AdoptActionListResponse(BaseModel):
    """Class to define the models for the Adopt API"""
    capabilities: List[AdoptAction] = Field(default=[], description="List of actions")

class AdoptActionRunRequest(BaseModel):
    """Class to define the models for the Adopt API"""
    messages: List[Union[HumanMessage, AIMessage, SystemMessage]] = Field(default=[], description="List of messages")
    base_url: str = Field(default="", description="API Base URL for platform")
    application_base_url: str = Field(default="", description="Application Base URL for platform")
    workflow_params: dict[str, Any] = Field(default={}, description="Workflow parameters")
    security_params: dict[str, Any] = Field(default={}, description="Security parameters")

class AdoptActionRunResponse(BaseModel):
    """Class to define the models for the Adopt API"""
    status: bool = Field(default=False, description="Status of the action run")
    response: str = Field(default="", description="Response from the action run")