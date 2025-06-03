# Context 250: Docker vs Git for EC2 Deployment Strategy

## Quick Answer

**Git is the better choice** for your current needs. Docker would add unnecessary complexity given that you:
1. Already have direct database access on EC2
2. Need to work with local file paths and AWS services
3. Want to use Cursor/VS Code for remote development

## Detailed Comparison

### Option 1: Git (Recommended)

**How it works:**
```bash
# On local machine
git init
git add scripts/ requirements.txt
git commit -m "Initial preprocessing pipeline"
git remote add origin git@github.com:yourusername/legal-doc-processor.git
git push origin main

# On EC2
cd /opt/legal-doc-processor
git clone git@github.com:yourusername/legal-doc-processor.git .
git pull origin main  # for updates
```

**Advantages:**
- ✅ Simple and straightforward
- ✅ Easy to sync changes between local and EC2
- ✅ Works perfectly with Cursor remote development
- ✅ Can track changes and rollback if needed
- ✅ Lightweight - no overhead

**Disadvantages:**
- ❌ Need to manage Python environments separately
- ❌ System dependencies must be installed on each machine

### Option 2: Docker

**How it works:**
```dockerfile
# Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY scripts/ ./scripts/
CMD ["celery", "-A", "scripts.celery_app", "worker"]
```

**Advantages:**
- ✅ Consistent environment everywhere
- ✅ Includes all dependencies
- ✅ Easy to scale with orchestration

**Disadvantages:**
- ❌ Adds complexity for database connections
- ❌ Harder to use with Cursor remote development
- ❌ Requires Docker knowledge and setup
- ❌ May complicate AWS service access (IAM roles, etc.)
- ❌ Overhead for your simple use case

## Recommended Approach: Git + Setup Script

### Step 1: Initialize Git Repository (Local)
```bash
cd /Users/josephott/Documents/phase_1_2_3_process_v5
git init
echo "__pycache__/" >> .gitignore
echo "*.pyc" >> .gitignore
echo ".env" >> .gitignore
echo ".DS_Store" >> .gitignore
echo "logs/" >> .gitignore
git add scripts/ requirements.txt
git commit -m "Initial preprocessing pipeline"
```

### Step 2: Create Setup Script
```bash
# create_setup_script.sh
cat > setup_ec2.sh << 'EOF'
#!/bin/bash
# EC2 Setup Script for Legal Doc Processor

# Install system dependencies
sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv python3.11-dev
sudo apt-get install -y postgresql-client redis-tools build-essential libpq-dev
sudo apt-get install -y poppler-utils tesseract-ocr supervisor

# Create directories
sudo mkdir -p /opt/legal-doc-processor
sudo mkdir -p /var/log/legal-doc-processor
sudo chown -R ubuntu:ubuntu /opt/legal-doc-processor
sudo chown -R ubuntu:ubuntu /var/log/legal-doc-processor

# Setup Python environment
cd /opt/legal-doc-processor
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "Setup complete! Don't forget to:"
echo "1. Copy .env file"
echo "2. Configure supervisor for Celery workers"
echo "3. Test database connection"
EOF
```

### Step 3: Push to GitHub
```bash
# Create a private repository on GitHub first
git remote add origin git@github.com:yourusername/legal-doc-processor-private.git
git push -u origin main
```

### Step 4: Clone on EC2
```bash
# On EC2 (via Cursor terminal)
cd /opt/legal-doc-processor
git clone git@github.com:yourusername/legal-doc-processor-private.git .

# Run setup
chmod +x setup_ec2.sh
./setup_ec2.sh
```

### Step 5: Sync Changes
```bash
# On local machine after making changes
git add .
git commit -m "Update feature X"
git push

# On EC2
git pull
# Restart services if needed
sudo supervisorctl restart all
```

## Why Git is Better for Your Case

1. **Direct Database Access**: You're on EC2 specifically to avoid SSH tunnels - Docker would complicate this
2. **Cursor Integration**: Git works seamlessly with remote development
3. **Simplicity**: No need to learn Docker for this use case
4. **Flexibility**: Easy to make quick changes and test
5. **AWS Services**: Easier to use IAM roles and AWS services without container boundaries

## If You Still Want Docker Later

You can always add Docker later for:
- Production deployment to ECS/Fargate
- Multi-server scaling
- Complete environment isolation
- CI/CD pipelines

But for now, Git gives you everything you need with less complexity.

## Next Steps

1. Create a private GitHub repository
2. Initialize git in your local project
3. Push your code
4. Clone on EC2
5. Use git pull/push to sync changes

This gives you version control, easy syncing, and works perfectly with your Cursor remote development setup.