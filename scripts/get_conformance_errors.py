#!/usr/bin/env python3
"""Get detailed schema conformance errors"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from scripts.db import DatabaseManager
from scripts.core.conformance_validator import ConformanceValidator

try:
    # Create database manager and trigger validation
    db_manager = DatabaseManager(validate_conformance=True)
except Exception as e:
    logger.error(f"Conformance validation failed: {e}")
    
    # Try to get detailed validation results
    try:
        validator = ConformanceValidator()
        from scripts.config import db_engine
        
        with db_engine.connect() as conn:
            validation_result = validator.validate_schema(conn)
            
            print("\n" + "="*80)
            print("SCHEMA CONFORMANCE VALIDATION REPORT")
            print("="*80)
            
            print(f"\nTotal issues found: {validation_result.total_issues}")
            print(f"Critical issues: {validation_result.critical_issues}")
            print(f"Warnings: {validation_result.warnings}")
            print(f"Is valid: {validation_result.is_valid}")
            
            if validation_result.issues:
                print("\nDETAILED ISSUES:")
                print("-"*80)
                for i, issue in enumerate(validation_result.issues, 1):
                    print(f"\n{i}. {issue.severity.upper()}: {issue.issue_type}")
                    print(f"   Table: {issue.table_name}")
                    print(f"   Column: {issue.column_name or 'N/A'}")
                    print(f"   Message: {issue.message}")
                    if issue.details:
                        print(f"   Details: {issue.details}")
                    if issue.suggestion:
                        print(f"   Suggestion: {issue.suggestion}")
            
            if validation_result.recovery_actions:
                print("\n\nRECOVERY ACTIONS:")
                print("-"*80)
                for action in validation_result.recovery_actions:
                    print(f"\n- {action}")
                    
    except Exception as inner_e:
        logger.error(f"Failed to get detailed validation: {inner_e}")
        import traceback
        traceback.print_exc()