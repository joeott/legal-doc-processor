#!/bin/bash
# Initialize RDS database and user via bastion host
# This script creates the database and application user

set -e

# Configuration
BASTION_IP="${BASTION_IP:-54.162.223.205}"
BASTION_KEY="${BASTION_KEY:-resources/aws/legal-doc-processor-bastion.pem}"
LOCAL_PORT="${LOCAL_PORT:-5433}"
RDS_ENDPOINT="database1.cuviucyodbeg.us-east-1.rds.amazonaws.com"
RDS_PORT="5432"

# Database configuration
DB_NAME="legal_doc_processing"
APP_USER="app_user"
APP_PASSWORD="LegalDoc2025!Secure"
MASTER_USER="postgres"
MASTER_PASSWORD="${RDS_MASTER_PASSWORD:-}"  # Must be provided

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}RDS Database Initialization${NC}"
echo "============================"

# Check if master password is provided
if [ -z "$MASTER_PASSWORD" ]; then
    echo -e "${RED}Error: RDS_MASTER_PASSWORD environment variable not set${NC}"
    echo "Usage: RDS_MASTER_PASSWORD=<password> ./init_rds_database.sh"
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

# Test connection as master user
echo -e "${YELLOW}Testing master connection...${NC}"
PGPASSWORD=$MASTER_PASSWORD psql -h localhost -p $LOCAL_PORT -U $MASTER_USER -d postgres -c "SELECT version();" || {
    echo -e "${RED}Failed to connect as master user${NC}"
    echo "Please check your RDS_MASTER_PASSWORD"
    exit 1
}

echo -e "${GREEN}✓ Master connection successful${NC}"

# Create application user if it doesn't exist
echo -e "${YELLOW}Creating application user...${NC}"
PGPASSWORD=$MASTER_PASSWORD psql -h localhost -p $LOCAL_PORT -U $MASTER_USER -d postgres << EOF
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_user WHERE usename = '$APP_USER') THEN
        CREATE USER $APP_USER WITH PASSWORD '$APP_PASSWORD';
        RAISE NOTICE 'User $APP_USER created';
    ELSE
        ALTER USER $APP_USER WITH PASSWORD '$APP_PASSWORD';
        RAISE NOTICE 'User $APP_USER password updated';
    END IF;
END
\$\$;
EOF

# Create database if it doesn't exist
echo -e "${YELLOW}Creating database...${NC}"
PGPASSWORD=$MASTER_PASSWORD psql -h localhost -p $LOCAL_PORT -U $MASTER_USER -d postgres -tc "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" | grep -q 1 || {
    PGPASSWORD=$MASTER_PASSWORD psql -h localhost -p $LOCAL_PORT -U $MASTER_USER -d postgres -c "CREATE DATABASE $DB_NAME;"
    echo -e "${GREEN}✓ Database $DB_NAME created${NC}"
}

# Grant all privileges on database to app user
echo -e "${YELLOW}Granting privileges...${NC}"
PGPASSWORD=$MASTER_PASSWORD psql -h localhost -p $LOCAL_PORT -U $MASTER_USER -d postgres -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $APP_USER;"

# Connect to the database and grant schema permissions
PGPASSWORD=$MASTER_PASSWORD psql -h localhost -p $LOCAL_PORT -U $MASTER_USER -d $DB_NAME << EOF
-- Grant permissions on public schema
GRANT ALL ON SCHEMA public TO $APP_USER;
GRANT CREATE ON SCHEMA public TO $APP_USER;

-- Grant default privileges for future objects
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO $APP_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO $APP_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO $APP_USER;
EOF

echo -e "${GREEN}✓ Privileges granted${NC}"

# Test application user connection
echo -e "${YELLOW}Testing application user connection...${NC}"
PGPASSWORD=$APP_PASSWORD psql -h localhost -p $LOCAL_PORT -U $APP_USER -d $DB_NAME -c "SELECT current_user, current_database();" || {
    echo -e "${RED}Failed to connect as application user${NC}"
    exit 1
}

echo -e "${GREEN}✓ Application user can connect successfully${NC}"

# Kill the tunnel
echo -e "${YELLOW}Cleaning up tunnel...${NC}"
lsof -ti:$LOCAL_PORT | xargs kill -9 2>/dev/null || true

echo -e "${GREEN}✓ Database initialization complete!${NC}"
echo ""
echo "Database details:"
echo "  Database: $DB_NAME"
echo "  User: $APP_USER"
echo "  Password: $APP_PASSWORD"
echo ""
echo "You can now run the schema deployment script:"
echo "  BASTION_IP=$BASTION_IP ./scripts/deploy_via_bastion.sh"