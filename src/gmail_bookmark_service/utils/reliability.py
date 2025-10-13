"""Reliability features: error handling, retries, and recovery."""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Any
from functools import wraps

import structlog

from ..database import get_db_session
from ..database.models import FailedMessage, ProcessingState
from ..processing.message_processor import message_processor
from ..processing.pubsub_manager import pubsub_manager
from ..auth.gmail_auth import auth_manager

logger = structlog.get_logger(__name__)


class RetryManager:
    """Manages retry logic for failed operations."""

    def __init__(self):
        self.max_retries = 3
        self.base_delay = 1.0  # seconds
        self.max_delay = 60.0  # seconds
        self.backoff_factor = 2.0

    def exponential_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff delay."""
        delay = self.base_delay * (self.backoff_factor ** attempt)
        return min(delay, self.max_delay)

    async def retry_with_backoff(
        self,
        func: Callable,
        *args,
        max_retries: Optional[int] = None,
        **kwargs
    ) -> Any:
        """Execute function with exponential backoff retry."""
        retries = max_retries or self.max_retries

        for attempt in range(retries + 1):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                if attempt == retries:
                    logger.error(
                        "Operation failed after all retries",
                        func=func.__name__,
                        attempt=attempt,
                        error=str(e),
                    )
                    raise

                delay = self.exponential_backoff(attempt)
                logger.warning(
                    "Operation failed, retrying",
                    func=func.__name__,
                    attempt=attempt,
                    delay=delay,
                    error=str(e),
                )
                await asyncio.sleep(delay)


class WatchManager:
    """Manages Gmail watch lifecycle and automatic renewal."""

    def __init__(self):
        self.renewal_task: Optional[asyncio.Task] = None
        self.daily_scan_task: Optional[asyncio.Task] = None
        self.running = False

    async def start(self, webhook_url: str) -> None:
        """Start watch management tasks."""
        if self.running:
            logger.warning("Watch manager already running")
            return

        self.running = True

        # Start renewal task
        self.renewal_task = asyncio.create_task(
            self._renewal_loop(webhook_url)
        )

        # Start daily scan task
        self.daily_scan_task = asyncio.create_task(
            self._daily_scan_loop()
        )

        logger.info("Watch manager started")

    async def stop(self) -> None:
        """Stop watch management tasks."""
        self.running = False

        if self.renewal_task:
            self.renewal_task.cancel()
            try:
                await self.renewal_task
            except asyncio.CancelledError:
                pass

        if self.daily_scan_task:
            self.daily_scan_task.cancel()
            try:
                await self.daily_scan_task
            except asyncio.CancelledError:
                pass

        logger.info("Watch manager stopped")

    async def _renewal_loop(self, webhook_url: str) -> None:
        """Periodically check and renew Gmail watch."""
        retry_manager = RetryManager()

        while self.running:
            try:
                # Check every 6 hours
                await asyncio.sleep(6 * 3600)

                result = await retry_manager.retry_with_backoff(
                    pubsub_manager.renew_watch_if_needed,
                    webhook_url,
                    max_retries=2,
                )

                if result.get("success"):
                    logger.info("Watch renewal check completed", result=result)
                else:
                    logger.error("Watch renewal failed", error=result.get("error"))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Unexpected error in renewal loop", error=str(e))

    async def _daily_scan_loop(self) -> None:
        """Daily scan to catch any missed messages."""
        retry_manager = RetryManager()

        while self.running:
            try:
                # Run daily at 2 AM UTC
                now = datetime.utcnow()
                next_run = now.replace(hour=2, minute=0, second=0, microsecond=0)
                if next_run <= now:
                    next_run += timedelta(days=1)

                sleep_seconds = (next_run - now).total_seconds()
                await asyncio.sleep(sleep_seconds)

                logger.info("Starting daily scan for missed messages")
                await self._run_daily_scan()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in daily scan loop", error=str(e))

    async def _run_daily_scan(self) -> None:
        """Scan last 24 hours for any missed messages."""
        try:
            service = await auth_manager.get_service()

            # Get messages from last 24 hours
            yesterday = datetime.utcnow() - timedelta(days=1)
            query = f"after:{yesterday.strftime('%Y/%m/%d')}"

            response = service.users().messages().list(
                userId="me",
                q=query,
                maxResults=500,  # Process in batches
            ).execute()

            messages = response.get("messages", [])
            if not messages:
                logger.info("No messages found in daily scan")
                return

            logger.info("Processing messages from daily scan", message_count=len(messages))

            # Process each message
            processed_count = 0
            already_processed_count = 0
            failed_count = 0

            for message in messages:
                try:
                    result = await message_processor._process_single_message(message["id"])
                    if result.get("success"):
                        if result.get("action") == "already_processed":
                            already_processed_count += 1
                        else:
                            processed_count += 1
                    else:
                        failed_count += 1
                except Exception as e:
                    logger.error("Failed to process message in daily scan", message_id=message["id"], error=str(e))
                    failed_count += 1

            logger.info(
                "Daily scan completed",
                processed=processed_count,
                already_processed=already_processed_count,
                failed=failed_count,
            )

        except Exception as e:
            logger.error("Failed to run daily scan", error=str(e))


class FailureRecoveryManager:
    """Manages recovery of failed messages."""

    def __init__(self):
        self.recovery_task: Optional[asyncio.Task] = None
        self.running = False

    async def start(self) -> None:
        """Start failure recovery task."""
        if self.running:
            logger.warning("Failure recovery manager already running")
            return

        self.running = True
        self.recovery_task = asyncio.create_task(self._recovery_loop())
        logger.info("Failure recovery manager started")

    async def stop(self) -> None:
        """Stop failure recovery task."""
        self.running = False

        if self.recovery_task:
            self.recovery_task.cancel()
            try:
                await self.recovery_task
            except asyncio.CancelledError:
                pass

        logger.info("Failure recovery manager stopped")

    async def _recovery_loop(self) -> None:
        """Periodically attempt to recover failed messages."""
        retry_manager = RetryManager()

        while self.running:
            try:
                # Run every hour
                await asyncio.sleep(3600)

                await self._recover_failed_messages(retry_manager)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in recovery loop", error=str(e))

    async def _recover_failed_messages(self, retry_manager: RetryManager) -> None:
        """Attempt to recover failed messages."""
        try:
            async with get_db_session() as db:
                from sqlalchemy import select

                # Get failed messages with low retry count
                result = await db.execute(
                    select(FailedMessage)
                    .where(
                        FailedMessage.retry_count < 3,
                        FailedMessage.last_attempt_at < datetime.utcnow() - timedelta(hours=1)
                    )
                    .order_by(FailedMessage.created_at)
                    .limit(50)
                )
                failed_messages = result.scalars().all()

            if not failed_messages:
                return

            logger.info("Attempting to recover failed messages", count=len(failed_messages))

            for failed_msg in failed_messages:
                try:
                    # Attempt to reprocess
                    result = await retry_manager.retry_with_backoff(
                        message_processor._process_single_message,
                        failed_msg.gmail_message_id,
                        max_retries=1,
                    )

                    if result.get("success"):
                        # Delete the failed message record
                        async with get_db_session() as db:
                            await db.delete(failed_msg)
                            await db.commit()

                        logger.info(
                            "Successfully recovered failed message",
                            message_id=failed_msg.gmail_message_id,
                        )
                    else:
                        # Update retry count
                        async with get_db_session() as db:
                            failed_msg.retry_count += 1
                            failed_msg.last_attempt_at = datetime.utcnow()
                            await db.commit()

                except Exception as e:
                    logger.error(
                        "Failed to recover message",
                        message_id=failed_msg.gmail_message_id,
                        error=str(e),
                    )

                    # Update retry count
                    async with get_db_session() as db:
                        failed_msg.retry_count += 1
                        failed_msg.last_attempt_at = datetime.utcnow()
                        await db.commit()

        except Exception as e:
            logger.error("Failed to recover messages", error=str(e))


def circuit_breaker(threshold: int = 5, timeout: float = 60.0):
    """Circuit breaker decorator for preventing cascading failures."""
    def decorator(func):
        if not asyncio.iscoroutinefunction(func):
            raise ValueError("Circuit breaker can only be applied to async functions")

        # Circuit breaker state
        state = {
            "failure_count": 0,
            "last_failure": None,
            "state": "closed",  # closed, open, half-open
        }

        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Check if circuit is open
            if state["state"] == "open":
                if datetime.utcnow().timestamp() - state["last_failure"] > timeout:
                    state["state"] = "half-open"
                    logger.info("Circuit breaker entering half-open state", func=func.__name__)
                else:
                    raise Exception("Circuit breaker is open")

            try:
                result = await func(*args, **kwargs)

                # Reset on success
                if state["state"] == "half-open":
                    state["state"] = "closed"
                    logger.info("Circuit breaker closed", func=func.__name__)

                state["failure_count"] = 0
                return result

            except Exception as e:
                state["failure_count"] += 1
                state["last_failure"] = datetime.utcnow().timestamp()

                if state["failure_count"] >= threshold:
                    state["state"] = "open"
                    logger.warning(
                        "Circuit breaker opened",
                        func=func.__name__,
                        failure_count=state["failure_count"],
                    )

                raise

        return wrapper
    return decorator


# Global managers
retry_manager = RetryManager()
watch_manager = WatchManager()
failure_recovery_manager = FailureRecoveryManager()