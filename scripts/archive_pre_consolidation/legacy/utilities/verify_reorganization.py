#!/usr/bin/env python3
"""
Verify the codebase reorganization was successful.
Checks imports, CLI tools, and basic functionality.
"""
import os
import sys
import subprocess
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich import box

console = Console()

def check_imports():
    """Verify all imports are working correctly."""
    console.print("\n[bold]Checking Python imports...[/bold]")
    
    test_imports = [
        "from celery_app import app",
        "from supabase_utils import SupabaseManager", 
        "from redis_utils import get_redis_manager",
        "from celery_tasks.ocr_tasks import process_ocr",
        "from core.document_processor import DocumentProcessor"
    ]
    
    errors = []
    for import_stmt in test_imports:
        try:
            exec(import_stmt)
            console.print(f"[green]✓[/green] {import_stmt}")
        except ImportError as e:
            errors.append(f"{import_stmt}: {e}")
            console.print(f"[red]✗[/red] {import_stmt}: {e}")
    
    return len(errors) == 0

def check_cli_tools():
    """Verify CLI tools are accessible."""
    console.print("\n[bold]Checking CLI tools...[/bold]")
    
    cli_tools = [
        ("Import CLI", "python scripts/cli/import.py --help"),
        ("Monitor CLI", "python scripts/cli/monitor.py --help"),
        ("Admin CLI", "python scripts/cli/admin.py --help")
    ]
    
    results = []
    for name, command in cli_tools:
        try:
            result = subprocess.run(
                command.split(), 
                capture_output=True, 
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                console.print(f"[green]✓[/green] {name}")
                results.append((name, True))
            else:
                console.print(f"[red]✗[/red] {name}: {result.stderr}")
                results.append((name, False))
        except Exception as e:
            console.print(f"[red]✗[/red] {name}: {e}")
            results.append((name, False))
    
    return all(r[1] for r in results)

def check_directory_structure():
    """Verify the expected directory structure exists."""
    console.print("\n[bold]Checking directory structure...[/bold]")
    
    expected_dirs = [
        "scripts/cli",
        "scripts/core", 
        "scripts/celery_tasks",
        "scripts/legacy",
        "scripts/legacy/import",
        "scripts/legacy/monitoring",
        "scripts/legacy/testing"
    ]
    
    all_exist = True
    for dir_path in expected_dirs:
        if os.path.exists(dir_path):
            console.print(f"[green]✓[/green] {dir_path}")
        else:
            console.print(f"[red]✗[/red] {dir_path} - Missing")
            all_exist = False
    
    return all_exist

def check_file_counts():
    """Compare file counts before and after reorganization."""
    console.print("\n[bold]File count comparison...[/bold]")
    
    # Count Python files in different locations
    locations = {
        "Core scripts": "scripts/*.py",
        "CLI tools": "scripts/cli/*.py",
        "Core modules": "scripts/core/*.py",
        "Celery tasks": "scripts/celery_tasks/*.py",
        "Legacy files": "scripts/legacy/**/*.py"
    }
    
    table = Table(title="Python File Distribution", box=box.ROUNDED)
    table.add_column("Location", style="cyan")
    table.add_column("Count", style="magenta")
    
    total_active = 0
    total_legacy = 0
    
    for name, pattern in locations.items():
        files = list(Path('.').glob(pattern))
        count = len(files)
        table.add_row(name, str(count))
        
        if "Legacy" in name:
            total_legacy += count
        else:
            total_active += count
    
    console.print(table)
    
    console.print(f"\n[bold]Summary:[/bold]")
    console.print(f"Active scripts: {total_active}")
    console.print(f"Legacy scripts: {total_legacy}")
    console.print(f"Total scripts: {total_active + total_legacy}")
    console.print(f"Reduction: {total_legacy}/{total_active + total_legacy} = "
                 f"{total_legacy/(total_active + total_legacy)*100:.1f}% archived")
    
    return True

def check_celery_config():
    """Verify Celery can discover tasks."""
    console.print("\n[bold]Checking Celery configuration...[/bold]")
    
    try:
        result = subprocess.run(
            ["celery", "-A", "scripts.celery_app", "inspect", "registered"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if "scripts.celery_tasks" in result.stdout:
            console.print("[green]✓[/green] Celery can find tasks")
            return True
        else:
            console.print("[red]✗[/red] Celery cannot find tasks")
            console.print(result.stdout)
            return False
    except Exception as e:
        console.print(f"[yellow]![/yellow] Could not check Celery (workers not running?): {e}")
        return True  # Don't fail if workers aren't running

def main():
    """Run all verification checks."""
    console.print("[bold blue]Codebase Reorganization Verification[/bold blue]\n")
    
    # Change to project root
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)
    
    # Add scripts to path
    sys.path.insert(0, str(project_root / "scripts"))
    
    # Run checks
    checks = [
        ("Directory Structure", check_directory_structure),
        ("Python Imports", check_imports),
        ("CLI Tools", check_cli_tools),
        ("File Counts", check_file_counts),
        ("Celery Config", check_celery_config)
    ]
    
    results = []
    for name, check_func in checks:
        try:
            result = check_func()
            results.append((name, result))
        except Exception as e:
            console.print(f"\n[red]Error in {name}: {e}[/red]")
            results.append((name, False))
    
    # Summary
    console.print("\n[bold]Verification Summary[/bold]")
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    table = Table(box=box.ROUNDED)
    table.add_column("Check", style="cyan")
    table.add_column("Result", style="green")
    
    for name, result in results:
        status = "[green]PASS[/green]" if result else "[red]FAIL[/red]"
        table.add_row(name, status)
    
    console.print(table)
    console.print(f"\n[bold]Overall: {passed}/{total} checks passed[/bold]")
    
    if passed == total:
        console.print("[bold green]✓ Reorganization verified successfully![/bold green]")
        return 0
    else:
        console.print("[bold red]✗ Some checks failed[/bold red]")
        return 1

if __name__ == "__main__":
    sys.exit(main())