"""
One-time migration to establish schema conformance.
"""

import click
from pathlib import Path
import shutil
from datetime import datetime
import re

from .conformance_engine import ConformanceEngine


@click.command()
@click.option('--database-url', envvar='DATABASE_URL', required=True)
@click.option('--dry-run', is_flag=True, help='Preview changes without applying')
@click.option('--skip-backup', is_flag=True, help='Skip backing up existing files')
def migrate(database_url: str, dry_run: bool, skip_backup: bool):
    """Migrate existing codebase to use conformant schemas."""
    
    engine = ConformanceEngine(database_url)
    
    # Step 1: Backup existing schemas
    schemas_path = Path('scripts/core/schemas.py')
    if schemas_path.exists() and not skip_backup and not dry_run:
        backup_path = schemas_path.with_suffix(f'.backup.{datetime.now():%Y%m%d_%H%M%S}.py')
        shutil.copy2(schemas_path, backup_path)
        click.echo(f"✅ Backed up existing schemas to: {backup_path}")
    
    # Step 2: Generate new conformant models
    click.echo("🔄 Generating conformant models...")
    generated_path = Path('scripts/core/schemas_generated.py')
    
    if not dry_run:
        engine.generate_models(generated_path)
        click.echo(f"✅ Generated models at: {generated_path}")
    else:
        click.echo(f"   Would generate models at: {generated_path}")
    
    # Step 3: Update imports across codebase
    click.echo("🔄 Scanning for files to update...")
    scripts_dir = Path('scripts')
    
    # Define replacement patterns
    replacements = [
        (r'from scripts\.core\.schemas import', 'from scripts.core.schemas_generated import'),
        (r'from core\.schemas import', 'from core.schemas_generated import'),
        (r'import scripts\.core\.schemas', 'import scripts.core.schemas_generated'),
    ]
    
    updated_files = []
    for py_file in scripts_dir.rglob('*.py'):
        # Skip schema files themselves
        if py_file.name in ('schemas.py', 'schemas_generated.py'):
            continue
        
        # Skip migration and database package files
        if 'database' in py_file.parts and py_file.parent.name == 'database':
            continue
            
        try:
            content = py_file.read_text()
            original = content
            
            # Apply replacements
            for pattern, replacement in replacements:
                content = re.sub(pattern, replacement, content)
            
            if content != original:
                updated_files.append(py_file)
                if not dry_run:
                    py_file.write_text(content)
                    
        except Exception as e:
            click.echo(f"⚠️  Error processing {py_file}: {e}")
    
    # Step 4: Generate Redis schemas
    click.echo("🔄 Generating Redis schemas...")
    redis_path = Path('scripts/cache/redis_schemas.json')
    
    if not dry_run:
        redis_schemas = engine.generate_redis_schemas()
        redis_path.parent.mkdir(exist_ok=True)
        
        import json
        with open(redis_path, 'w') as f:
            json.dump(redis_schemas, f, indent=2)
        click.echo(f"✅ Generated Redis schemas at: {redis_path}")
    else:
        click.echo(f"   Would generate Redis schemas at: {redis_path}")
    
    # Step 5: Validate conformance
    click.echo("\n🔍 Validating conformance...")
    if not dry_run and generated_path.exists():
        issues = engine.check_model_conformance(generated_path)
        if issues:
            click.echo(f"⚠️  Found {len(issues)} conformance issues in generated models")
            for issue in issues[:5]:  # Show first 5 issues
                click.echo(f"   • {issue.table}.{issue.field or '*'}: {issue.details}")
            if len(issues) > 5:
                click.echo(f"   ... and {len(issues) - 5} more")
        else:
            click.echo("✅ Generated models are fully conformant")
    
    # Summary
    click.echo("\n📊 Migration Summary:")
    click.echo(f"  • Tables found: {len(engine.reflector.get_table_names())}")
    click.echo(f"  • Files updated: {len(updated_files)}")
    
    if updated_files and (dry_run or len(updated_files) <= 10):
        click.echo("\n  Updated files:")
        for f in updated_files[:10]:
            click.echo(f"    - {f.relative_to(Path.cwd())}")
        if len(updated_files) > 10:
            click.echo(f"    ... and {len(updated_files) - 10} more")
    
    if dry_run:
        click.echo("\n⚠️  This was a dry run. No changes were made.")
        click.echo("Run without --dry-run to apply changes.")
    else:
        click.echo("\n✅ Migration complete!")
        click.echo("\nNext steps:")
        click.echo("  1. Review generated models in scripts/core/schemas_generated.py")
        click.echo("  2. Run 'python -m scripts.database.cli check' to verify conformance")
        click.echo("  3. Update imports to use schemas_generated instead of schemas")
        click.echo("  4. Run tests to ensure everything works")
        click.echo("  5. Commit changes")


@click.command()
@click.option('--backup-file', type=Path, required=True, help='Path to backup file to restore')
def rollback(backup_file: Path):
    """Rollback to a previous schema backup."""
    if not backup_file.exists():
        click.echo(f"❌ Backup file not found: {backup_file}")
        return
    
    schemas_path = Path('scripts/core/schemas.py')
    
    try:
        shutil.copy2(backup_file, schemas_path)
        click.echo(f"✅ Restored schemas from: {backup_file}")
        
        # Remove generated files
        generated_path = Path('scripts/core/schemas_generated.py')
        if generated_path.exists():
            generated_path.unlink()
            click.echo(f"✅ Removed generated schemas")
            
        redis_path = Path('scripts/cache/redis_schemas.json')
        if redis_path.exists():
            redis_path.unlink()
            click.echo(f"✅ Removed Redis schemas")
            
        click.echo("\n✅ Rollback complete!")
        click.echo("Note: You may need to manually revert import changes in other files.")
        
    except Exception as e:
        click.echo(f"❌ Rollback failed: {e}")


@click.group()
def cli():
    """Schema migration commands."""
    pass


cli.add_command(migrate)
cli.add_command(rollback)


if __name__ == '__main__':
    cli()