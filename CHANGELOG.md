# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2025-01-13

### Added
- **Gmail OAuth2 Authentication** with auto-refresh token management
- **Real-time Processing** via Gmail Push Notifications and GCP Pub/Sub
- **HTTPS Webhook Endpoint** for receiving Pub/Sub notifications
- **Message Processing** for extracting URLs and attachments from Gmail
- **SQLite Database** with comprehensive bookmark and state management
- **Reliability Features** including:
  - Exponential backoff retry logic
  - Circuit breaker pattern implementation
  - Automatic failure recovery
  - Daily catch-up scanning for missed messages
- **Health Monitoring** with comprehensive endpoints
- **Structured Logging** with JSON support for production
- **Metrics Collection** for service monitoring
- **Production Deployment** with systemd unit file
- **Security Features**:
  - SSL/TLS support with self-signed certificate generation
  - Webhook signature verification
  - Secure token storage
- **Background Services**:
  - Gmail watch renewal (7-day expiry handling)
  - Failed message recovery
  - Daily message scanning

### Features
- **URL Extraction**: Automatically extracts all URLs from message content and HTML
- **Attachment Download**: Downloads and stores attachments up to 25MB
- **Deduplication**: Message hash-based duplicate detection
- **Multi-format Support**: Handles both plain text and HTML email content
- **Configurable Processing**: Adjustable worker count and processing limits
- **Comprehensive API**: Health checks, metrics, and management endpoints

### Documentation
- Complete README with quick start guide
- Detailed deployment guide for production
- API documentation
- Security and troubleshooting guides

### Architecture
- **Modular Design**: Clean separation of concerns
- **Async Processing**: Non-blocking message processing
- **Database Models**: SQLAlchemy with async support
- **FastAPI**: Modern Python web framework
- **Type Hints**: Full type annotation support

## Development Notes

### Requirements
- Python 3.9+
- Gmail API access
- GCP Project with Pub/Sub enabled
- OCI VM or similar hosting environment

### Security Considerations
- OAuth2 credentials stored securely
- HTTPS enforced in production
- Attachment size limits enforced
- Input validation and sanitization

### Performance Features
- Connection pooling
- Async database operations
- Background processing queues
- Efficient resource management