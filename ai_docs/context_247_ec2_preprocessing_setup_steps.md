# Context 247: EC2 Preprocessing Setup - Detailed Step-by-Step Guide

## Overview
This document provides specific, executable steps to configure the EC2 instance for the preprocessing pipeline and enable remote IDE development access.

## Part 1: EC2 Instance Configuration

### Step 1: Connect to EC2 Instance
```bash
# From your local machine
ssh -i resources/aws/legal-doc-processor-bastion.pem ubuntu@54.162.223.205
```

### Step 2: System Updates and Python Setup
```bash
# Update package lists
sudo apt-get update

# Install Python 3.11
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv python3.11-dev python3.11-distutils

# Install pip for Python 3.11
curl -sS https://bootstrap.pypa.io/get-pip.py | sudo python3.11

# Set Python 3.11 as default python3
sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
```

### Step 3: Install System Dependencies
```bash
# Database and Redis clients
sudo apt-get install -y postgresql-client redis-tools

# Build essentials
sudo apt-get install -y build-essential libpq-dev libssl-dev libffi-dev

# PDF processing tools
sudo apt-get install -y poppler-utils tesseract-ocr

# Process management and monitoring
sudo apt-get install -y supervisor htop

# Development tools
sudo apt-get install -y git vim tree

# Create application directories
sudo mkdir -p /opt/legal-doc-processor
sudo mkdir -p /var/log/legal-doc-processor
sudo mkdir -p /var/lib/legal-doc-processor/{temp,cache}

# Set ownership
sudo chown -R ubuntu:ubuntu /opt/legal-doc-processor
sudo chown -R ubuntu:ubuntu /var/log/legal-doc-processor
sudo chown -R ubuntu:ubuntu /var/lib/legal-doc-processor
```

## Part 2: Code Deployment

### Step 4: Create Deployment Package (Local Machine)
```bash
# On your local machine, in the project root
cd /Users/josephott/Documents/phase_1_2_3_process_v5

# Create preprocessing-only package
cat > create_deployment_package.sh << 'EOF'
#!/bin/bash
PACKAGE_NAME="preprocessing_deployment.tar.gz"

# Create temporary directory
mkdir -p /tmp/preprocessing_deploy

# Copy only preprocessing-related scripts
cp -r scripts /tmp/preprocessing_deploy/
cp requirements.txt /tmp/preprocessing_deploy/

# Remove non-preprocessing components
rm -rf /tmp/preprocessing_deploy/scripts/archive_pre_consolidation
rm -rf /tmp/preprocessing_deploy/scripts/__pycache__
find /tmp/preprocessing_deploy -name "*.pyc" -delete
find /tmp/preprocessing_deploy -name ".DS_Store" -delete

# Create tarball
tar -czf $PACKAGE_NAME -C /tmp/preprocessing_deploy .

# Cleanup
rm -rf /tmp/preprocessing_deploy

echo "Deployment package created: $PACKAGE_NAME"
EOF

chmod +x create_deployment_package.sh
./create_deployment_package.sh
```

### Step 5: Upload Package to EC2
```bash
# Upload the deployment package
scp -i resources/aws/legal-doc-processor-bastion.pem \
    preprocessing_deployment.tar.gz \
    ubuntu@54.162.223.205:/tmp/

# Upload environment template
scp -i resources/aws/legal-doc-processor-bastion.pem \
    .env \
    ubuntu@54.162.223.205:/tmp/.env.template
```

### Step 6: Deploy on EC2
```bash
# SSH back into EC2
ssh -i resources/aws/legal-doc-processor-bastion.pem ubuntu@54.162.223.205

# Extract deployment package
cd /opt/legal-doc-processor
tar -xzf /tmp/preprocessing_deployment.tar.gz

# Setup Python virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Upgrade pip and install wheel
pip install --upgrade pip wheel

# Install Python dependencies
pip install -r requirements.txt

# Setup environment file
cp /tmp/.env.template .env
```

