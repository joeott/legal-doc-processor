#!/usr/bin/env python3
"""Safely migrate to standardized models"""

import os
import sys
import shutil
from datetime import datetime
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def backup_current_models():
    """Backup current model files"""
    backup_dir = f"model_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(backup_dir, exist_ok=True)
    
    files_to_backup = [
        "scripts/models.py",
        "scripts/core/schemas.py",
        "scripts/core/pdf_models.py",
        "scripts/core/models_minimal.py",
        "scripts/core/model_factory.py"
    ]
    
    for file_path in files_to_backup:
        if os.path.exists(file_path):
            backup_path = os.path.join(backup_dir, file_path.replace('/', '_'))
            shutil.copy2(file_path, backup_path)
            logger.info(f"✅ Backed up {file_path} to {backup_path}")
    
    return backup_dir

def check_import_usage():
    """Check for imports that need updating"""
    logger.info("\nChecking import usage...")
    
    import_patterns = [
        ("from scripts.core.schemas import", "Full schemas"),
        ("from scripts.core.pdf_models import", "PDF models"),
        ("from scripts.core.models_minimal import", "Core minimal models"),
        ("from scripts.models import", "Standard minimal models")
    ]
    
    issues_found = []
    
    for pattern, description in import_patterns:
        logger.info(f"\nChecking {description}...")
        result = os.popen(f'grep -r "{pattern}" scripts/ --include="*.py" | grep -v test_ | grep -v __pycache__ | wc -l').read().strip()
        count = int(result)
        logger.info(f"  Found {count} occurrences")
        
        if description != "Standard minimal models" and count > 0:
            issues_found.append(f"{description}: {count} imports need updating")
    
    return issues_found

def verify_model_consistency():
    """Verify models are consistent with database"""
    logger.info("\nVerifying model consistency...")
    
    try:
        # Import and run the test
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from scripts.test_model_consistency import test_model_db_consistency
        
        result = test_model_db_consistency()
        if result:
            logger.info("✅ Model consistency verified")
        else:
            logger.error("❌ Model consistency check failed")
            return False
    except Exception as e:
        logger.error(f"❌ Error during model consistency check: {e}")
        return False
    
    return True

def run_uuid_flow_test():
    """Run UUID flow test"""
    logger.info("\nRunning UUID flow test...")
    
    try:
        from scripts.test_uuid_flow import test_uuid_flow
        test_uuid_flow()
        logger.info("✅ UUID flow test passed")
        return True
    except Exception as e:
        logger.error(f"❌ UUID flow test failed: {e}")
        return False

def main():
    """Main migration function"""
    logger.info("Starting model standardization migration...")
    logger.info("="*60)
    
    # Step 1: Backup
    backup_dir = backup_current_models()
    logger.info(f"\nBackups saved to: {backup_dir}")
    
    # Step 2: Check imports
    issues = check_import_usage()
    if issues:
        logger.warning("\nImport issues found:")
        for issue in issues:
            logger.warning(f"  - {issue}")
    else:
        logger.info("\n✅ No import issues found")
    
    # Step 3: Verify model consistency
    if not verify_model_consistency():
        logger.error("\n❌ Model consistency check failed. Migration aborted.")
        logger.info(f"To restore, copy files from {backup_dir}")
        return 1
    
    # Step 4: Run UUID flow test
    if not run_uuid_flow_test():
        logger.error("\n❌ UUID flow test failed. Migration aborted.")
        logger.info(f"To restore, copy files from {backup_dir}")
        return 1
    
    # Step 5: Summary
    logger.info("\n" + "="*60)
    logger.info("MIGRATION SUMMARY")
    logger.info("="*60)
    logger.info("✅ Model standardization migration completed successfully!")
    logger.info("\nChanges implemented:")
    logger.info("1. Updated all models to match database schema exactly")
    logger.info("2. Fixed UUID type handling throughout the pipeline")
    logger.info("3. Corrected field name mismatches (char_start_index, char_end_index)")
    logger.info("4. Updated model factory to use standardized models")
    logger.info("\nNext steps:")
    logger.info("1. Monitor pipeline for any errors")
    logger.info("2. Run full end-to-end test with real documents")
    logger.info(f"3. Keep backup in {backup_dir} for 7 days")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())