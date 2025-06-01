#!/bin/bash
# Interactive RDS initialization script
# Prompts for master password securely

set -e

# Configuration
BASTION_IP="54.162.223.205"
BASTION_KEY="resources/aws/legal-doc-processor-bastion.pem"
LOCAL_PORT="5433"
RDS_ENDPOINT="database1.cuviucyodbeg.us-east-1.rds.amazonaws.com"
RDS_PORT="5432"

# Database configuration
DB_NAME="legal_doc_processing"
APP_USER="app_user"
APP_PASSWORD="LegalDoc2025!Secure"
MASTER_USER="postgres"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}RDS Database Interactive Initialization${NC}"
echo "======================================"
echo ""
echo "This script will:"
echo "1. Connect to RDS via the bastion host"
echo "2. Create the application database and user"
echo "3. Grant necessary permissions"
echo ""
echo -e "${YELLOW}Configuration:${NC}"
echo "  Bastion: $BASTION_IP"
echo "  RDS: $RDS_ENDPOINT"
echo "  Database: $DB_NAME"
echo "  App User: $APP_USER"
echo ""

# Prompt for master password
echo -e "${YELLOW}Please enter the RDS master password for user 'postgres':${NC}"
read -s MASTER_PASSWORD
echo ""

if [ -z "$MASTER_PASSWORD" ]; then
    echo -e "${RED}Error: Password cannot be empty${NC}"
    exit 1
fi

# Export for the init script
export RDS_MASTER_PASSWORD="$MASTER_PASSWORD"

# Run the initialization
echo -e "${YELLOW}Starting initialization...${NC}"
./scripts/init_rds_database.sh

echo ""
echo -e "${GREEN}✓ Initialization complete!${NC}"
echo ""
echo "Next steps:"
echo "1. Run the schema deployment:"
echo "   ${CYAN}BASTION_IP=$BASTION_IP ./scripts/deploy_via_bastion.sh${NC}"
echo ""
echo "2. Update your .env file with:"
echo "   ${CYAN}DATABASE_URL=postgresql://$APP_USER:$APP_PASSWORD@$RDS_ENDPOINT:$RDS_PORT/$DB_NAME?sslmode=require${NC}"