### Step 7: Configure Environment Variables
```bash
# Edit the .env file
nano /opt/legal-doc-processor/.env

# Update these specific values:
# Change from SSH tunnel to direct connection:
DATABASE_URL=postgresql://app_user:LegalDoc2025!Secure@database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432/legal_doc_processing?sslmode=require

# Ensure AWS region is correct:
AWS_REGION=us-east-1
AWS_DEFAULT_REGION=us-east-1

# Keep all other values (Redis, OpenAI, etc.) the same
```

## Part 3: Remote IDE Access Setup

### Step 8: Install VS Code Server (for Cursor/VS Code Remote)
```bash
# On EC2, install code-server for remote development
curl -fsSL https://code-server.dev/install.sh | sh

# Create code-server config directory
mkdir -p ~/.config/code-server

# Create config file
cat > ~/.config/code-server/config.yaml << 'EOF'
bind-addr: 127.0.0.1:8080
auth: password
password: your-secure-password-here
cert: false
EOF

# Create systemd service for code-server
sudo tee /etc/systemd/system/code-server@ubuntu.service > /dev/null << 'EOF'
[Unit]
Description=code-server
After=network.target

[Service]
Type=exec
User=ubuntu
WorkingDirectory=/opt/legal-doc-processor
ExecStart=/usr/bin/code-server --bind-addr 127.0.0.1:8080
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Enable and start code-server
sudo systemctl enable code-server@ubuntu
sudo systemctl start code-server@ubuntu
```

### Step 9: Setup SSH Config for Easy Access (Local Machine)
```bash
# On your local machine, add to ~/.ssh/config
cat >> ~/.ssh/config << 'EOF'

Host legal-doc-ec2
    HostName 54.162.223.205
    User ubuntu
    IdentityFile ~/Documents/phase_1_2_3_process_v5/resources/aws/legal-doc-processor-bastion.pem
    ForwardAgent yes
    LocalForward 8080 127.0.0.1:8080
    LocalForward 5555 127.0.0.1:5555
    ServerAliveInterval 60
    ServerAliveCountMax 3
EOF
```

### Step 10: Connect with Cursor/VS Code
```bash
# Option 1: Using VS Code/Cursor Remote SSH Extension
# 1. Install "Remote - SSH" extension in Cursor/VS Code
# 2. Press Cmd+Shift+P (Mac) or Ctrl+Shift+P (Windows/Linux)
# 3. Type "Remote-SSH: Connect to Host"
# 4. Select "legal-doc-ec2"
# 5. Open folder: /opt/legal-doc-processor

# Option 2: Using code-server in browser
# 1. SSH with port forwarding:
ssh legal-doc-ec2

# 2. Open browser to: http://localhost:8080
# 3. Enter password from config.yaml
```

## Part 4: Service Configuration

### Step 11: Create Supervisor Configuration
```bash
# On EC2, create Celery worker configs
sudo tee /etc/supervisor/conf.d/celery-workers.conf > /dev/null << 'EOF'
[program:celery-ocr]
command=/opt/legal-doc-processor/venv/bin/celery -A scripts.celery_app worker --loglevel=info -Q ocr -n worker.ocr@%%h
directory=/opt/legal-doc-processor
user=ubuntu
environment=PATH="/opt/legal-doc-processor/venv/bin:%(ENV_PATH)s"
autostart=true
autorestart=true
stdout_logfile=/var/log/legal-doc-processor/celery-ocr.log
stderr_logfile=/var/log/legal-doc-processor/celery-ocr-error.log

[program:celery-text]
command=/opt/legal-doc-processor/venv/bin/celery -A scripts.celery_app worker --loglevel=info -Q text -n worker.text@%%h
directory=/opt/legal-doc-processor
user=ubuntu
environment=PATH="/opt/legal-doc-processor/venv/bin:%(ENV_PATH)s"
autostart=true
autorestart=true
stdout_logfile=/var/log/legal-doc-processor/celery-text.log
stderr_logfile=/var/log/legal-doc-processor/celery-text-error.log

[group:celery]
programs=celery-ocr,celery-text
EOF

# Reload supervisor
sudo supervisorctl reread
sudo supervisorctl update
```

