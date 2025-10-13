"""Gmail OAuth2 authentication management."""

import json
import os
from datetime import datetime, timedelta
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource
from googleapiclient.errors import HttpError

import structlog

from ..settings import settings

logger = structlog.get_logger(__name__)

# Gmail API scopes
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
]


class GmailAuthManager:
    """Manages Gmail OAuth2 authentication and API client."""

    def __init__(self):
        self.credentials_path = settings.gmail_credentials_path
        self.token_path = settings.gmail_token_path
        self._credentials: Optional[Credentials] = None
        self._service: Optional[Resource] = None

    async def get_credentials(self) -> Credentials:
        """Get valid Gmail API credentials, refreshing if necessary."""
        if self._credentials and self._credentials.valid:
            return self._credentials

        # Load existing token if available
        if os.path.exists(self.token_path):
            try:
                self._credentials = Credentials.from_authorized_user_file(
                    self.token_path, SCOPES
                )
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning("Invalid token file, will re-authenticate", error=str(e))
                self._credentials = None

        # If credentials are invalid or missing, refresh or re-authenticate
        if not self._credentials or not self._credentials.valid:
            if self._credentials and self._credentials.expired and self._credentials.refresh_token:
                try:
                    logger.info("Refreshing expired Gmail API credentials")
                    self._credentials.refresh(Request())
                    await self._save_credentials()
                except Exception as e:
                    logger.error("Failed to refresh credentials", error=str(e))
                    self._credentials = None
                    return await self._authenticate()
            else:
                return await self._authenticate()

        return self._credentials

    async def _authenticate(self) -> Credentials:
        """Perform OAuth2 authentication flow."""
        if not os.path.exists(self.credentials_path):
            raise FileNotFoundError(
                f"Gmail credentials file not found at {self.credentials_path}. "
                "Please download from Google Cloud Console."
            )

        logger.info("Starting Gmail OAuth2 authentication flow")

        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                self.credentials_path, SCOPES
            )

            # Run auth flow - for production, this should be handled differently
            # For now, using local server callback
            self._credentials = flow.run_local_server(port=0)

            await self._save_credentials()
            logger.info("Gmail authentication successful")
            return self._credentials

        except Exception as e:
            logger.error("Gmail authentication failed", error=str(e))
            raise

    async def _save_credentials(self) -> None:
        """Save credentials to token file."""
        os.makedirs(os.path.dirname(self.token_path), exist_ok=True)

        with open(self.token_path, "w") as token_file:
            token_file.write(self._credentials.to_json())

    async def get_service(self) -> Resource:
        """Get authenticated Gmail API service."""
        if self._service:
            return self._service

        credentials = await self.get_credentials()
        self._service = build("gmail", "v1", credentials=credentials)
        return self._service

    async def revoke_credentials(self) -> None:
        """Revoke stored credentials."""
        if os.path.exists(self.token_path):
            os.remove(self.token_path)
        self._credentials = None
        self._service = None
        logger.info("Gmail credentials revoked")

    async def test_connection(self) -> dict:
        """Test Gmail API connection and return user info."""
        try:
            service = await self.get_service()

            # Get user profile info
            profile = service.users().getProfile(userId="me").execute()

            return {
                "success": True,
                "email_address": profile.get("emailAddress"),
                "messages_total": profile.get("messagesTotal"),
                "threads_total": profile.get("threadsTotal"),
                "history_id": profile.get("historyId"),
            }
        except HttpError as e:
            logger.error("Gmail API test failed", error=str(e))
            return {
                "success": False,
                "error": str(e),
                "error_code": e.resp.status,
            }
        except Exception as e:
            logger.error("Gmail connection test failed", error=str(e))
            return {
                "success": False,
                "error": str(e),
            }

    def is_authenticated(self) -> bool:
        """Check if valid credentials exist."""
        return (
            self._credentials is not None
            and self._credentials.valid
            or (
                os.path.exists(self.token_path)
                and not self._needs_refresh()
            )
        )

    async def _needs_refresh(self) -> bool:
        """Check if stored credentials need refresh."""
        if not os.path.exists(self.token_path):
            return True

        try:
            with open(self.token_path, "r") as f:
                token_data = json.load(f)

            expiry_str = token_data.get("expiry")
            if expiry_str:
                expiry = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
                # Refresh if expires in next hour
                return datetime.utcnow() + timedelta(hours=1) >= expiry

            return True
        except Exception:
            return True


# Global auth manager instance
auth_manager = GmailAuthManager()