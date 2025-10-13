# Gmail Bookmark Service

A production-ready Python service that automatically extracts URLs and attachments from Gmail messages and stores them as bookmarks. Uses Gmail Push Notifications via GCP Pub/Sub for real-time processing.

## Features

- **Real-time Processing**: Gmail Push Notifications with Pub/Sub
- **OAuth2 Authentication**: Secure Gmail API access with auto-refresh
- **URL & Attachment Extraction**: Automatically extracts all URLs and downloads attachments
- **Reliable Processing**: Retry logic, circuit breakers, and failure recovery
- **Health Monitoring**: Comprehensive health checks and metrics
- **Production Ready**: Systemd support, structured logging, SSL termination
- **Deduplication**: Message hash-based duplicate detection
- **Auto-renewal**: Automatic Gmail watch renewal (7-day expiry)
- **Daily Catch-up**: Fallback scanning for missed messages

## Architecture

```
Gmail → Pub/Sub → Webhook → Message Processor → Database
                    ↓
            Background Services:
            - Watch Renewal
            - Failure Recovery
            - Daily Scan
```

## Quick Start

### Prerequisites

- Python 3.9+
- Gmail API access (Google Cloud Console)
- GCP Project with Pub/Sub enabled
- OCI VM or similar hosting environment

### 1. Gmail API Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create/select a project
3. Enable Gmail API and Pub/Sub API
4. Create OAuth2 credentials:
   - Go to "APIs & Services" → "Credentials"
   - "Create Credentials" → "OAuth client ID"
   - Application type: "Desktop app"
   - Download JSON as `gmail_credentials.json`

### 2. GCP Pub/Sub Setup

```bash
# Set your project ID
export PROJECT_ID="your-gcp-project-id"

# Create topic
gcloud pubsub topics create gmail-notifications --project=$PROJECT_ID

# Create push subscription (update URL later)
gcloud pubsub subscriptions create gmail-push-subscription \
    --topic=gmail-notifications \
    --push-endpoint=https://your-domain.com:8443/webhook/pubsub \
    --ack-deadline=600 \
    --project=$PROJECT_ID
```

### 3. Service Installation

```bash
# Clone or copy the service
git clone <repository> gmail-bookmark-service
cd gmail-bookmark-service

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -e .

# Create configuration
cp .env.example .env
# Edit .env with your settings

# Create data directories
mkdir -p data/{logs,ssl,attachments}

# Initialize database
python -m gmail_bookmark_service.database.connection
```

### 4. Configuration

Edit `.env` file:

```env
# Gmail API Configuration
GMAIL_CREDENTIALS_PATH=/path/to/gmail_credentials.json
GMAIL_TOKEN_PATH=data/gmail_token.json

# GCP Configuration
GCP_PROJECT_ID=your-gcp-project-id
PUBSUB_TOPIC=gmail-notifications
PUBSUB_SUBSCRIPTION=gmail-push-subscription

# Service Configuration
WEBHOOK_PORT=8443
WEBHOOK_HOST=0.0.0.0
DATA_DIRECTORY=data

# Security
WEBHOOK_SECRET=your-secret-key

# Production
ENVIRONMENT=production
JSON_LOGS=true
LOG_LEVEL=INFO
```

### 5. First Run

```bash
# Start the service (will trigger OAuth flow first time)
python -m gmail_bookmark_service.main

# Follow the OAuth authentication flow in your browser
```

## Production Deployment

### 1. System Setup

```bash
# Create service user
sudo useradd --system --home /opt/gmail-bookmark-service gmail-service

# Install service
sudo mkdir -p /opt/gmail-bookmark-service
sudo cp -r * /opt/gmail-bookmark-service/
sudo chown -R gmail-service:gmail-service /opt/gmail-bookmark-service

# Set up virtual environment
sudo -u gmail-service python3 -m venv /opt/gmail-bookmark-service/venv
sudo -u gmail-service /opt/gmail-bookmark-service/venv/bin/pip install -e /opt/gmail-bookmark-service

# Install systemd service
sudo cp gmail-bookmark-service.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable gmail-bookmark-service
```

