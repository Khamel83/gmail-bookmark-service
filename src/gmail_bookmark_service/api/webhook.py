"""Webhook endpoints for Gmail push notifications."""

import asyncio
from datetime import datetime
from typing import Dict

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

import structlog

from ..processing.pubsub_manager import pubsub_manager
from ..processing.message_processor import message_processor
from ..settings import settings

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.post("/webhook/pubsub")
async def pubsub_webhook(request: Request) -> Response:
    """Handle Pub/Sub push notifications for Gmail."""
    try:
        # Get request body
        body = await request.body()
        headers = dict(request.headers)

        # Log incoming webhook
        logger.info(
            "Received Pub/Sub webhook",
            content_type=headers.get("content-type"),
            message_type=headers.get("message-type"),
            content_length=len(body),
        )

        # Verify webhook signature (basic check)
        if not await pubsub_manager.verify_webhook_signature(headers, body):
            logger.warning("Invalid webhook signature")
            raise HTTPException(status_code=401, detail="Invalid signature")

        # Parse the message
        try:
            message_data = pubsub_manager.parse_webhook_message(body)
        except Exception as e:
            logger.error("Failed to parse webhook message", error=str(e))
            # Still return 200 to Pub/Sub to avoid retries
            return Response(status_code=status.HTTP_200_OK)

        # Queue for async processing
        asyncio.create_task(
            process_gmail_notification(message_data)
        )

        logger.info(
            "Webhook queued for processing",
            message_id=message_data.get("message_id"),
            history_id=message_data.get("history_id"),
        )

        # Return 200 immediately to Pub/Sub
        return Response(status_code=status.HTTP_200_OK)

    except Exception as e:
        logger.error("Unexpected error in webhook handler", error=str(e))
        # Still return 200 to avoid Pub/Sub retries
        return Response(status_code=status.HTTP_200_OK)


async def process_gmail_notification(message_data: Dict) -> None:
    """Process Gmail notification in background."""
    try:
        logger.info(
            "Processing Gmail notification",
            message_id=message_data.get("message_id"),
            history_id=message_data.get("history_id"),
        )

        # Process the message
        result = await message_processor.process_notification(message_data)

        if result.get("success"):
            logger.info(
                "Gmail notification processed successfully",
                message_id=message_data.get("message_id"),
                bookmarks_created=result.get("bookmarks_created", 0),
            )
        else:
            logger.error(
                "Failed to process Gmail notification",
                message_id=message_data.get("message_id"),
                error=result.get("error"),
            )

    except Exception as e:
        logger.error(
            "Unexpected error processing Gmail notification",
            message_id=message_data.get("message_id"),
            error=str(e),
        )


@router.post("/webhook/test")
async def test_webhook(request: Request) -> JSONResponse:
    """Test endpoint for webhook connectivity."""
    try:
        body = await request.json()
        logger.info("Test webhook received", data=body)

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "ok",
                "timestamp": datetime.utcnow().isoformat(),
                "received": body,
            },
        )
    except Exception as e:
        logger.error("Test webhook error", error=str(e))
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"status": "error", "error": str(e)},
        )


@router.get("/webhook/health")
async def webhook_health() -> JSONResponse:
    """Health check endpoint for webhook service."""
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "service": "gmail-bookmark-service",
        },
    )