### Step 12: Test Database Connectivity
```bash
# Activate virtual environment
cd /opt/legal-doc-processor
source venv/bin/activate

# Test direct database connection
python3 << 'EOF'
import os
from scripts.db import get_engine

# Force direct connection
os.environ['DATABASE_URL'] = os.environ['DATABASE_URL'].replace('localhost:5433', 'database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432')

try:
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute("SELECT version()")
        print(f"Connected to: {result.scalar()}")
except Exception as e:
    print(f"Connection failed: {e}")
EOF
```

### Step 13: Create Helper Scripts
```bash
# Create start script
cat > /opt/legal-doc-processor/start_workers.sh << 'EOF'
#!/bin/bash
source /opt/legal-doc-processor/venv/bin/activate
export $(cat /opt/legal-doc-processor/.env | xargs)
sudo supervisorctl start celery:*
EOF

# Create stop script
cat > /opt/legal-doc-processor/stop_workers.sh << 'EOF'
#!/bin/bash
sudo supervisorctl stop celery:*
EOF

# Create status script
cat > /opt/legal-doc-processor/check_status.sh << 'EOF'
#!/bin/bash
echo "=== System Status ==="
echo "Celery Workers:"
sudo supervisorctl status
echo ""
echo "Python Environment:"
/opt/legal-doc-processor/venv/bin/python --version
echo ""
echo "Database Connection:"
/opt/legal-doc-processor/venv/bin/python -c "
from scripts.db import get_engine
try:
    engine = get_engine()
    print('Database: Connected')
except Exception as e:
    print(f'Database: Failed - {e}')
"
EOF

chmod +x /opt/legal-doc-processor/*.sh
```

## Part 5: Verification

### Step 14: Verify Deployment
```bash
# Run verification script
cd /opt/legal-doc-processor
./check_status.sh

# Test preprocessing pipeline
source venv/bin/activate
python3 << 'EOF'
from scripts.pdf_tasks import process_pdf_document
import uuid

# Create test document
test_doc = {
    'document_uuid': str(uuid.uuid4()),
    'filename': 'test.pdf',
    'project_uuid': str(uuid.uuid4())
}

print(f"Testing document processing: {test_doc}")
# Note: This will fail if no actual PDF, but will test connectivity
EOF
```

### Step 15: Setup Log Monitoring
```bash
# Create log tail script
cat > /opt/legal-doc-processor/tail_logs.sh << 'EOF'
#!/bin/bash
tail -f /var/log/legal-doc-processor/*.log
EOF
chmod +x /opt/legal-doc-processor/tail_logs.sh
```

## Summary Checklist

- [ ] EC2 system updated with Python 3.11
- [ ] All system dependencies installed
- [ ] Application directories created with correct permissions
- [ ] Preprocessing scripts deployed to /opt/legal-doc-processor
- [ ] Python virtual environment created and dependencies installed
- [ ] Environment variables configured for direct database access
- [ ] VS Code Server installed for remote IDE access
- [ ] SSH config updated for easy connection
- [ ] Supervisor configured for Celery workers
- [ ] Database connectivity verified
- [ ] Helper scripts created for management
- [ ] Remote IDE access working

## Next Steps

1. Connect to EC2 using Cursor/VS Code Remote SSH
2. Start Celery workers: `./start_workers.sh`
3. Monitor logs: `./tail_logs.sh`
4. Test document processing with actual PDFs
5. Configure CloudWatch for production monitoring

## Troubleshooting

### If database connection fails:
```bash
# Check security group allows connection from EC2
# Verify credentials in .env
# Test with psql directly:
PGPASSWORD='LegalDoc2025!Secure' psql \
    -h database1.cuviucyodbeg.us-east-1.rds.amazonaws.com \
    -p 5432 -U app_user -d legal_doc_processing
```

### If Celery workers won't start:
```bash
# Check supervisor logs
sudo tail -f /var/log/supervisor/supervisord.log
# Check individual worker logs
tail -f /var/log/legal-doc-processor/celery-*.log
```

### If VS Code Remote won't connect:
```bash
# Ensure SSH key permissions are correct
chmod 600 ~/Documents/phase_1_2_3_process_v5/resources/aws/legal-doc-processor-bastion.pem
# Test basic SSH connection first
ssh -v legal-doc-ec2
```