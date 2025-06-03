#!/bin/bash
# Deploy RDS schema via bastion host
# This script creates an SSH tunnel and deploys the schema

set -e

# Configuration
BASTION_IP="${BASTION_IP:-}"  # Set this to your bastion host IP
BASTION_KEY="${BASTION_KEY:-resources/aws/legal-doc-processor-bastion.pem}"
LOCAL_PORT="${LOCAL_PORT:-5433}"
RDS_ENDPOINT="database1.cuviucyodbeg.us-east-1.rds.amazonaws.com"
RDS_PORT="5432"
DB_NAME="legal_doc_processing"
DB_USER="app_user"
DB_PASSWORD="LegalDoc2025!Secure"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}RDS Schema Deployment via Bastion${NC}"
echo "=================================="

# Check if bastion IP is provided
if [ -z "$BASTION_IP" ]; then
    echo -e "${RED}Error: BASTION_IP environment variable not set${NC}"
    echo "Usage: BASTION_IP=54.x.x.x ./deploy_via_bastion.sh"
    exit 1
fi

# Check if PEM file exists
if [ ! -f "$BASTION_KEY" ]; then
    echo -e "${RED}Error: Bastion key not found at $BASTION_KEY${NC}"
    exit 1
fi

# Kill any existing tunnel on the local port
echo -e "${YELLOW}Checking for existing tunnels...${NC}"
lsof -ti:$LOCAL_PORT | xargs kill -9 2>/dev/null || true

# Create SSH tunnel in background
echo -e "${YELLOW}Creating SSH tunnel through bastion...${NC}"
ssh -f -N -L $LOCAL_PORT:$RDS_ENDPOINT:$RDS_PORT -i $BASTION_KEY ubuntu@$BASTION_IP

# Wait for tunnel to establish
sleep 3

# Test connection through tunnel
echo -e "${YELLOW}Testing database connection...${NC}"
PGPASSWORD=$DB_PASSWORD psql -h localhost -p $LOCAL_PORT -U $DB_USER -d postgres -c "SELECT version();" || {
    echo -e "${RED}Failed to connect to database through tunnel${NC}"
    exit 1
}

echo -e "${GREEN}✓ Database connection successful${NC}"

# Create database if it doesn't exist
echo -e "${YELLOW}Creating database if needed...${NC}"
PGPASSWORD=$DB_PASSWORD psql -h localhost -p $LOCAL_PORT -U $DB_USER -d postgres -c "CREATE DATABASE $DB_NAME;" 2>/dev/null || {
    echo -e "${YELLOW}Database already exists (this is OK)${NC}"
}

# Deploy schema
echo -e "${YELLOW}Deploying schema...${NC}"
PGPASSWORD=$DB_PASSWORD psql -h localhost -p $LOCAL_PORT -U $DB_USER -d $DB_NAME < scripts/create_simple_rds_schema.sql || {
    echo -e "${RED}Schema deployment failed${NC}"
    exit 1
}

echo -e "${GREEN}✓ Schema deployed successfully${NC}"

# Verify deployment
echo -e "${YELLOW}Verifying deployment...${NC}"
TABLES=$(PGPASSWORD=$DB_PASSWORD psql -h localhost -p $LOCAL_PORT -U $DB_USER -d $DB_NAME -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE';")
TABLES=$(echo $TABLES | tr -d ' ')

echo -e "${GREEN}✓ Found $TABLES tables in database${NC}"

# List tables
echo -e "${YELLOW}Database tables:${NC}"
PGPASSWORD=$DB_PASSWORD psql -h localhost -p $LOCAL_PORT -U $DB_USER -d $DB_NAME -c "\dt"

# Show connection info for applications
echo ""
echo -e "${GREEN}Deployment Complete!${NC}"
echo "===================="
echo -e "${YELLOW}Connection string for applications:${NC}"
echo "postgresql://$DB_USER:$DB_PASSWORD@$RDS_ENDPOINT:$RDS_PORT/$DB_NAME?sslmode=require"
echo ""
echo -e "${YELLOW}To connect via psql through tunnel:${NC}"
echo "PGPASSWORD=$DB_PASSWORD psql -h localhost -p $LOCAL_PORT -U $DB_USER -d $DB_NAME"
echo ""
echo -e "${YELLOW}Note: SSH tunnel is running in background. To stop it:${NC}"
echo "lsof -ti:$LOCAL_PORT | xargs kill"