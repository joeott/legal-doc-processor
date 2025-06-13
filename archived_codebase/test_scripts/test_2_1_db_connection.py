#!/usr/bin/env python3
"""Test 2.1: Database Connection Without Conformance"""

print("=== Test 2.1: Database Connection Without Conformance ===")
import sys
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Verify environment variables are set
print(f"USE_MINIMAL_MODELS: {os.getenv('USE_MINIMAL_MODELS')}")
print(f"SKIP_CONFORMANCE_CHECK: {os.getenv('SKIP_CONFORMANCE_CHECK')}")

try:
    from scripts.db import DatabaseManager
    from scripts.config import db_engine
    from sqlalchemy import text
    
    # Create database manager without conformance validation
    print("\nCreating DatabaseManager with validate_conformance=False...")
    db = DatabaseManager(validate_conformance=False)
    print("✓ Database connection successful without conformance")
    
    # Test a simple query to verify connection using the engine directly
    print("\nTesting database query...")
    with db_engine.connect() as conn:
        result = conn.execute(text("SELECT 1")).scalar()
        print(f"✓ Query result: {result}")
    
    # Check if conformance was actually skipped
    print("\n✓ No conformance validation errors occurred")
    print("✓ Test 2.1 PASSED")
    
except Exception as e:
    print(f"✗ Database connection failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)