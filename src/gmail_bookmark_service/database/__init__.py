"""Database package for Gmail bookmark service."""

from .connection import init_database, get_db, get_db_session
from .models import Base, Bookmark, ProcessingState, FailedMessage

__all__ = [
    "init_database",
    "get_db",
    "get_db_session",
    "Base",
    "Bookmark",
    "ProcessingState",
    "FailedMessage",
]