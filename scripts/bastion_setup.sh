#!/bin/bash
# Bastion setup script for legal document processing

set -e

echo "🚀 Starting bastion setup..."

# Update system
echo "📦 Updating system packages..."
sudo apt update && sudo apt upgrade -y

# Install essential tools
echo "🔧 Installing essential tools..."
sudo apt install -y \
    postgresql-client-14 \
    python3-pip python3-venv python3-dev \
    git curl wget htop ncdu unzip \
    build-essential libpq-dev

# Install AWS CLI v2
echo "☁️ Installing AWS CLI..."
if ! command -v aws &> /dev/null; then
    curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
    unzip awscliv2.zip
    sudo ./aws/install
    rm -rf awscliv2.zip aws/
fi

# Create project directory
echo "📁 Setting up project directory..."
mkdir -p ~/legal-doc-processing
cd ~/legal-doc-processing

# Setup Python environment
echo "🐍 Setting up Python environment..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools wheel

# Install Python packages
echo "📦 Installing Python packages..."
pip install \
    psycopg2-binary \
    sqlalchemy \
    boto3 \
    python-dotenv \
    pandas \
    redis \
    celery

# Create database connection test script
echo "📝 Creating database test script..."
cat > test_rds_from_bastion.py << 'EOF'
#!/usr/bin/env python3
import os
import psycopg2
from sqlalchemy import create_engine

# RDS connection details
RDS_ENDPOINT = "database1.cuviucyodbeg.us-east-1.rds.amazonaws.com"
RDS_PORT = 5432

def test_connection():
    """Test RDS connection from bastion"""
    # Test with master credentials first
    master_user = input("Enter RDS master username (postgres): ") or "postgres"
    master_pass = input("Enter RDS master password: ")
    
    try:
        # Connect to postgres database
        conn = psycopg2.connect(
            host=RDS_ENDPOINT,
            port=RDS_PORT,
            database="postgres",
            user=master_user,
            password=master_pass
        )
        cur = conn.cursor()
        cur.execute("SELECT version();")
        version = cur.fetchone()
        print(f"\n✅ Connected successfully!")
        print(f"PostgreSQL version: {version[0]}")
        
        # Check for legal_doc_processing database
        cur.execute("""
            SELECT datname FROM pg_database 
            WHERE datname = 'legal_doc_processing'
        """)
        
        if cur.fetchone():
            print("✅ Database 'legal_doc_processing' exists")
        else:
            print("❌ Database 'legal_doc_processing' not found")
            print("   Run the setup scripts to create it")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"\n❌ Connection failed: {e}")
        return False

if __name__ == "__main__":
    print("🔍 Testing RDS connection from bastion...")
    print(f"Endpoint: {RDS_ENDPOINT}")
    test_connection()
EOF

chmod +x test_rds_from_bastion.py

# Create .env template
echo "📝 Creating .env template..."
cat > .env.template << 'EOF'
# RDS PostgreSQL Configuration
DATABASE_URL=postgresql://app_user:LegalDoc2025!Secure@database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432/legal_doc_processing?sslmode=require

# Redis Configuration (update when Redis is setup)
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=

# AWS Configuration
AWS_DEFAULT_REGION=us-east-1
EOF

# Create helper scripts
echo "📝 Creating helper scripts..."

# Script to run SQL files
cat > run_sql.sh << 'EOF'
#!/bin/bash
# Helper to run SQL files against RDS

if [ $# -eq 0 ]; then
    echo "Usage: ./run_sql.sh <sql_file>"
    exit 1
fi

echo "Running $1 against RDS..."
psql -h database1.cuviucyodbeg.us-east-1.rds.amazonaws.com \
     -p 5432 \
     -U ${DB_USER:-postgres} \
     -d ${DB_NAME:-postgres} \
     -f "$1"
EOF
chmod +x run_sql.sh

# Create SSH tunnel script for local development
cat > create_tunnel.sh << 'EOF'
#!/bin/bash
# Creates SSH tunnel to access RDS from local machine

echo "Creating SSH tunnel to RDS via bastion..."
echo "RDS will be available at localhost:5432"
ssh -N -L 5432:database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432 ubuntu@$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)
EOF
chmod +x create_tunnel.sh

echo "✅ Bastion setup complete!"
echo ""
echo "📋 Next steps:"
echo "1. Test RDS connection: python3 test_rds_from_bastion.py"
echo "2. Copy your SQL scripts to this instance"
echo "3. Run database setup: ./run_sql.sh setup_rds_database.sql"
echo "4. Create schema: ./run_sql.sh create_schema.sql"
echo ""
echo "💡 To create an SSH tunnel from your local machine:"
echo "   ssh -L 5432:database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432 ubuntu@$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)"