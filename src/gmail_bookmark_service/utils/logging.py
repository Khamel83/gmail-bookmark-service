"""Logging configuration and monitoring for Gmail bookmark service."""

import logging
import logging.handlers
import os
import sys
from datetime import datetime
from typing import Any, Dict

import structlog
from structlog.stdlib import LoggerFactory

from ..settings import settings


def setup_logging() -> None:
    """Configure structured logging for the service."""
    # Ensure log directory exists
    log_dir = os.path.join(settings.data_directory, "logs")
    os.makedirs(log_dir, exist_ok=True)

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer() if _should_use_json_logs() else structlog.dev.ConsoleRenderer(),
        ],
        context_class=dict,
        logger_factory=LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level.upper()),
    )

    # Add file handler for logs
    log_file = os.path.join(log_dir, "gmail_bookmark_service.log")
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=50 * 1024 * 1024,  # 50MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(getattr(logging, settings.log_level.upper()))

    # Create formatter for file logs (always JSON)
    file_formatter = logging.Formatter("%(message)s")
    file_handler.setFormatter(file_formatter)

    # Add file handler to root logger
    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)

    # Set specific log levels for noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)
    logging.getLogger("googleapiclient").setLevel(logging.WARNING)

    # Log startup info
    logger = structlog.get_logger(__name__)
    logger.info(
        "Logging initialized",
        log_level=settings.log_level,
        log_file=log_file,
        json_logs=_should_use_json_logs(),
    )


def _should_use_json_logs() -> bool:
    """Determine if JSON logs should be used based on environment."""
    # Use JSON logs in production or if explicitly requested
    return (
        os.getenv("ENVIRONMENT", "development").lower() == "production"
        or os.getenv("JSON_LOGS", "false").lower() == "true"
    )


class MetricsCollector:
    """Collects and stores service metrics."""

    def __init__(self):
        self.reset_metrics()

    def reset_metrics(self) -> None:
        """Reset all metrics to zero."""
        self.metrics = {
            "webhook_requests_total": 0,
            "webhook_requests_success": 0,
            "webhook_requests_error": 0,
            "messages_processed_total": 0,
            "messages_processed_success": 0,
            "messages_processed_error": 0,
            "bookmarks_created_total": 0,
            "attachments_downloaded_total": 0,
            "urls_extracted_total": 0,
            "gmail_api_calls_total": 0,
            "gmail_api_calls_success": 0,
            "gmail_api_calls_error": 0,
            "pubsub_messages_total": 0,
            "processing_errors_total": 0,
            "auth_failures_total": 0,
            "circuit_breaker_activations": 0,
        }

    def increment(self, metric_name: str, value: int = 1) -> None:
        """Increment a metric by the given value."""
        if metric_name in self.metrics:
            self.metrics[metric_name] += value
        else:
            self.metrics[metric_name] = value

    def set(self, metric_name: str, value: Any) -> None:
        """Set a metric to a specific value."""
        self.metrics[metric_name] = value

    def get_all(self) -> Dict[str, Any]:
        """Get all current metrics."""
        # Add timestamp and service info
        metrics = {
            **self.metrics,
            "timestamp": datetime.utcnow().isoformat(),
            "service": "gmail-bookmark-service",
            "version": "1.0.0",
        }
        return metrics

    def get_formatted_stats(self) -> str:
        """Get formatted statistics string."""
        total_requests = self.metrics.get("webhook_requests_total", 0)
        success_rate = (
            (self.metrics.get("webhook_requests_success", 0) / total_requests * 100)
            if total_requests > 0 else 0
        )

        total_messages = self.metrics.get("messages_processed_total", 0)
        message_success_rate = (
            (self.metrics.get("messages_processed_success", 0) / total_messages * 100)
            if total_messages > 0 else 0
        )

        return (
            f"Webhook Requests: {total_requests} ({success_rate:.1f}% success) | "
            f"Messages: {total_messages} ({message_success_rate:.1f}% success) | "
            f"Bookmarks: {self.metrics.get('bookmarks_created_total', 0)} | "
            f"Attachments: {self.metrics.get('attachments_downloaded_total', 0)} | "
            f"URLs: {self.metrics.get('urls_extracted_total', 0)}"
        )


# Global metrics collector
metrics = MetricsCollector()


class MonitoringMixin:
    """Mixin to add monitoring capabilities to classes."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = structlog.get_logger(self.__class__.__name__)

    def _log_metric(self, metric_name: str, value: int = 1, **kwargs) -> None:
        """Log a metric increment."""
        metrics.increment(metric_name, value)
        self.logger.info(
            "Metric recorded",
            metric=metric_name,
            value=value,
            **kwargs
        )

    def _log_operation_start(self, operation: str, **kwargs) -> None:
        """Log the start of an operation."""
        self.logger.info(
            "Operation started",
            operation=operation,
            **kwargs
        )

    def _log_operation_success(self, operation: str, **kwargs) -> None:
        """Log successful operation completion."""
        self.logger.info(
            "Operation completed successfully",
            operation=operation,
            **kwargs
        )

    def _log_operation_error(self, operation: str, error: Exception, **kwargs) -> None:
        """Log operation error."""
        self.logger.error(
            "Operation failed",
            operation=operation,
            error=str(error),
            error_type=type(error).__name__,
            **kwargs
        )
        metrics.increment("processing_errors_total")


class RequestLogger:
    """Middleware for logging HTTP requests."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        """ASGI middleware for request logging."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        logger = structlog.get_logger("http_request")

        start_time = datetime.utcnow()

        # Process request
        try:
            await self.app(scope, receive, send)
        except Exception as e:
            logger.error(
                "Request failed",
                method=scope.get("method"),
                path=scope.get("path"),
                error=str(e),
            )
            metrics.increment("webhook_requests_error")
            raise
        else:
            duration = (datetime.utcnow() - start_time).total_seconds()

            logger.info(
                "Request completed",
                method=scope.get("method"),
                path=scope.get("path"),
                duration_seconds=duration,
            )
            metrics.increment("webhook_requests_success")

        metrics.increment("webhook_requests_total")