"""Message processing for extracting URLs and attachments from Gmail messages."""

import hashlib
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Set
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from googleapiclient.errors import HttpError

import structlog

from ..auth.gmail_auth import auth_manager
from ..database import get_db_session
from ..database.models import Bookmark, FailedMessage, ProcessingState
from ..settings import settings

logger = structlog.get_logger(__name__)


class MessageProcessor:
    """Processes Gmail messages to extract URLs and attachments."""

    def __init__(self):
        self.url_pattern = re.compile(
            r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
        )
        self.http_client = httpx.AsyncClient(timeout=30.0)

    async def process_notification(self, notification_data: Dict) -> Dict:
        """Process a Gmail notification."""
        try:
            history_id = notification_data.get("history_id")
            message_id = notification_data.get("message_id")

            if not history_id and not message_id:
                return {"success": False, "error": "No history_id or message_id in notification"}

            # Get the last processed history ID
            async with get_db_session() as db:
                last_history_id = await self._get_last_history_id(db)

            if history_id:
                return await self._process_history_update(history_id, last_history_id)
            elif message_id:
                return await self._process_single_message(message_id)
            else:
                return {"success": False, "error": "No valid identifiers in notification"}

        except Exception as e:
            logger.error("Failed to process notification", error=str(e))
            return {"success": False, "error": str(e)}

    async def _process_history_update(self, history_id: str, last_history_id: Optional[str]) -> Dict:
        """Process Gmail history to find new messages."""
        try:
            service = await auth_manager.get_service()

            # Get history list
            history_response = service.users().history().list(
                userId="me",
                startHistoryId=last_history_id,
                historyTypes=["messageAdded"],
            ).execute()

            histories = history_response.get("history", [])
            if not histories:
                logger.info("No new messages in history update", history_id=history_id)
                return {"success": True, "messages_processed": 0}

            # Extract message IDs from history
            message_ids = set()
            for history in histories:
                for message_added in history.get("messagesAdded", []):
                    message_id = message_added["message"]["id"]
                    message_ids.add(message_id)

            logger.info(
                "Processing messages from history",
                history_id=history_id,
                message_count=len(message_ids),
            )

            # Process each message
            processed_count = 0
            failed_count = 0

            for message_id in message_ids:
                result = await self._process_single_message(message_id)
                if result.get("success"):
                    processed_count += 1
                else:
                    failed_count += 1

            # Update last history ID
            async with get_db_session() as db:
                await self._save_last_history_id(db, history_id)

            return {
                "success": True,
                "messages_processed": processed_count,
                "messages_failed": failed_count,
                "history_id": history_id,
            }

        except HttpError as e:
            logger.error("Failed to get Gmail history", error=str(e))
            return {"success": False, "error": str(e)}

    async def _process_single_message(self, message_id: str) -> Dict:
        """Process a single Gmail message."""
        try:
            # Check if already processed
            async with get_db_session() as db:
                existing = await db.execute(
                    "SELECT id FROM bookmarks WHERE gmail_message_id = ?", (message_id,)
                )
                if existing.scalar_one_or_none():
                    logger.info("Message already processed", message_id=message_id)
                    return {"success": True, "action": "already_processed"}

            # Fetch message from Gmail API
            service = await auth_manager.get_service()
            message = service.users().messages().get(
                userId="me",
                id=message_id,
                format="full",
            ).execute()

            # Extract message data
            message_data = self._extract_message_data(message)

            # Create bookmark record
            async with get_db_session() as db:
                bookmark = Bookmark(**message_data)
                db.add(bookmark)
                await db.flush()

                # Download attachments
                if message_data.get("attachments"):
                    attachment_data = await self._download_attachments(
                        message, message_data["attachments"], bookmark.id
                    )
                    bookmark.attachments = attachment_data
                    bookmark.attachment_count = len(attachment_data)

                await db.commit()

            logger.info(
                "Message processed successfully",
                message_id=message_id,
                urls_found=len(message_data["urls"]),
                attachments=len(message_data["attachments"]),
            )

            return {"success": True, "bookmark_id": bookmark.id}

        except HttpError as e:
            logger.error("Failed to fetch Gmail message", message_id=message_id, error=str(e))
            await self._record_failed_message(message_id, "http_error", str(e))
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error("Failed to process message", message_id=message_id, error=str(e))
            await self._record_failed_message(message_id, "processing_error", str(e))
            return {"success": False, "error": str(e)}

    def _extract_message_data(self, message: Dict) -> Dict:
        """Extract data from Gmail message."""
        headers = {h["name"]: h["value"] for h in message["payload"].get("headers", [])}

        # Get sender info
        from_header = headers.get("From", "")
        sender_email = ""
        sender_name = ""
        if "<" in from_header:
            sender_name = from_header.split("<")[0].strip().strip('"')
            sender_email = from_header.split("<")[1].split(">")[0].strip()
        else:
            sender_email = from_header.strip()

        # Extract URLs from message content
        urls = set()
        content = self._extract_message_content(message["payload"])

        # Find URLs in text content
        urls.update(self.url_pattern.findall(content))

        # Find URLs in HTML content (more reliable)
        if "html" in content.lower():
            soup = BeautifulSoup(content, "html.parser")
            for link in soup.find_all("a", href=True):
                href = link["href"]
                if href.startswith(("http://", "https://")):
                    urls.add(href)

        # Extract attachment info
        attachments = []
        if "parts" in message["payload"]:
            for part in message["payload"]["parts"]:
                if part.get("filename"):
                    attachment_info = {
                        "filename": part["filename"],
                        "size": part.get("body", {}).get("size", 0),
                        "attachment_id": part.get("body", {}).get("attachmentId"),
                        "mime_type": part.get("mimeType", "application/octet-stream"),
                    }
                    if attachment_info["size"] <= settings.max_attachment_size:
                        attachments.append(attachment_info)

        # Create message hash for deduplication
        message_content = f"{headers.get('Subject', '')}{sender_email}{sorted(list(urls))}"
        message_hash = hashlib.sha256(message_content.encode()).hexdigest()

        # Get Gmail timestamp
        gmail_timestamp = datetime.fromtimestamp(int(message["internalDate"]) / 1000)

        return {
            "gmail_message_id": message["id"],
            "gmail_thread_id": message["threadId"],
            "subject": headers.get("Subject", ""),
            "sender_email": sender_email,
            "sender_name": sender_name,
            "urls": sorted(list(urls)),
            "url_count": len(urls),
            "attachments": attachments,
            "attachment_count": len(attachments),
            "snippet": message.get("snippet", ""),
            "gmail_timestamp": gmail_timestamp,
            "processing_status": "completed",
            "message_hash": message_hash,
            "labels": message.get("labelIds", []),
            "is_unread": "UNREAD" in message.get("labelIds", []),
        }

    def _extract_message_content(self, payload: Dict) -> str:
        """Extract text and HTML content from message payload."""
        content = ""

        if "parts" in payload:
            for part in payload["parts"]:
                if part["mimeType"].startswith("text/"):
                    if "data" in part["body"]:
                        import base64
                        content += base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="ignore")
                elif "parts" in part:
                    content += self._extract_message_content(part)
        elif "data" in payload.get("body", {}):
            import base64
            content = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")

        return content

    async def _download_attachments(self, message: Dict, attachment_infos: List[Dict], bookmark_id: int) -> List[Dict]:
        """Download attachments and save to disk."""
        downloaded_attachments = []
        service = await auth_manager.get_service()

        # Create attachments directory
        attachments_dir = os.path.join(settings.data_directory, "attachments", str(bookmark_id))
        os.makedirs(attachments_dir, exist_ok=True)

        for attachment_info in attachment_infos:
            try:
                attachment_id = attachment_info["attachment_id"]
                if not attachment_id:
                    continue

                # Download attachment
                attachment = service.users().messages().attachments().get(
                    userId="me",
                    messageId=message["id"],
                    id=attachment_id,
                ).execute()

                # Decode attachment data
                import base64
                data = base64.urlsafe_b64decode(attachment["data"])

                # Save to file
                file_path = os.path.join(attachments_dir, attachment_info["filename"])
                with open(file_path, "wb") as f:
                    f.write(data)

                downloaded_attachments.append({
                    "filename": attachment_info["filename"],
                    "file_path": file_path,
                    "size": len(data),
                    "mime_type": attachment_info["mime_type"],
                })

                logger.info(
                    "Attachment downloaded",
                    filename=attachment_info["filename"],
                    size=len(data),
                )

            except Exception as e:
                logger.error(
                    "Failed to download attachment",
                    filename=attachment_info["filename"],
                    error=str(e),
                )

        return downloaded_attachments

    async def _get_last_history_id(self, db) -> Optional[str]:
        """Get the last processed history ID from database."""
        from sqlalchemy import select

        result = await db.execute(
            select(ProcessingState).where(ProcessingState.key == "last_history_id")
        )
        state = result.scalar_one_or_none()
        return state.value if state else None

    async def _save_last_history_id(self, db, history_id: str) -> None:
        """Save the last processed history ID to database."""
        from sqlalchemy import insert, update

        await db.execute(
            insert(ProcessingState)
            .values(key="last_history_id", value=history_id)
            .on_conflict_do_update(
                index_elements=["key"],
                set_={"value": history_id, "updated_at": datetime.utcnow()},
            )
        )

    async def _record_failed_message(self, message_id: str, error_type: str, error_message: str) -> None:
        """Record a failed message for potential retry."""
        try:
            async with get_db_session() as db:
                from sqlalchemy import insert

                await db.execute(
                    insert(FailedMessage).values(
                        gmail_message_id=message_id,
                        error_message=error_message,
                        error_type=error_type,
                    )
                )
        except Exception as e:
            logger.error("Failed to record failed message", message_id=message_id, error=str(e))

    async def shutdown(self):
        """Cleanup resources."""
        await self.http_client.aclose()


# Global message processor instance
message_processor = MessageProcessor()