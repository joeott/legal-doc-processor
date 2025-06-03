#!/usr/bin/env python3
"""
Migrate to minimal database manager by replacing db.py
"""

import os
import shutil
import sys

def backup_original():
    """Backup the original db.py"""
    print("📁 Backing up original db.py...")
    if os.path.exists("scripts/db.py"):
        shutil.copy("scripts/db.py", "scripts/db_original.py")
        print("✅ Backed up to scripts/db_original.py")
    else:
        print("⚠️  No db.py found to backup")

def replace_with_minimal():
    """Replace db.py with db_minimal.py"""
    print("\n🔄 Replacing db.py with minimal version...")
    if os.path.exists("scripts/db_minimal.py"):
        shutil.copy("scripts/db_minimal.py", "scripts/db.py")
        print("✅ Replaced db.py with minimal version")
    else:
        print("❌ db_minimal.py not found!")
        return False
    return True

def test_import():
    """Test that the new db.py imports correctly"""
    print("\n🧪 Testing new db.py imports...")
    try:
        # Set required environment variable
        os.environ['OPENAI_API_KEY'] = 'test-key-for-import'
        
        from scripts.db import DatabaseManager, get_db_manager
        db_manager = get_db_manager()
        print("✅ Database manager imports successfully")
        print(f"   Type: {type(db_manager)}")
        return True
    except Exception as e:
        print(f"❌ Import failed: {e}")
        return False

def main():
    """Run the migration"""
    print("=" * 60)
    print("🚀 MIGRATING TO MINIMAL DATABASE MANAGER")
    print("=" * 60)
    
    # Step 1: Backup
    backup_original()
    
    # Step 2: Replace
    if not replace_with_minimal():
        print("\n❌ Migration failed!")
        return 1
    
    # Step 3: Test
    if not test_import():
        print("\n⚠️  Rolling back...")
        if os.path.exists("scripts/db_original.py"):
            shutil.copy("scripts/db_original.py", "scripts/db.py")
            print("✅ Rolled back to original")
        return 1
    
    print("\n✅ Migration complete!")
    print("\n📝 Next steps:")
    print("1. Test the pipeline with: python3 test_e2e_existing_doc.py")
    print("2. If successful, remove scripts/db_original.py")
    print("3. Remove scripts/db_minimal.py")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())