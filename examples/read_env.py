"""Module to read the environment variables from .env files"""

import os
from typing import Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv


class AdoptEnv(BaseModel):
    """Class to read the environment variables from the dev.env file"""
    ADOPT_CLIENT_ID: Optional[str] = Field(default=None, description="Client ID for Adopt API authentication")
    ADOPT_CLIENT_SECRET: Optional[str] = Field(default=None, description="Client secret for Adopt API authentication")
    ADOPT_API_ENDPOINT: Optional[str] = Field(default="https://connect.adopt.ai", description="Endpoint where Adopt is running")
    AWS_SECRET_ACCESS_KEY: Optional[str] = Field(default=None, description="AWS Secret Access Key for Bedrock")
    AWS_ACCESS_KEY_ID: Optional[str] = Field(default=None, description="AWS Access Key ID for Bedrock")
    AWS_REGION: Optional[str] = Field(default="us-east-1", description="AWS Region for Bedrock")
    BEDROCK_MODEL: Optional[str] = Field(default="us.anthropic.claude-3-5-haiku-20241022-v1:0", description="Bedrock model to use")
    MAXIM_API_KEY: Optional[str] = Field(default=None, description="Maxim API Key for evaluation platform")
    MAXIM_WORKSPACE_ID: Optional[str] = Field(default=None, description="Maxim Workspace ID for storing evaluation results")
    ADOPT_TIMEOUT_SECONDS: Optional[int] = Field(default=30, description="Timeout for Adopt API requests")
    OPENAI_API_KEY: Optional[str] = Field(default="", description="OpenAI API Key for OpenAI models")

def read_env() -> AdoptEnv:
    """Read the environment variables from .env files"""
    # Load environment variables from .env file (if not already loaded)
    load_dotenv()
    
    adopt_env = AdoptEnv(**os.environ)
    if adopt_env.ADOPT_CLIENT_ID is None or adopt_env.ADOPT_CLIENT_SECRET is None:
        raise ValueError("ADOPT_CLIENT_ID and ADOPT_CLIENT_SECRET are required")
    if adopt_env.AWS_SECRET_ACCESS_KEY is None or adopt_env.AWS_ACCESS_KEY_ID is None:
        raise ValueError("AWS_SECRET_ACCESS_KEY and AWS_ACCESS_KEY_ID are required for Bedrock")
    return adopt_env