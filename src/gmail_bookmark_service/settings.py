"""Configuration settings for Gmail bookmark service."""

from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""

    # Gmail API Configuration
    gmail_credentials_path: str = Field(
        default="config/gmail_credentials.json",
        description="Path to Gmail API OAuth2 credentials file"
    )
    gmail_token_path: str = Field(
        default="data/gmail_token.json",
        description="Path to store Gmail OAuth2 tokens"
    )
    gmail_watch_label: Optional[str] = Field(
        default=None,
        description="Label to watch (null = entire inbox)"
    )

    # GCP Configuration
    gcp_project_id: str = Field(
        description="GCP Project ID"
    )
    pubsub_topic: str = Field(
        default="gmail-notifications",
        description="Pub/Sub topic name for Gmail notifications"
    )
    pubsub_subscription: str = Field(
        default="gmail-push-subscription",
        description="Pub/Sub subscription name"
    )

    # Service Configuration
    webhook_port: int = Field(
        default=8443,
        description="Port for HTTPS webhook server"
    )
    webhook_host: str = Field(
        default="0.0.0.0",
        description="Host to bind webhook server"
    )
    data_directory: str = Field(
        default="data",
        description="Directory for storing data and attachments"
    )

    # Database
    database_url: str = Field(
        default="sqlite:///data/bookmarks.db",
        description="Database connection URL"
    )

    # Security
    webhook_secret: str = Field(
        description="Secret for webhook signature verification"
    )

    # Processing
    max_attachment_size: int = Field(
        default=25 * 1024 * 1024,  # 25MB
        description="Maximum attachment size to download"
    )
    processing_workers: int = Field(
        default=4,
        description="Number of background processing workers"
    )

    # Monitoring
    log_level: str = Field(
        default="INFO",
        description="Logging level"
    )
    health_check_interval: int = Field(
        default=300,  # 5 minutes
        description="Health check interval in seconds"
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Global settings instance
settings = Settings()