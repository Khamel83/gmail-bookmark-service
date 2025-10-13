"""GCP Pub/Sub management for Gmail push notifications."""

import base64
import hashlib
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from google.cloud import pubsub_v1
from googleapiclient.errors import HttpError

import structlog

from ..auth.gmail_auth import auth_manager
from ..database import get_db_session
from ..database.models import ProcessingState
from ..settings import settings

logger = structlog.get_logger(__name__)


class PubSubManager:
    """Manages GCP Pub/Sub topics and Gmail watch setup."""

    def __init__(self):
        self.project_id = settings.gcp_project_id
        self.topic_name = settings.pubsub_topic
        self.subscription_name = settings.pubsub_subscription
        self.publisher = pubsub_v1.PublisherClient()
        self.subscriber = pubsub_v1.SubscriberClient()

    def get_topic_path(self) -> str:
        """Get full Pub/Sub topic path."""
        return self.publisher.topic_path(self.project_id, self.topic_name)

    def get_subscription_path(self) -> str:
        """Get full Pub/Sub subscription path."""
        return self.subscriber.subscription_path(self.project_id, self.subscription_name)

    async def setup_topic_and_subscription(self, webhook_url: str) -> bool:
        """Set up Pub/Sub topic and push subscription."""
        try:
            topic_path = self.get_topic_path()

            # Create topic if it doesn't exist
            try:
                self.publisher.create_topic(request={"name": topic_path})
                logger.info("Created Pub/Sub topic", topic=topic_path)
            except Exception as e:
                if "already exists" not in str(e):
                    raise
                logger.info("Pub/Sub topic already exists", topic=topic_path)

            # Create push subscription
            subscription_path = self.get_subscription_path()
            push_config = {
                "push_endpoint": webhook_url,
                "oidc_token": {
                    "service_account_email": None,  # Use default
                    "audience": webhook_url,
                },
                "attributes": {},
            }

            try:
                self.subscriber.create_subscription(
                    request={
                        "name": subscription_path,
                        "topic": topic_path,
                        "push_config": push_config,
                    }
                )
                logger.info("Created push subscription", subscription=subscription_path, webhook_url=webhook_url)
            except Exception as e:
                if "already exists" not in str(e):
                    raise
                logger.info("Push subscription already exists", subscription=subscription_path)

            return True

        except Exception as e:
            logger.error("Failed to setup Pub/Sub topic and subscription", error=str(e))
            return False

    async def start_gmail_watch(self, webhook_url: str) -> Dict:
        """Start Gmail watch for push notifications."""
        try:
            service = await auth_manager.get_service()

            # Set up watch request
            watch_request = {
                "topicName": f"projects/{self.project_id}/topics/{self.topic_name}",
                "labelIds": ["INBOX"],
            }

            # Add label filter if specified
            if settings.gmail_watch_label:
                # Get label ID for the specified label
                labels_response = service.users().labels().list(userId="me").execute()
                label_id = None
                for label in labels_response.get("labels", []):
                    if label["name"] == settings.gmail_watch_label:
                        label_id = label["id"]
                        break

                if label_id:
                    watch_request["labelIds"] = [label_id]
                    logger.info("Using label filter", label=settings.gmail_watch_label, label_id=label_id)
                else:
                    logger.warning("Label not found, watching entire inbox", label=settings.gmail_watch_label)

            # Start the watch
            watch_response = service.users().watch(userId="me", body=watch_request).execute()

            # Store watch state
            history_id = watch_response.get("historyId")
            expiration = datetime.fromisoformat(
                watch_response.get("expiration").replace("Z", "+00:00")
            )

            async with get_db_session() as db:
                await self._save_watch_state(db, history_id, expiration)

            logger.info(
                "Gmail watch started",
                history_id=history_id,
                expiration=expiration,
                webhook_url=webhook_url,
            )

            return {
                "success": True,
                "history_id": history_id,
                "expiration": expiration.isoformat(),
                "webhook_url": webhook_url,
            }

        except HttpError as e:
            logger.error("Failed to start Gmail watch", error=str(e), error_code=e.resp.status)
            return {
                "success": False,
                "error": str(e),
                "error_code": e.resp.status,
            }
        except Exception as e:
            logger.error("Unexpected error starting Gmail watch", error=str(e))
            return {
                "success": False,
                "error": str(e),
            }

    async def stop_gmail_watch(self) -> bool:
        """Stop Gmail watch notifications."""
        try:
            service = await auth_manager.get_service()
            service.users().stop(userId="me").execute()

            # Clear watch state
            async with get_db_session() as db:
                await self._save_watch_state(db, None, None)

            logger.info("Gmail watch stopped")
            return True

        except HttpError as e:
            logger.error("Failed to stop Gmail watch", error=str(e))
            return False
        except Exception as e:
            logger.error("Unexpected error stopping Gmail watch", error=str(e))
            return False

    async def renew_watch_if_needed(self, webhook_url: str) -> Dict:
        """Check and renew Gmail watch if it's about to expire."""
        try:
            async with get_db_session() as db:
                state = await self._get_watch_state(db)

            if not state or not state.get("expiration"):
                logger.info("No active watch found, starting new watch")
                return await self.start_gmail_watch(webhook_url)

            expiration = datetime.fromisoformat(state["expiration"])
            now = datetime.utcnow()

            # Renew if expires in next 24 hours
            if expiration - now < timedelta(hours=24):
                logger.info("Watch expires soon, renewing", expiration=expiration)
                return await self.start_gmail_watch(webhook_url)

            logger.info("Watch is still active", expiration=expiration)
            return {
                "success": True,
                "action": "no_action_needed",
                "expiration": expiration.isoformat(),
            }

        except Exception as e:
            logger.error("Failed to check/renew watch", error=str(e))
            return {
                "success": False,
                "error": str(e),
            }

    async def verify_webhook_signature(self, headers: Dict, body: bytes) -> bool:
        """Verify Pub/Sub webhook signature if configured."""
        # For now, just check basic headers
        # In production, implement proper signature verification
        return (
            "content-type" in headers
            and "message-type" in headers
            and headers.get("content-type", "").startswith("application/json")
        )

    def parse_webhook_message(self, body: bytes) -> Dict:
        """Parse incoming Pub/Sub webhook message."""
        try:
            message_data = json.loads(body.decode("utf-8"))

            if "message" not in message_data:
                raise ValueError("No message field in webhook data")

            message = message_data["message"]
            data = base64.b64decode(message["data"]).decode("utf-8")
            notification = json.loads(data)

            return {
                "email_address": message_data.get("emailAddress"),
                "history_id": notification.get("historyId"),
                "message_id": notification.get("messageId"),
                "raw_data": notification,
            }

        except Exception as e:
            logger.error("Failed to parse webhook message", error=str(e))
            raise

    async def _save_watch_state(self, db, history_id: Optional[str], expiration: Optional[datetime]) -> None:
        """Save Gmail watch state to database."""
        from sqlalchemy import insert, update

        if history_id and expiration:
            await db.execute(
                insert(ProcessingState)
                .values(
                    key="gmail_watch",
                    value=json.dumps({
                        "history_id": history_id,
                        "expiration": expiration.isoformat(),
                    }),
                )
                .on_conflict_do_update(
                    index_elements=["key"],
                    set_={
                        "value": json.dumps({
                            "history_id": history_id,
                            "expiration": expiration.isoformat(),
                        }),
                        "updated_at": datetime.utcnow(),
                    },
                )
            )
        else:
            # Clear watch state
            await db.execute(
                update(ProcessingState)
                .where(ProcessingState.key == "gmail_watch")
                .values(value="", updated_at=datetime.utcnow())
            )

    async def _get_watch_state(self, db) -> Optional[Dict]:
        """Get Gmail watch state from database."""
        from sqlalchemy import select

        result = await db.execute(
            select(ProcessingState).where(ProcessingState.key == "gmail_watch")
        )
        state = result.scalar_one_or_none()

        if state and state.value:
            try:
                return json.loads(state.value)
            except json.JSONDecodeError:
                pass

        return None


# Global Pub/Sub manager instance
pubsub_manager = PubSubManager()