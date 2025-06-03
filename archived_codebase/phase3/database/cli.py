"""
CLI commands for schema conformance management.
"""

import click
import json
from pathlib import Path
from typing import Optional
from datetime import datetime
from rich.console import Console
from rich.table import Table

from .conformance_engine import ConformanceStatus
from .conformance_engine_supabase import SupabaseConformanceEngine

console = Console()


@click.group()
def schema():
    """Schema conformance management commands."""
    pass


@schema.command()
@click.option('--model-path', type=Path, default='scripts/core/schemas.py')
@click.option('--output', '-o', type=Path, help='Save detailed report')
def check(model_path: Path, output: Optional[Path]):
    """Check schema conformance between database and models."""
    try:
        engine = SupabaseConformanceEngine()
        issues = engine.check_model_conformance(model_path)
        
        # Display summary
        console.print(f"\n[bold]Schema Conformance Check[/bold]")
        console.print(f"Database: {database_url.split('@')[1].split('/')[0] if '@' in database_url else 'local'}")
        console.print(f"Models: {model_path}")
        
        if not issues:
            console.print("\n✅ [green]All schemas are conformant![/green]")
        else:
            # Group issues by severity
            errors = [i for i in issues if i.severity == 'error']
            warnings = [i for i in issues if i.severity == 'warning']
            
            console.print(f"\n❌ Found {len(errors)} errors, {len(warnings)} warnings")
            
            # Display issues in table
            table = Table(title="Conformance Issues", show_lines=True)
            table.add_column("Table", style="cyan", width=20)
            table.add_column("Field", style="magenta", width=20)
            table.add_column("Issue", style="red", width=20)
            table.add_column("Details", width=50)
            
            for issue in sorted(issues, key=lambda x: (x.severity, x.table, x.field or '')):
                severity_style = "red" if issue.severity == "error" else "yellow"
                table.add_row(
                    issue.table,
                    issue.field or "-",
                    f"[{severity_style}]{issue.status.value}[/{severity_style}]",
                    issue.details
                )
            
            console.print(table)
        
        # Save detailed report
        if output:
            report = {
                'timestamp': datetime.now().isoformat(),
                'database': database_url.split('@')[1].split('/')[0] if '@' in database_url else 'local',
                'model_path': str(model_path),
                'issues': [
                    {
                        'table': i.table,
                        'field': i.field,
                        'status': i.status.value,
                        'details': i.details,
                        'severity': i.severity
                    }
                    for i in issues
                ],
                'summary': {
                    'total_issues': len(issues),
                    'errors': len([i for i in issues if i.severity == 'error']),
                    'warnings': len([i for i in issues if i.severity == 'warning'])
                }
            }
            
            with open(output, 'w') as f:
                json.dump(report, f, indent=2)
            
            console.print(f"\n📄 Detailed report saved to: {output}")
            
    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise click.ClickException(str(e))


@schema.command()
@click.option('--database-url', envvar='DATABASE_URL', required=True)
@click.option('--output', '-o', type=Path, default='scripts/core/schemas_generated.py')
@click.option('--tables', '-t', multiple=True, help='Specific tables to generate')
def generate(database_url: str, output: Path, tables: tuple):
    """Generate Pydantic models from database schema."""
    try:
        engine = ConformanceEngine(database_url)
        
        with console.status("[bold green]Generating models..."):
            engine.generate_models(output, list(tables) if tables else None)
        
        console.print(f"✅ Generated models saved to: {output}")
        
        # Show what was generated
        if tables:
            console.print(f"Generated models for tables: {', '.join(tables)}")
        else:
            table_count = len(engine.reflector.get_table_names())
            console.print(f"Generated models for all {table_count} tables")
            
    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise click.ClickException(str(e))


@schema.command()
@click.option('--database-url', envvar='DATABASE_URL', required=True)
@click.argument('script_path', type=Path)
def validate(database_url: str, script_path: Path):
    """Validate that a script uses correct schema."""
    try:
        engine = ConformanceEngine(database_url)
        issues = engine.validate_script(script_path)
        
        if not issues:
            console.print(f"✅ {script_path} uses valid schema")
        else:
            console.print(f"❌ Found {len(issues)} schema issues in {script_path}")
            for issue in issues:
                console.print(f"  • {issue.details}")
                
    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise click.ClickException(str(e))


@schema.command()
@click.option('--database-url', envvar='DATABASE_URL', required=True)
@click.option('--output', '-o', type=Path, default='scripts/cache/redis_schemas.json')
def export_redis(database_url: str, output: Path):
    """Export schemas for Redis caching."""
    try:
        engine = ConformanceEngine(database_url)
        schemas = engine.generate_redis_schemas()
        
        output.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output, 'w') as f:
            json.dump(schemas, f, indent=2)
        
        console.print(f"✅ Exported Redis schemas to: {output}")
        console.print(f"   Tables exported: {len(schemas)}")
        
    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise click.ClickException(str(e))


@schema.command('list-tables')
@click.option('--database-url', envvar='DATABASE_URL', required=True)
def list_tables(database_url: str):
    """List all tables in the database."""
    try:
        engine = ConformanceEngine(database_url)
        tables = engine.reflector.get_table_names()
        
        console.print(f"\n[bold]Database Tables[/bold]")
        console.print(f"Found {len(tables)} tables:\n")
        
        for table in sorted(tables):
            console.print(f"  • {table}")
            
    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise click.ClickException(str(e))


@schema.command('inspect-table')
@click.option('--database-url', envvar='DATABASE_URL', required=True)
@click.argument('table_name')
def inspect_table(database_url: str, table_name: str):
    """Inspect a specific table's schema."""
    try:
        engine = ConformanceEngine(database_url)
        
        if not engine._table_exists(table_name):
            console.print(f"[red]Table '{table_name}' not found[/red]")
            return
        
        table_info = engine.reflector.reflect_table(table_name)
        
        console.print(f"\n[bold]Table: {table_name}[/bold]")
        
        # Display columns
        console.print("\n[bold]Columns:[/bold]")
        col_table = Table(show_header=True)
        col_table.add_column("Name", style="cyan")
        col_table.add_column("Type", style="green")
        col_table.add_column("Nullable", style="yellow")
        col_table.add_column("Default", style="blue")
        
        for col in table_info['columns']:
            col_table.add_row(
                col['name'],
                str(col['type']),
                "Yes" if col['nullable'] else "No",
                str(col.get('default', '-'))
            )
        
        console.print(col_table)
        
        # Display primary key
        if table_info['primary_key'] and table_info['primary_key']['constrained_columns']:
            console.print(f"\n[bold]Primary Key:[/bold] {', '.join(table_info['primary_key']['constrained_columns'])}")
        
        # Display foreign keys
        if table_info['foreign_keys']:
            console.print("\n[bold]Foreign Keys:[/bold]")
            for fk in table_info['foreign_keys']:
                console.print(f"  • {', '.join(fk['constrained_columns'])} → {fk['referred_table']}.{', '.join(fk['referred_columns'])}")
        
        # Display indexes
        if table_info['indexes']:
            console.print("\n[bold]Indexes:[/bold]")
            for idx in table_info['indexes']:
                unique = " (unique)" if idx['unique'] else ""
                console.print(f"  • {idx['name']}: {', '.join(idx['column_names'])}{unique}")
                
    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise click.ClickException(str(e))


if __name__ == '__main__':
    schema()