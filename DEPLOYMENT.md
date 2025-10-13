# Deployment Guide

This guide covers production deployment of the Gmail Bookmark Service on an OCI VM.

## Prerequisites

- OCI VM with Ubuntu 20.04+ or CentOS 8+
- Domain name pointing to VM
- SSL certificate (Let's Encrypt recommended)
- Google Cloud Console access

## Step 1: Server Setup

### Basic System Configuration

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install required packages
sudo apt install -y python3 python3-pip python3-venv nginx certbot

# Create service user
sudo useradd --system --create-home --shell /bin/bash gmail-service
```

### Firewall Configuration

```bash
# Configure UFW (Ubuntu)
sudo ufw allow ssh
sudo ufw allow 80
sudo ufw allow 443
sudo ufw --force enable

# Or configure iptables directly
sudo iptables -A INPUT -p tcp --dport 22 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 80 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 443 -j ACCEPT
```

## Step 2: Service Installation

### Deploy Application

```bash
# Create application directory
sudo mkdir -p /opt/gmail-bookmark-service
cd /tmp

# Copy service files (replace with your deployment method)
sudo cp -r gmail-bookmark-service/* /opt/gmail-bookmark-service/
sudo chown -R gmail-service:gmail-service /opt/gmail-bookmark-service

# Set up Python environment
sudo -u gmail-service python3 -m venv /opt/gmail-bookmark-service/venv
sudo -u gmail-service /opt/gmail-bookmark-service/venv/bin/pip install --upgrade pip

# Install dependencies
sudo -u gmail-service /opt/gmail-bookmark-service/venv/bin/pip install -e /opt/gmail-bookmark-service/

# Create data directories
sudo -u gmail-service mkdir -p /opt/gmail-bookmark-service/data/{logs,ssl,attachments}
```

### Configure Environment

```bash
# Create production environment file
sudo tee /opt/gmail-bookmark-service/.env > /dev/null << 'EOF'
# Gmail API Configuration
GMAIL_CREDENTIALS_PATH=/opt/gmail-bookmark-service/config/gmail_credentials.json
GMAIL_TOKEN_PATH=/opt/gmail-bookmark-service/data/gmail_token.json

# GCP Configuration
GCP_PROJECT_ID=your-gcp-project-id
PUBSUB_TOPIC=gmail-notifications
PUBSUB_SUBSCRIPTION=gmail-push-subscription

# Service Configuration
WEBHOOK_HOST=127.0.0.1
WEBHOOK_PORT=8443
DATA_DIRECTORY=/opt/gmail-bookmark-service/data

# Security
WEBHOOK_SECRET=$(openssl rand -hex 32)

# Production Settings
ENVIRONMENT=production
JSON_LOGS=true
LOG_LEVEL=INFO
EOF

# Set proper permissions
sudo chown gmail-service:gmail-service /opt/gmail-bookmark-service/.env
sudo chmod 600 /opt/gmail-bookmark-service/.env
```

## Step 3: SSL Certificate Setup

### Let's Encrypt Certificate

```bash
# Stop any services using port 80/443
sudo systemctl stop nginx || true

# Get certificate (replace with your domain)
sudo certbot certonly --standalone -d your-domain.com

# Copy certificates to service directory
sudo mkdir -p /opt/gmail-bookmark-service/data/ssl
sudo cp /etc/letsencrypt/live/your-domain.com/fullchain.pem /opt/gmail-bookmark-service/data/ssl/cert.pem
sudo cp /etc/letsencrypt/live/your-domain.com/privkey.pem /opt/gmail-bookmark-service/data/ssl/key.pem

# Set permissions
sudo chown gmail-service:gmail-service /opt/gmail-bookmark-service/data/ssl/*
sudo chmod 600 /opt/gmail-bookmark-service/data/ssl/key.pem
```

### Auto-renewal Setup

```bash
# Add renewal hook to copy certificates
sudo tee /etc/letsencrypt/renewal-hooks/deploy/gmail-bookmark-service > /dev/null << 'EOF'
#!/bin/bash
cp /etc/letsencrypt/live/$RENEWED_DOMAIN/fullchain.pem /opt/gmail-bookmark-service/data/ssl/cert.pem
cp /etc/letsencrypt/live/$RENEWED_DOMAIN/privkey.pem /opt/gmail-bookmark-service/data/ssl/key.pem
chown gmail-service:gmail-service /opt/gmail-bookmark-service/data/ssl/*
systemctl restart gmail-bookmark-service
EOF

sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/gmail-bookmark-service
```

## Step 4: Nginx Reverse Proxy

### Nginx Configuration

```bash
sudo tee /etc/nginx/sites-available/gmail-bookmark-service > /dev/null << 'EOF'
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    # SSL Configuration
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512:ECDHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;

    # Security Headers
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload";

    # Proxy to Gmail service
    location / {
        proxy_pass https://127.0.0.1:8443;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support (if needed)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # Health check endpoint (no auth)
    location /health {
        access_log off;
        proxy_pass https://127.0.0.1:8443/api/v1/health/simple;
    }
}
EOF

# Enable site
sudo ln -s /etc/nginx/sites-available/gmail-bookmark-service /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default

# Test configuration
sudo nginx -t

# Restart Nginx
sudo systemctl restart nginx
sudo systemctl enable nginx
```

## Step 5: Systemd Service

### Install Service

```bash
# Copy service file
sudo cp /opt/gmail-bookmark-service/gmail-bookmark-service.service /etc/systemd/system/

# Modify service file for your paths
sudo sed -i 's|/opt/gmail-bookmark-service|/opt/gmail-bookmark-service|g' /etc/systemd/system/gmail-bookmark-service.service

# Reload systemd
sudo systemctl daemon-reload

# Enable and start service
sudo systemctl enable gmail-bookmark-service
sudo systemctl start gmail-bookmark-service
```

### Service Management

```bash
# Check status
sudo systemctl status gmail-bookmark-service

# View logs
sudo journalctl -u gmail-bookmark-service -f

# Restart service
sudo systemctl restart gmail-bookmark-service

# Stop service
sudo systemctl stop gmail-bookmark-service
```

## Step 6: Gmail API Setup

### Create OAuth2 Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Select your project
3. Navigate to "APIs & Services" → "Credentials"
4. Click "Create Credentials" → "OAuth client ID"
5. Select "Desktop app" as application type
6. Download the JSON file

### Deploy Credentials

```bash
# Create config directory
sudo mkdir -p /opt/gmail-bookmark-service/config

# Upload credentials file (secure method)
sudo -u gmail-service scp user@source:/path/to/credentials.json /opt/gmail-bookmark-service/config/gmail_credentials.json

# Set permissions
sudo chown gmail-service:gmail-service /opt/gmail-bookmark-service/config/gmail_credentials.json
sudo chmod 600 /opt/gmail-bookmark-service/config/gmail_credentials.json
```

### Initial Authentication

```bash
# Switch to service user
sudo -u gmail-service -i

# Run service once to trigger OAuth flow
cd /opt/gmail-bookmark-service
source venv/bin/activate
python -m gmail_bookmark_service.main

# Follow the browser authentication flow
# This will create the gmail_token.json file
```

## Step 7: GCP Pub/Sub Configuration

### Update Webhook URL

```bash
# Update Pub/Sub subscription with your domain
gcloud pubsub subscriptions update gmail-push-subscription \
    --push-endpoint=https://your-domain.com/webhook/pubsub \
    --ack-deadline=600 \
    --project=your-gcp-project-id
```

## Step 8: Monitoring and Maintenance

### Log Rotation

```bash
sudo tee /etc/logrotate.d/gmail-bookmark-service > /dev/null << 'EOF'
/opt/gmail-bookmark-service/data/logs/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 644 gmail-service gmail-service
    postrotate
        systemctl reload gmail-bookmark-service || true
    endscript
}
EOF
```

### Health Monitoring

```bash
# Create monitoring script
sudo tee /opt/gmail-bookmark-service/monitor.sh > /dev/null << 'EOF'
#!/bin/bash

# Health check endpoint
HEALTH_URL="https://your-domain.com/health"

# Check service health
response=$(curl -s -o /dev/null -w "%{http_code}" $HEALTH_URL)

if [ $response != "200" ]; then
    echo "$(date): Service unhealthy (HTTP $response)"
    # Send alert or restart service
    systemctl restart gmail-bookmark-service
fi
EOF

sudo chmod +x /opt/gmail-bookmark-service/monitor.sh

# Add to crontab (every 5 minutes)
sudo -u gmail-service crontab -l | { cat; echo "*/5 * * * * /opt/gmail-bookmark-service/monitor.sh"; } | sudo -u gmail-service crontab -
```

## Step 9: Backup Configuration

### Database Backup

```bash
# Create backup script
sudo tee /opt/gmail-bookmark-service/backup.sh > /dev/null << 'EOF'
#!/bin/bash

BACKUP_DIR="/opt/gmail-bookmark-service/backups"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

# Backup database
cp /opt/gmail-bookmark-service/data/bookmarks.db $BACKUP_DIR/bookmarks_$DATE.db

# Backup configuration
tar -czf $BACKUP_DIR/config_$DATE.tar.gz \
    /opt/gmail-bookmark-service/.env \
    /opt/gmail-bookmark-service/config/ \
    /opt/gmail-bookmark-service/data/gmail_token.json

# Keep only last 30 days
find $BACKUP_DIR -name "*.db" -mtime +30 -delete
find $BACKUP_DIR -name "*.tar.gz" -mtime +30 -delete
EOF

sudo chmod +x /opt/gmail-bookmark-service/backup.sh

# Add to crontab (daily at 2 AM)
sudo -u gmail-service crontab -l | { cat; echo "0 2 * * * /opt/gmail-bookmark-service/backup.sh"; } | sudo -u gmail-service crontab -
```

## Troubleshooting

### Service Won't Start

```bash
# Check logs
sudo journalctl -u gmail-bookmark-service -n 50

# Check configuration
sudo -u gmail-service /opt/gmail-bookmark-service/venv/bin/python -c "from gmail_bookmark_service.settings import settings; print(settings.dict())"

# Test database
sudo -u gmail-service /opt/gmail-bookmark-service/venv/bin/python -c "import asyncio; from gmail_bookmark_service.database import init_database; asyncio.run(init_database())"
```

### Gmail API Issues

```bash
# Test authentication
sudo -u gmail-service /opt/gmail-bookmark-service/venv/bin/python -c "
import asyncio
from gmail_bookmark_service.auth.gmail_auth import auth_manager
result = asyncio.run(auth_manager.test_connection())
print(result)
"
```

### Pub/Sub Issues

```bash
# Check subscription status
gcloud pubsub subscriptions describe gmail-push-subscription --project=your-gcp-project-id

# Test topic
gcloud pubsub topics publish gmail-notifications --message 'test' --project=your-gcp-project-id
```

## Security Hardening

### Additional Security Measures

```bash
# Install fail2ban
sudo apt install -y fail2ban

# Configure fail2ban for Nginx
sudo tee /etc/fail2ban/jail.local > /dev/null << 'EOF'
[nginx-http-auth]
enabled = true
filter = nginx-http-auth
logpath = /var/log/nginx/error.log
maxretry = 3
bantime = 3600

[nginx-limit-req]
enabled = true
filter = nginx-limit-req
logpath = /var/log/nginx/error.log
maxretry = 10
bantime = 600
EOF

sudo systemctl restart fail2ban

# Set up automatic security updates
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

This deployment guide provides a production-ready setup with proper security, monitoring, and maintenance procedures.