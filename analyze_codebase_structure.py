#!/usr/bin/env python3
"""Analyze codebase structure for reorganization"""

import os
import sys
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set

sys.path.insert(0, "/opt/legal-doc-processor")

def analyze_scripts():
    """Analyze all scripts in the scripts directory"""
    
    scripts_dir = Path("/opt/legal-doc-processor/scripts")
    
    # Categories based on context_412 and functionality
    categories = {
        "core_pipeline": [
            "pdf_tasks.py", "production_processor.py", "batch_processor.py",
            "intake_service.py"
        ],
        "core_services": [
            "entity_service.py", "graph_service.py", "project_association.py",
            "document_categorization.py", "semantic_naming.py"
        ],
        "core_storage": [
            "db.py", "rds_utils.py", "cache.py", "s3_storage.py"
        ],
        "core_extractors": [
            "textract_utils.py", "ocr_extraction.py", "chunking_utils.py"
        ],
        "core_config": [
            "config.py", "celery_app.py", "logging_config.py"
        ],
        "core_operational": [
            "status_manager.py", "audit_logger.py", "start_worker.py"
        ],
        "core_models": [
            "models.py"
        ],
        "dev_debug": [],
        "dev_test": [],
        "dev_validation": [],
        "dev_manual": [],
        "dev_migration": [],
        "cli_tools": [],
        "monitoring": [],
        "validation": [],
        "enhancements": [
            "core_enhancements_immediate.py"
        ]
    }
    
    # Scan all Python files
    all_files = defaultdict(list)
    
    for py_file in scripts_dir.rglob("*.py"):
        if py_file.name.startswith("._") or "__pycache__" in str(py_file):
            continue
            
        relative_path = py_file.relative_to(scripts_dir)
        parent_dir = relative_path.parts[0] if len(relative_path.parts) > 1 else ""
        filename = py_file.name
        
        # Categorize based on directory
        if parent_dir == "cli":
            all_files["cli_tools"].append(str(relative_path))
        elif parent_dir == "monitoring":
            all_files["monitoring"].append(str(relative_path))
        elif parent_dir == "validation":
            all_files["validation"].append(str(relative_path))
        elif parent_dir == "core":
            # Core subdirectory files
            if filename in ["models.py", "models_minimal.py"]:
                all_files["core_models"].append(str(relative_path))
            elif filename in ["schemas.py", "pdf_models.py", "schemas_generated.py"]:
                all_files["dev_migration"].append(str(relative_path))  # To be migrated/archived
            else:
                all_files["core_services"].append(str(relative_path))
        elif parent_dir == "services":
            all_files["core_services"].append(str(relative_path))
        elif parent_dir == "utils":
            all_files["enhancements"].append(str(relative_path))
        else:
            # Root level scripts - categorize by name/function
            categorized = False
            
            # Check each category
            for category, scripts in categories.items():
                if filename in scripts:
                    all_files[category].append(str(relative_path))
                    categorized = True
                    break
            
            if not categorized:
                # Pattern-based categorization
                if filename.startswith("check_"):
                    all_files["dev_debug"].append(str(relative_path))
                elif filename.startswith("test_"):
                    all_files["dev_test"].append(str(relative_path))
                elif filename.startswith(("verify_", "validate_")):
                    all_files["dev_validation"].append(str(relative_path))
                elif filename.startswith(("retry_", "manual_", "run_entity")):
                    all_files["dev_manual"].append(str(relative_path))
                elif filename == "monitor_document_complete.py":
                    all_files["dev_debug"].append(str(relative_path))
                elif filename == "api_compatibility.py":
                    all_files["dev_migration"].append(str(relative_path))
                elif filename == "migrate_to_standard_models.py":
                    all_files["dev_migration"].append(str(relative_path))
                else:
                    # Default to enhancements if unclear
                    all_files["enhancements"].append(str(relative_path))
    
    return dict(all_files)

def print_reorganization_plan(categorized_files: Dict[str, List[str]]):
    """Print the reorganization plan"""
    
    print("CODEBASE REORGANIZATION PLAN")
    print("="*60)
    
    # Production categories
    print("\n📦 PRODUCTION RUNTIME")
    production_categories = [
        "core_pipeline", "core_services", "core_storage", 
        "core_extractors", "core_config", "core_operational", 
        "core_models", "enhancements"
    ]
    
    total_production = 0
    for category in production_categories:
        if category in categorized_files and categorized_files[category]:
            print(f"\n{category} ({len(categorized_files[category])} files):")
            for script in sorted(categorized_files[category]):
                print(f"  - {script}")
                total_production += 1
    
    # Development categories
    print("\n\n🛠️  DEVELOPMENT/DEBUG")
    dev_categories = [
        "dev_debug", "dev_test", "dev_validation", 
        "dev_manual", "dev_migration"
    ]
    
    total_dev = 0
    for category in dev_categories:
        if category in categorized_files and categorized_files[category]:
            print(f"\n{category} ({len(categorized_files[category])} files):")
            for script in sorted(categorized_files[category]):
                print(f"  - {script}")
                total_dev += 1
    
    # CLI and monitoring
    print("\n\n🖥️  INTERFACES")
    interface_categories = ["cli_tools", "monitoring", "validation"]
    
    total_interface = 0
    for category in interface_categories:
        if category in categorized_files and categorized_files[category]:
            print(f"\n{category} ({len(categorized_files[category])} files):")
            for script in sorted(categorized_files[category]):
                print(f"  - {script}")
                total_interface += 1
    
    print(f"\n\nSUMMARY:")
    print(f"  Production scripts: {total_production}")
    print(f"  Development scripts: {total_dev}")
    print(f"  Interface scripts: {total_interface}")
    print(f"  TOTAL: {total_production + total_dev + total_interface}")

if __name__ == "__main__":
    categorized = analyze_scripts()
    print_reorganization_plan(categorized)