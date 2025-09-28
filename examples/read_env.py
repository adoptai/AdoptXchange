"""Module to read the environment variables from the dev.env file"""

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
    BEDROCK_MODEL: Optional[str] = Field(default="us.anthropic.claude-4-sonnet-20250514-v1:0", description="Bedrock model to use")

def read_env() -> AdoptEnv:
    """Read the environment variables from the dev.env file"""
    # Load .env file if it exists
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    load_dotenv(env_path)
    
    adopt_env = AdoptEnv(**os.environ)
    if adopt_env.ADOPT_CLIENT_ID is None or adopt_env.ADOPT_CLIENT_SECRET is None:
        raise ValueError("ADOPT_CLIENT_ID and ADOPT_CLIENT_SECRET are required")
    if adopt_env.AWS_SECRET_ACCESS_KEY is None or adopt_env.AWS_ACCESS_KEY_ID is None:
        raise ValueError("AWS_SECRET_ACCESS_KEY and AWS_ACCESS_KEY_ID are required for Bedrock")
    return adopt_env