### 2. SSL Certificate (Production)

Replace the self-signed certificate with proper certificates:

```bash
# Use Let's Encrypt or your organization's certificates
sudo cp your-cert.pem /opt/gmail-bookmark-service/data/ssl/cert.pem
sudo cp your-key.pem /opt/gmail-bookmark-service/data/ssl/key.pem
sudo chown gmail-service:gmail-service /opt/gmail-bookmark-service/data/ssl/*
```

### 3. Start Service

```bash
# Start the service
sudo systemctl start gmail-bookmark-service

# Check status
sudo systemctl status gmail-bookmark-service

# View logs
sudo journalctl -u gmail-bookmark-service -f
```

## API Endpoints

### Health Checks

- `GET /api/v1/health` - Comprehensive health check
- `GET /api/v1/health/simple` - Simple health check (for load balancers)

### Webhooks

- `POST /api/v1/webhook/pubsub` - Gmail push notifications endpoint
- `POST /api/v1/webhook/test` - Test endpoint

### Metrics

- `GET /metrics` - Raw metrics in JSON format
- `GET /stats` - Formatted statistics

## Database Schema

### Bookmarks Table

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| gmail_message_id | STRING | Gmail message ID (unique) |
| sender_email | STRING | Sender email address |
| urls | JSON | Array of extracted URLs |
| attachments | JSON | Attachment metadata |
| gmail_timestamp | DATETIME | Gmail message timestamp |
| processed_at | DATETIME | Processing timestamp |
| message_hash | STRING | Deduplication hash |

### Processing State

| Column | Type | Description |
|--------|------|-------------|
| key | STRING | State key (e.g., "last_history_id") |
| value | TEXT | State value |
| updated_at | DATETIME | Last update time |

## Monitoring

### Metrics Available

- Webhook request counts and success rates
- Message processing counts and success rates
- Gmail API call metrics
- Attachment download counts
- URL extraction counts
- Error counts by type

### Logging

Service uses structured logging with JSON output in production:

```bash
# View logs
sudo journalctl -u gmail-bookmark-service -f

# View specific log levels
sudo journalctl -u gmail-bookmark-service --priority=err
```

## Troubleshooting

### Common Issues

1. **OAuth Authentication Failed**
   - Check `gmail_credentials.json` path and validity
   - Verify Gmail API is enabled
   - Check network connectivity

2. **Pub/Sub Webhook Failing**
   - Verify webhook URL is accessible from GCP
   - Check SSL certificate validity
   - Confirm firewall allows port 8443

3. **No Messages Processing**
   - Check Gmail watch status: `curl http://localhost:8443/api/v1/health`
   - Verify Pub/Sub subscription is active
   - Check Gmail API permissions

4. **Database Errors**
   - Ensure data directory is writable
   - Check disk space
   - Verify SQLite file permissions

### Debug Mode

Set `LOG_LEVEL=DEBUG` in `.env` for detailed logging.

### Manual Testing

```bash
# Test webhook
curl -X POST https://your-domain:8443/api/v1/webhook/test \
  -H "Content-Type: application/json" \
  -d '{"test": true}'

# Check health
curl https://your-domain:8443/api/v1/health

# View metrics
curl https://your-domain:8443/metrics
```

## Security Considerations

- Store Gmail credentials securely
- Use HTTPS in production
- Implement proper firewall rules
- Regularly rotate secrets
- Monitor logs for unusual activity
- Limit attachment sizes and types

## Performance Tuning

- Adjust `PROCESSING_WORKERS` based on CPU cores
- Tune database connection pool if needed
- Monitor memory usage with large attachments
- Consider CDN for attachment serving

## License

This project is licensed under the MIT License - see the LICENSE file for details.