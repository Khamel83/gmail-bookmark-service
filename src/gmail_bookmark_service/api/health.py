"""Health check endpoints for Gmail bookmark service."""

import asyncio
from datetime import datetime
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

import structlog

from ..auth.gmail_auth import auth_manager
from ..processing.pubsub_manager import pubsub_manager
from ..database import get_db_session
from ..database.models import ProcessingState, Bookmark
from ..settings import settings

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.get("/health")
async def health_check() -> JSONResponse:
    """Comprehensive health check for the service."""
    health_status = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "gmail-bookmark-service",
        "version": "1.0.0",
        "checks": {},
    }

    # Run all health checks
    checks = [
        ("database", check_database_health),
        ("gmail_auth", check_gmail_auth_health),
        ("gmail_watch", check_gmail_watch_health),
        ("pubsub", check_pubsub_health),
    ]

    tasks = [check_func() for check_name, check_func in checks]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for (check_name, _), result in zip(checks, results):
        if isinstance(result, Exception):
            health_status["checks"][check_name] = {
                "status": "unhealthy",
                "error": str(result),
            }
            health_status["status"] = "degraded"
        else:
            health_status["checks"][check_name] = result
            if result["status"] != "healthy":
                health_status["status"] = "degraded"

    # Determine HTTP status
    status_code = 200 if health_status["status"] == "healthy" else 503

    return JSONResponse(status_code=status_code, content=health_status)


async def check_database_health() -> Dict:
    """Check database connectivity and basic operations."""
    try:
        async with get_db_session() as db:
            # Test basic query
            result = await db.execute("SELECT 1")
            await result.scalar_one()

            # Check processing state table
            from sqlalchemy import select, func

            bookmark_count = await db.scalar(
                select(func.count(Bookmark.id))
            )

            return {
                "status": "healthy",
                "bookmark_count": bookmark_count,
                "timestamp": datetime.utcnow().isoformat(),
            }

    except Exception as e:
        logger.error("Database health check failed", error=str(e))
        raise


async def check_gmail_auth_health() -> Dict:
    """Check Gmail API authentication."""
    try:
        test_result = await auth_manager.test_connection()

        if test_result["success"]:
            return {
                "status": "healthy",
                "email_address": test_result["email_address"],
                "authenticated": True,
                "timestamp": datetime.utcnow().isoformat(),
            }
        else:
            return {
                "status": "unhealthy",
                "error": test_result["error"],
                "authenticated": False,
                "timestamp": datetime.utcnow().isoformat(),
            }

    except Exception as e:
        logger.error("Gmail auth health check failed", error=str(e))
        raise


async def check_gmail_watch_health() -> Dict:
    """Check Gmail watch status."""
    try:
        async with get_db_session() as db:
            from sqlalchemy import select

            result = await db.execute(
                select(ProcessingState).where(ProcessingState.key == "gmail_watch")
            )
            state = result.scalar_one_or_none()

            if state and state.value:
                import json

                watch_data = json.loads(state.value)
                expiration = datetime.fromisoformat(watch_data["expiration"].replace("Z", "+00:00"))
                now = datetime.utcnow()

                if expiration > now:
                    hours_until_expiry = (expiration - now).total_seconds() / 3600
                    return {
                        "status": "healthy",
                        "active": True,
                        "history_id": watch_data["history_id"],
                        "expiration": watch_data["expiration"],
                        "hours_until_expiry": round(hours_until_expiry, 2),
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                else:
                    return {
                        "status": "unhealthy",
                        "active": False,
                        "error": "Watch expired",
                        "expiration": watch_data["expiration"],
                        "timestamp": datetime.utcnow().isoformat(),
                    }
            else:
                return {
                    "status": "unhealthy",
                    "active": False,
                    "error": "No active watch found",
                    "timestamp": datetime.utcnow().isoformat(),
                }

    except Exception as e:
        logger.error("Gmail watch health check failed", error=str(e))
        raise


async def check_pubsub_health() -> Dict:
    """Check Pub/Sub connectivity."""
    try:
        # Basic check - verify we can create topic paths
        topic_path = pubsub_manager.get_topic_path()
        subscription_path = pubsub_manager.get_subscription_path()

        return {
            "status": "healthy",
            "topic_path": topic_path,
            "subscription_path": subscription_path,
            "project_id": settings.gcp_project_id,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error("Pub/Sub health check failed", error=str(e))
        raise


@router.get("/health/simple")
async def simple_health_check() -> JSONResponse:
    """Simple health check for load balancers."""
    return JSONResponse(
        status_code=200,
        content={
            "status": "ok",
            "timestamp": datetime.utcnow().isoformat(),
        },
    )