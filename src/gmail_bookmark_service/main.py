"""Main application entry point for Gmail bookmark service."""

import asyncio
import os
import signal
import sys
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Dict

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import structlog

from .settings import settings
from .database import init_database
from .api import webhook_router, health_router
from .utils.logging import setup_logging, metrics, RequestLogger
from .utils.reliability import watch_manager, failure_recovery_manager

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management."""
    # Startup
    logger.info("Starting Gmail bookmark service")

    # Setup logging
    setup_logging()

    # Initialize database
    try:
        await init_database()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error("Failed to initialize database", error=str(e))
        sys.exit(1)

    # Start background services
    webhook_url = f"https://localhost:{settings.webhook_port}/webhook/pubsub"

    # Start watch manager
    try:
        await watch_manager.start(webhook_url)
        logger.info("Watch manager started")
    except Exception as e:
        logger.error("Failed to start watch manager", error=str(e))

    # Start failure recovery manager
    try:
        await failure_recovery_manager.start()
        logger.info("Failure recovery manager started")
    except Exception as e:
        logger.error("Failed to start failure recovery manager", error=str(e))

    logger.info("Gmail bookmark service started successfully")

    # Application running
    yield

    # Shutdown
    logger.info("Shutting down Gmail bookmark service")

    # Stop background services
    await watch_manager.stop()
    await failure_recovery_manager.stop()

    logger.info("Gmail bookmark service stopped")


# Create FastAPI application
app = FastAPI(
    title="Gmail Bookmark Service",
    description="Automated Gmail-to-bookmarking ingestion service with push notifications",
    version="1.0.0",
    lifespan=lifespan,
)

# Add middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add request logging middleware
app.add_middleware(RequestLogger)

# Include routers
app.include_router(webhook_router, prefix="/api/v1")
app.include_router(health_router, prefix="/api/v1")


@app.get("/")
async def root() -> JSONResponse:
    """Root endpoint."""
    return JSONResponse(
        content={
            "service": "Gmail Bookmark Service",
            "version": "1.0.0",
            "status": "running",
            "timestamp": metrics.get_all()["timestamp"],
        }
    )


@app.get("/metrics")
async def get_metrics() -> JSONResponse:
    """Get service metrics."""
    return JSONResponse(content=metrics.get_all())


@app.get("/stats")
async def get_stats() -> JSONResponse:
    """Get formatted statistics."""
    return JSONResponse(
        content={
            "stats": metrics.get_formatted_stats(),
            "metrics": metrics.get_all(),
        }
    )


class GracefulShutdown:
    """Handle graceful shutdown."""

    def __init__(self):
        self.shutdown = False

    def signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info("Received shutdown signal", signal=signum)
        self.shutdown = True


def create_ssl_context():
    """Create SSL context for HTTPS."""
    import ssl

    # For development, create self-signed certificate if it doesn't exist
    cert_dir = os.path.join(settings.data_directory, "ssl")
    os.makedirs(cert_dir, exist_ok=True)

    cert_file = os.path.join(cert_dir, "cert.pem")
    key_file = os.path.join(cert_dir, "key.pem")

    if not os.path.exists(cert_file) or not os.path.exists(key_file):
        logger.info("Creating self-signed SSL certificate for development")
        create_self_signed_cert(cert_file, key_file)

    # Create SSL context
    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_cert_chain(cert_file, key_file)

    return ssl_context


def create_self_signed_cert(cert_file: str, key_file: str):
    """Create a self-signed SSL certificate for development."""
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    import ipaddress

    # Generate private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # Create certificate
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "California"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "San Francisco"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Gmail Bookmark Service"),
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    ])

    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        private_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.utcnow()
    ).not_valid_after(
        datetime.utcnow() + timedelta(days=365)
    ).add_extension(
        x509.SubjectAlternativeName([
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            x509.IPAddress(ipaddress.IPv4Address("0.0.0.0")),
        ]),
        critical=False,
    ).sign(private_key, hashes.SHA256())

    # Write certificate and key to files
    with open(cert_file, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    with open(key_file, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ))

    logger.info("Self-signed certificate created", cert_file=cert_file, key_file=key_file)


async def main():
    """Main application entry point."""
    # Setup graceful shutdown
    shutdown_handler = GracefulShutdown()
    signal.signal(signal.SIGINT, shutdown_handler.signal_handler)
    signal.signal(signal.SIGTERM, shutdown_handler.signal_handler)

    # Create SSL context
    ssl_context = create_ssl_context()

    # Configure uvicorn
    config = uvicorn.Config(
        app=app,
        host=settings.webhook_host,
        port=settings.webhook_port,
        ssl_certfile=os.path.join(settings.data_directory, "ssl", "cert.pem"),
        ssl_keyfile=os.path.join(settings.data_directory, "ssl", "key.pem"),
        log_level=settings.log_level.lower(),
        access_log=True,
    )

    # Start server
    server = uvicorn.Server(config)

    # Run server
    try:
        await server.serve()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error("Server error", error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())