#!/usr/bin/env python3
"""Verify current model and UUID handling issues"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def check_model_imports():
    """Check for conflicting model imports"""
    print("=" * 60)
    print("Checking Model Imports")
    print("=" * 60)
    
    import subprocess
    
    # Check for different model imports
    patterns = [
        ("Minimal models", "from scripts.models import"),
        ("Core schemas", "from scripts.core.schemas import"),
        ("PDF models", "from scripts.core.pdf_models import"),
        ("Direct model imports", "from models import")
    ]
    
    for name, pattern in patterns:
        result = subprocess.run(
            ["grep", "-r", pattern, "scripts/"],
            capture_output=True,
            text=True
        )
        count = len(result.stdout.strip().split('\n')) if result.stdout.strip() else 0
        print(f"{name}: {count} occurrences")
        if count > 0 and "Minimal" not in name:
            print(f"  ⚠️  Found conflicting imports!")
    print()

def check_uuid_field_names():
    """Check for inconsistent UUID field names"""
    print("=" * 60)
    print("Checking UUID Field Name Inconsistencies")
    print("=" * 60)
    
    # Load models to check field names
    try:
        from scripts.models import (
            DocumentChunkMinimal,
            EntityMentionMinimal,
            CanonicalEntityMinimal
        )
        
        # Check DocumentChunkMinimal
        chunk_fields = list(DocumentChunkMinimal.model_fields.keys())
        print(f"DocumentChunkMinimal fields: {chunk_fields}")
        if 'chunk_id' in chunk_fields:
            print("  ❌ Uses 'chunk_id' instead of 'chunk_uuid'")
        elif 'chunk_uuid' in chunk_fields:
            print("  ✅ Correctly uses 'chunk_uuid'")
            
        # Check for char index fields
        if 'start_char' in chunk_fields:
            print("  ❌ Uses 'start_char' instead of 'char_start_index'")
        if 'char_start_index' in chunk_fields:
            print("  ✅ Correctly uses 'char_start_index'")
            
        print()
        
        # Check EntityMentionMinimal
        mention_fields = list(EntityMentionMinimal.model_fields.keys())
        print(f"EntityMentionMinimal fields: {mention_fields}")
        if 'entity_mention_id' in mention_fields:
            print("  ❌ Uses 'entity_mention_id' instead of 'mention_uuid'")
        elif 'mention_uuid' in mention_fields:
            print("  ✅ Correctly uses 'mention_uuid'")
            
        print()
        
        # Check CanonicalEntityMinimal
        canonical_fields = list(CanonicalEntityMinimal.model_fields.keys())
        print(f"CanonicalEntityMinimal fields: {canonical_fields}")
        if 'canonical_entity_id' in canonical_fields:
            print("  ❌ Uses 'canonical_entity_id' instead of appropriate UUID field")
        
    except Exception as e:
        print(f"Error loading models: {e}")
    
    print()

def check_uuid_type_usage():
    """Check for string vs UUID type usage"""
    print("=" * 60)
    print("Checking UUID Type Usage in Tasks")
    print("=" * 60)
    
    import subprocess
    
    # Check for patterns that indicate string UUID usage
    patterns = [
        ("String UUID in cache keys", "f\".*{document_uuid}\""),
        ("UUID string conversion", "str(.*uuid)"),
        ("UUID from string", "UUID(.*uuid"),
        ("uuid.uuid4() calls", "uuid.uuid4()"),
    ]
    
    for name, pattern in patterns:
        result = subprocess.run(
            ["grep", "-r", "-E", pattern, "scripts/pdf_tasks.py"],
            capture_output=True,
            text=True
        )
        count = len(result.stdout.strip().split('\n')) if result.stdout.strip() else 0
        print(f"{name}: {count} occurrences")
    
    print()

def check_database_compatibility():
    """Check if models match database schema"""
    print("=" * 60)
    print("Checking Model-Database Compatibility")
    print("=" * 60)
    
    try:
        from scripts.db import get_db
        from sqlalchemy import text
        
        session = next(get_db())
        
        # Check key tables
        tables = ['document_chunks', 'entity_mentions', 'canonical_entities']
        
        for table in tables:
            result = session.execute(text(f"""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = '{table}'
                AND column_name LIKE '%uuid%' OR column_name LIKE '%_id'
                ORDER BY ordinal_position
            """)).fetchall()
            
            print(f"\n{table} UUID/ID columns:")
            for row in result:
                print(f"  - {row.column_name}")
        
        session.close()
        
    except Exception as e:
        print(f"Error checking database: {e}")
    
    print()

def check_specific_issues():
    """Check for specific known issues"""
    print("=" * 60)
    print("Checking Specific Known Issues")
    print("=" * 60)
    
    import subprocess
    
    # Check for the canonical entity UUID confusion
    issues = [
        ("canonical_entity_uuid vs entity_uuid confusion", 
         "grep -r 'canonical_entity_uuid' scripts/models.py"),
        ("resolved_canonical_id usage",
         "grep -r 'resolved_canonical_id' scripts/"),
        ("chunk_id UUID field",
         "grep -r 'chunk_id.*UUID' scripts/"),
    ]
    
    for issue, cmd in issues:
        result = subprocess.run(cmd.split(), capture_output=True, text=True)
        if result.stdout.strip():
            print(f"❌ {issue}:")
            count = len(result.stdout.strip().split('\n'))
            print(f"   Found: {count} occurrences")
        else:
            print(f"✅ {issue}: Not found")
    
    print()

def main():
    """Run all checks"""
    print("MODEL AND UUID CONSISTENCY VERIFICATION")
    print("=" * 60)
    print()
    
    check_model_imports()
    check_uuid_field_names()
    check_uuid_type_usage()
    check_database_compatibility()
    check_specific_issues()
    
    print("=" * 60)
    print("RECOMMENDATIONS:")
    print("=" * 60)
    print("1. Standardize on scripts.models (Minimal models)")
    print("2. Update field names to match database exactly")
    print("3. Handle UUID type conversions at Celery boundaries")
    print("4. Remove conflicting model definitions")
    print()

if __name__ == "__main__":
    main()