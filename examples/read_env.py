"""Module to read the environment variables from the dev.env file"""

import os
from typing import Optional
from pydantic import BaseModel, Field

class AdoptEnv(BaseModel):
    """Class to read the environment variables from the dev.env file"""
    ADOPT_CLIENT_ID: Optional[str] = Field(default=None, description="Client ID for Adopt API authentication")
    ADOPT_CLIENT_SECRET: Optional[str] = Field(default=None, description="Client secret for Adopt API authentication")
    ADOPT_API_ENDPOINT: Optional[str] = Field(default="https://connect.adopt.ai", description="Endpoint where Adopt is running")

def read_env() -> AdoptEnv:
    """Read the environment variables from the dev.env file"""
    adopt_env = AdoptEnv(**os.environ)
    if adopt_env.ADOPT_CLIENT_ID is None or adopt_env.ADOPT_CLIENT_SECRET is None:
        raise ValueError("ADOPT_CLIENT_ID and ADOPT_CLIENT_SECRET are required")
    return adopt_env