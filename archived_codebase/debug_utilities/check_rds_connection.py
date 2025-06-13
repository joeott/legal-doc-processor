#!/usr/bin/env python3
"""
RDS Database Connection Checker
Verifies database connectivity and provides helpful diagnostics
"""

import sys
import os
import subprocess
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from scripts.rds_utils import test_connection, health_check
from scripts.config import (
    DATABASE_URL, DATABASE_URL_DIRECT, 
    RDS_BASTION_HOST, RDS_TUNNEL_LOCAL_PORT,
    get_database_url, DEPLOYMENT_STAGE, STAGE_DESCRIPTIONS
)

def check_tunnel_status():
    """Check if SSH tunnel is active."""
    try:
        result = subprocess.run(
            ['lsof', f'-ti:{RDS_TUNNEL_LOCAL_PORT}'], 
            capture_output=True, text=True
        )
        return bool(result.stdout.strip())
    except:
        return False

def main():
    print("RDS Database Connection Checker")
    print("=" * 50)
    
    # Show deployment stage
    print(f"Deployment Stage: {DEPLOYMENT_STAGE} - {STAGE_DESCRIPTIONS[DEPLOYMENT_STAGE]}")
    print(f"Database URL in use: {'Direct' if get_database_url() == DATABASE_URL_DIRECT else 'Tunnel'}")
    print()
    
    # Check tunnel status
    tunnel_active = check_tunnel_status()
    if DEPLOYMENT_STAGE != "3":  # Not production
        print(f"SSH Tunnel Status: {'✓ Active' if tunnel_active else '✗ Inactive'}")
        if not tunnel_active:
            print("  To start tunnel: ./scripts/start_rds_tunnel.sh")
    print()
    
    # Test connection
    print("Testing database connection...")
    connected = test_connection()
    
    if connected:
        print("✓ Database connection: SUCCESS")
        print()
        
        # Get health check
        health = health_check()
        print(f"Database Status: {health.get('status', 'unknown')}")
        
        if 'version' in health:
            print(f"PostgreSQL Version: {health['version']}")
        
        if 'tables' in health:
            print("\nTable Statistics:")
            total_rows = 0
            for table, count in health['tables'].items():
                if isinstance(count, int):
                    print(f"  {table:<20} {count:>10,} rows")
                    total_rows += count
                else:
                    print(f"  {table:<20} {count:>10}")
            print(f"  {'Total':<20} {total_rows:>10,} rows")
    else:
        print("✗ Database connection: FAILED")
        print()
        print("Troubleshooting steps:")
        
        if DEPLOYMENT_STAGE != "3" and not tunnel_active:
            print("1. Start SSH tunnel:")
            print("   ./scripts/start_rds_tunnel.sh")
        
        print("2. Check environment variables in .env:")
        print("   - DATABASE_URL")
        print("   - DATABASE_URL_DIRECT")
        
        print("3. Verify bastion host is accessible:")
        print(f"   ssh -i resources/aws/legal-doc-processor-bastion.pem ubuntu@{RDS_BASTION_HOST}")
        
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())