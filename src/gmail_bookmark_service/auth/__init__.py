"""Authentication package for Gmail bookmark service."""

from .gmail_auth import auth_manager, GmailAuthManager, SCOPES

__all__ = [
    "auth_manager",
    "GmailAuthManager",
    "SCOPES",
]