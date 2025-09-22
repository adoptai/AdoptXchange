"""Module to define the models for the Adopt API"""

from pydantic import BaseModel, Field

class AdoptActionListResponse(BaseModel):
    """Class to define the models for the Adopt API"""
    capabilities: list[AdoptAction] = Field(default=[], description="List of actions")

class AdoptAction(BaseModel):
    """Class to define the models for the Adopt API"""
    id: str = Field(default="", description="Action ID")
    title: str = Field(default="", description="Action name")
    description: str = Field(default="", description="Action description")

class AdoptActionRunRequest(BaseModel):
    """Class to define the models for the Adopt API"""
    messages: list[AdoptMessage] = Field(default=[], description="List of messages")
    base_url: str = Field(default="", description="API Base URL for platform")
    application_base_url: str = Field(default="", description="Application Base URL for platform")
    workflow_params: dict = Field(default={}, description="Workflow parameters")
    security_params: dict = Field(default={}, description="Security parameters")

class AdoptMessage(BaseModel):
    """Class to define the models for the Adopt API"""
    role: str = Field(default="", description="Message role")
    content: str = Field(default="", description="Message content")

class AdoptActionRunResponse(BaseModel):
    """Class to define the models for the Adopt API"""
    status: bool = Field(default=False, description="Status of the action run")
    response: str = Field(default="", description="Response from the action run")