#!/bin/bash
# Start SSH tunnel for RDS database access

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if tunnel already exists
if lsof -ti:5433 > /dev/null 2>&1; then
    echo -e "${GREEN}✓ SSH tunnel already active on port 5433${NC}"
    exit 0
fi

# Check if PEM key exists
PEM_KEY="resources/aws/legal-doc-processor-bastion.pem"
if [ ! -f "$PEM_KEY" ]; then
    echo -e "${RED}✗ PEM key not found at $PEM_KEY${NC}"
    exit 1
fi

# Create tunnel
echo "Creating SSH tunnel to RDS..."
ssh -f -N -L 5433:database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432 \
    -i "$PEM_KEY" \
    ubuntu@54.162.223.205

# Wait a moment for tunnel to establish
sleep 2

# Verify tunnel
if lsof -ti:5433 > /dev/null 2>&1; then
    echo -e "${GREEN}✓ SSH tunnel created successfully on port 5433${NC}"
    echo "You can now connect to RDS using: postgresql://app_user:LegalDoc2025!Secure@localhost:5433/legal_doc_processing"
else
    echo -e "${RED}✗ Failed to create SSH tunnel${NC}"
    exit 1
fi