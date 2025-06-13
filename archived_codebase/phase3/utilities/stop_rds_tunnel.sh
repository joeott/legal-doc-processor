#!/bin/bash
# Stop SSH tunnel for RDS database access

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# Check if tunnel exists
PID=$(lsof -ti:5433 2>/dev/null)

if [ -z "$PID" ]; then
    echo -e "${YELLOW}No SSH tunnel found on port 5433${NC}"
    exit 0
fi

# Kill the tunnel process
echo "Stopping SSH tunnel (PID: $PID)..."
kill -9 $PID

# Verify it's stopped
sleep 1
if lsof -ti:5433 > /dev/null 2>&1; then
    echo -e "${RED}✗ Failed to stop SSH tunnel${NC}"
    exit 1
else
    echo -e "${GREEN}✓ SSH tunnel stopped successfully${NC}"
fi