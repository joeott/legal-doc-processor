# Context 217: SQLAlchemy-Based Pydantic Conformance Implementation Plan

**Date**: 2025-01-29
**Type**: Technical Implementation Plan
**Status**: PROPOSED
**Model**: Claude Opus 4

## Executive Summary

Based on analysis of SQLAlchemy's reflection and introspection capabilities, this document proposes a comprehensive solution for automatic schema conformance between Supabase (PostgreSQL), Pydantic models, Redis cache structures, and application scripts. The solution leverages SQLAlchemy's mature reflection APIs to create a single source of truth from the database schema.

## Core Architecture

### 1. SQLAlchemy as the Bridge

SQLAlchemy provides robust database introspection through its `Inspector` class and reflection capabilities. We'll use this as the foundation for:

- Database schema discovery
- Type mapping between SQL and Python
- Relationship detection
- Constraint identification

### 2. Key Components

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│    Supabase     │────▶│   SQLAlchemy    │────▶│    Pydantic     │
│   (PostgreSQL)  │     │   Reflection    │     │     Models      │
└─────────────────┘     └─────────────────┘     └─────────────────┘
         │                       │                        │
         │                       ▼                        │
         │              ┌─────────────────┐              │
         └──────────────│  Conformance    │──────────────┘
                        │     Engine      │
                        └─────────────────┘
                                 │
                        ┌────────┴────────┐
                        ▼                 ▼
                ┌─────────────┐   ┌─────────────┐
                │    Redis    │   │   Scripts   │
                │   Schemas   │   │ Validation  │
                └─────────────┘   └─────────────┘
```

## Implementation Plan

### Phase 1: Core Infrastructure

#### 1.1 Schema Reflection Service

```python
# scripts/database/schema_reflection.py
"""
SQLAlchemy-based schema reflection and Pydantic model generation.
"""

from typing import Dict, List, Optional, Any, Type
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path

from sqlalchemy import create_engine, MetaData, inspect
from sqlalchemy.engine import Engine, Inspector
from sqlalchemy.sql.sqltypes import (
    String, Integer, BigInteger, Boolean, DateTime, 
    Date, Time, Float, Numeric, JSON, UUID, Text
)
from pydantic import BaseModel, Field, create_model
from pydantic.fields import FieldInfo

class SchemaReflector:
    """Reflects database schema using SQLAlchemy and generates Pydantic models."""
    
    def __init__(self, database_url: str):
        self.engine = create_engine(database_url)
        self.metadata = MetaData()
        self.inspector: Inspector = inspect(self.engine)
        self._type_mapping = self._initialize_type_mapping()
        
    def _initialize_type_mapping(self) -> Dict[Type, Type]:
        """Map SQLAlchemy types to Python/Pydantic types."""
        return {
            String: str,
            Text: str,
            Integer: int,
            BigInteger: int,
            Boolean: bool,
            DateTime: datetime,
            Date: datetime,
            Time: datetime,
            Float: float,
            Numeric: Decimal,
            JSON: Dict[str, Any],
            UUID: str,  # Pydantic handles UUID strings
        }
    
    def reflect_table(self, table_name: str) -> Dict[str, Any]:
        """Reflect a single table's structure."""
        columns = self.inspector.get_columns(table_name)
        pk_constraint = self.inspector.get_pk_constraint(table_name)
        foreign_keys = self.inspector.get_foreign_keys(table_name)
        indexes = self.inspector.get_indexes(table_name)
        unique_constraints = self.inspector.get_unique_constraints(table_name)
        
        return {
            'name': table_name,
            'columns': columns,
            'primary_key': pk_constraint,
            'foreign_keys': foreign_keys,
            'indexes': indexes,
            'unique_constraints': unique_constraints,
            'comment': self.inspector.get_table_comment(table_name)
        }
    
    def generate_pydantic_model(self, table_name: str) -> Type[BaseModel]:
        """Generate a Pydantic model from table reflection."""
        table_info = self.reflect_table(table_name)
        
        # Build field definitions
        fields = {}
        for column in table_info['columns']:
            field_type = self._get_python_type(column['type'])
            field_default = ... if not column['nullable'] else None
            
            # Handle defaults
            if column.get('default'):
                # SQLAlchemy returns defaults as strings, need parsing
                field_default = self._parse_default(column['default'])
            
            # Create field with proper annotation
            if column['nullable']:
                field_type = Optional[field_type]
            
            fields[column['name']] = (
                field_type,
                Field(
                    default=field_default,
                    description=column.get('comment'),
                    alias=column['name']  # Preserve exact DB names
                )
            )
        
        # Create model class
        model_name = self._table_to_model_name(table_name)
        model = create_model(
            model_name,
            **fields,
            __module__='generated.models'
        )
        
        # Add configuration
        model.__config__ = type('Config', (), {
            'from_attributes': True,
            'populate_by_name': True,
            'json_encoders': {
                datetime: lambda v: v.isoformat(),
                Decimal: lambda v: float(v)
            }
        })
        
        return model
    
    def _get_python_type(self, sql_type: Any) -> Type:
        """Convert SQLAlchemy type to Python type."""
        for sql_class, py_type in self._type_mapping.items():
            if isinstance(sql_type, sql_class):
                return py_type
        # Default to Any for unknown types
        return Any
    
    def _parse_default(self, default_str: str) -> Any:
        """Parse SQLAlchemy default value strings."""
        if default_str.lower() in ('true', 'false'):
            return default_str.lower() == 'true'
        elif default_str.isdigit():
            return int(default_str)
        elif default_str.startswith("'") and default_str.endswith("'"):
            return default_str[1:-1]
        return default_str
    
    def _table_to_model_name(self, table_name: str) -> str:
        """Convert table_name to ModelName."""
        return ''.join(word.capitalize() for word in table_name.split('_'))
```

#### 1.2 Conformance Engine

```python
# scripts/database/conformance_engine.py
"""
Central conformance engine that coordinates schema synchronization.
"""

from typing import Dict, List, Optional, Set, Any
from pathlib import Path
import ast
import importlib.util
from dataclasses import dataclass
from enum import Enum

from .schema_reflection import SchemaReflector
from pydantic import BaseModel


class ConformanceStatus(Enum):
    CONFORMANT = "conformant"
    MISSING_IN_MODEL = "missing_in_model"
    MISSING_IN_DB = "missing_in_db"
    TYPE_MISMATCH = "type_mismatch"
    CONSTRAINT_MISMATCH = "constraint_mismatch"


@dataclass
class ConformanceIssue:
    table: str
    field: Optional[str]
    status: ConformanceStatus
    details: str
    severity: str  # 'error', 'warning', 'info'


class ConformanceEngine:
    """Manages schema conformance across all system components."""
    
    def __init__(self, database_url: str):
        self.reflector = SchemaReflector(database_url)
        self.issues: List[ConformanceIssue] = []
        
    def check_model_conformance(self, model_path: Path) -> List[ConformanceIssue]:
        """Check if Pydantic models match database schema."""
        issues = []
        
        # Load existing models
        existing_models = self._load_pydantic_models(model_path)
        
        # Get all tables from database
        table_names = self.reflector.inspector.get_table_names()
        
        for table_name in table_names:
            model_name = self.reflector._table_to_model_name(table_name)
            
            if model_name not in existing_models:
                issues.append(ConformanceIssue(
                    table=table_name,
                    field=None,
                    status=ConformanceStatus.MISSING_IN_MODEL,
                    details=f"No Pydantic model found for table {table_name}",
                    severity="error"
                ))
                continue
            
            # Compare fields
            db_columns = {col['name']: col for col in 
                         self.reflector.inspector.get_columns(table_name)}
            model_fields = existing_models[model_name].__fields__
            
            # Check each database column
            for col_name, col_info in db_columns.items():
                if col_name not in model_fields:
                    issues.append(ConformanceIssue(
                        table=table_name,
                        field=col_name,
                        status=ConformanceStatus.MISSING_IN_MODEL,
                        details=f"Column {col_name} missing in Pydantic model",
                        severity="error"
                    ))
                else:
                    # Check type compatibility
                    model_field = model_fields[col_name]
                    if not self._types_compatible(col_info, model_field):
                        issues.append(ConformanceIssue(
                            table=table_name,
                            field=col_name,
                            status=ConformanceStatus.TYPE_MISMATCH,
                            details=f"Type mismatch for {col_name}",
                            severity="error"
                        ))
            
            # Check for extra fields in model
            for field_name in model_fields:
                if field_name not in db_columns:
                    issues.append(ConformanceIssue(
                        table=table_name,
                        field=field_name,
                        status=ConformanceStatus.MISSING_IN_DB,
                        details=f"Field {field_name} in model but not in database",
                        severity="warning"
                    ))
        
        return issues
    
    def generate_models(self, output_path: Path, tables: Optional[List[str]] = None):
        """Generate Pydantic models for all or specified tables."""
        if tables is None:
            tables = self.reflector.inspector.get_table_names()
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Generate imports
        imports = [
            "# Auto-generated models from database schema",
            f"# Generated at: {datetime.now().isoformat()}",
            "",
            "from typing import Optional, Dict, Any, List",
            "from datetime import datetime",
            "from decimal import Decimal",
            "from pydantic import BaseModel, Field",
            ""
        ]
        
        models = []
        for table_name in sorted(tables):
            try:
                model = self.reflector.generate_pydantic_model(table_name)
                model_code = self._model_to_code(model, table_name)
                models.append(model_code)
            except Exception as e:
                print(f"Error generating model for {table_name}: {e}")
        
        # Write to file
        with open(output_path, 'w') as f:
            f.write('\n'.join(imports))
            f.write('\n\n'.join(models))
    
    def validate_script(self, script_path: Path) -> List[ConformanceIssue]:
        """Validate that a script uses correct table/column names."""
        issues = []
        
        with open(script_path, 'r') as f:
            tree = ast.parse(f.read())
        
        # Find database operations
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Look for .table() calls
                if (isinstance(node.func, ast.Attribute) and 
                    node.func.attr == 'table' and 
                    len(node.args) > 0 and 
                    isinstance(node.args[0], ast.Str)):
                    
                    table_name = node.args[0].s
                    if not self._table_exists(table_name):
                        issues.append(ConformanceIssue(
                            table=table_name,
                            field=None,
                            status=ConformanceStatus.MISSING_IN_DB,
                            details=f"Table '{table_name}' not found in database",
                            severity="error"
                        ))
        
        return issues
    
    def generate_redis_schemas(self) -> Dict[str, Any]:
        """Generate Redis-compatible schema definitions."""
        schemas = {}
        
        for table_name in self.reflector.inspector.get_table_names():
            table_info = self.reflector.reflect_table(table_name)
            
            # Create simplified schema for Redis
            redis_schema = {
                'table': table_name,
                'primary_key': table_info['primary_key']['constrained_columns'],
                'fields': {},
                'indexes': []
            }
            
            for column in table_info['columns']:
                redis_schema['fields'][column['name']] = {
                    'type': str(column['type']),
                    'nullable': column['nullable'],
                    'indexed': any(column['name'] in idx['column_names'] 
                                 for idx in table_info['indexes'])
                }
            
            schemas[table_name] = redis_schema
        
        return schemas
```

### Phase 2: Integration Layer

#### 2.1 CLI Commands

```python
# scripts/database/cli.py
"""
CLI commands for schema conformance management.
"""

import click
import json
from pathlib import Path
from rich.console import Console
from rich.table import Table

from .conformance_engine import ConformanceEngine, ConformanceStatus

console = Console()


@click.group()
def schema():
    """Schema conformance management commands."""
    pass


@schema.command()
@click.option('--database-url', envvar='DATABASE_URL', required=True)
@click.option('--model-path', type=Path, default='scripts/core/schemas.py')
@click.option('--output', '-o', type=Path, help='Save detailed report')
def check(database_url: str, model_path: Path, output: Optional[Path]):
    """Check schema conformance between database and models."""
    engine = ConformanceEngine(database_url)
    issues = engine.check_model_conformance(model_path)
    
    # Display summary
    console.print(f"\n[bold]Schema Conformance Check[/bold]")
    console.print(f"Database: {database_url.split('@')[1] if '@' in database_url else 'local'}")
    console.print(f"Models: {model_path}")
    
    if not issues:
        console.print("\n✅ [green]All schemas are conformant![/green]")
    else:
        # Group issues by severity
        errors = [i for i in issues if i.severity == 'error']
        warnings = [i for i in issues if i.severity == 'warning']
        
        console.print(f"\n❌ Found {len(errors)} errors, {len(warnings)} warnings")
        
        # Display issues in table
        table = Table(title="Conformance Issues")
        table.add_column("Table", style="cyan")
        table.add_column("Field", style="magenta")
        table.add_column("Issue", style="red")
        table.add_column("Details")
        
        for issue in sorted(issues, key=lambda x: (x.severity, x.table, x.field or '')):
            table.add_row(
                issue.table,
                issue.field or "-",
                issue.status.value,
                issue.details
            )
        
        console.print(table)
    
    # Save detailed report
    if output:
        report = {
            'timestamp': datetime.now().isoformat(),
            'database': database_url.split('@')[1] if '@' in database_url else 'local',
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


@schema.command()
@click.option('--database-url', envvar='DATABASE_URL', required=True)
@click.option('--output', '-o', type=Path, default='scripts/core/schemas_generated.py')
@click.option('--tables', '-t', multiple=True, help='Specific tables to generate')
def generate(database_url: str, output: Path, tables: tuple):
    """Generate Pydantic models from database schema."""
    engine = ConformanceEngine(database_url)
    
    with console.status("[bold green]Generating models..."):
        engine.generate_models(output, list(tables) if tables else None)
    
    console.print(f"✅ Generated models saved to: {output}")
    
    # Show what was generated
    if tables:
        console.print(f"Generated models for tables: {', '.join(tables)}")
    else:
        table_count = len(engine.reflector.inspector.get_table_names())
        console.print(f"Generated models for all {table_count} tables")


@schema.command()
@click.option('--database-url', envvar='DATABASE_URL', required=True)
@click.argument('script_path', type=Path)
def validate(database_url: str, script_path: Path):
    """Validate that a script uses correct schema."""
    engine = ConformanceEngine(database_url)
    issues = engine.validate_script(script_path)
    
    if not issues:
        console.print(f"✅ {script_path} uses valid schema")
    else:
        console.print(f"❌ Found {len(issues)} schema issues in {script_path}")
        for issue in issues:
            console.print(f"  • {issue.details}")


@schema.command()
@click.option('--database-url', envvar='DATABASE_URL', required=True)
@click.option('--output', '-o', type=Path, default='redis_schemas.json')
def export_redis(database_url: str, output: Path):
    """Export schemas for Redis caching."""
    engine = ConformanceEngine(database_url)
    schemas = engine.generate_redis_schemas()
    
    with open(output, 'w') as f:
        json.dump(schemas, f, indent=2)
    
    console.print(f"✅ Exported Redis schemas to: {output}")
```

### Phase 3: Automated Synchronization

#### 3.1 GitHub Actions Workflow

```yaml
# .github/workflows/schema-conformance.yml
name: Schema Conformance Check

on:
  push:
    paths:
      - 'scripts/core/schemas.py'
      - 'scripts/**/*.py'
      - 'supabase/migrations/**'
  pull_request:
    paths:
      - 'scripts/core/schemas.py'
      - 'scripts/**/*.py'
      - 'supabase/migrations/**'

jobs:
  check-conformance:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'
    
    - name: Install dependencies
      run: |
        pip install sqlalchemy pydantic supabase click rich
    
    - name: Check schema conformance
      env:
        DATABASE_URL: ${{ secrets.DATABASE_URL }}
      run: |
        python -m scripts.database.cli check \
          --output conformance-report.json
    
    - name: Upload conformance report
      if: always()
      uses: actions/upload-artifact@v3
      with:
        name: conformance-report
        path: conformance-report.json
    
    - name: Comment PR with issues
      if: github.event_name == 'pull_request' && failure()
      uses: actions/github-script@v6
      with:
        script: |
          const fs = require('fs');
          const report = JSON.parse(fs.readFileSync('conformance-report.json'));
          
          const comment = `## ❌ Schema Conformance Check Failed
          
          Found ${report.summary.errors} errors and ${report.summary.warnings} warnings.
          
          <details>
          <summary>View issues</summary>
          
          ${report.issues.map(i => `- **${i.table}${i.field ? '.' + i.field : ''}**: ${i.details}`).join('\n')}
          
          </details>
          
          Run \`python -m scripts.database.cli generate\` to regenerate models from the database.`;
          
          github.rest.issues.createComment({
            issue_number: context.issue.number,
            owner: context.repo.owner,
            repo: context.repo.repo,
            body: comment
          });
```

### Phase 4: Migration Path

#### 4.1 Initial Migration Script

```python
# scripts/database/migrate_to_conformance.py
"""
One-time migration to establish schema conformance.
"""

import click
from pathlib import Path
import shutil
from datetime import datetime

from .conformance_engine import ConformanceEngine


@click.command()
@click.option('--database-url', envvar='DATABASE_URL', required=True)
@click.option('--dry-run', is_flag=True, help='Preview changes without applying')
def migrate(database_url: str, dry_run: bool):
    """Migrate existing codebase to use conformant schemas."""
    
    engine = ConformanceEngine(database_url)
    
    # Step 1: Backup existing schemas
    schemas_path = Path('scripts/core/schemas.py')
    if schemas_path.exists() and not dry_run:
        backup_path = schemas_path.with_suffix(f'.backup.{datetime.now():%Y%m%d_%H%M%S}')
        shutil.copy2(schemas_path, backup_path)
        click.echo(f"✅ Backed up existing schemas to: {backup_path}")
    
    # Step 2: Generate new conformant models
    click.echo("🔄 Generating conformant models...")
    if not dry_run:
        engine.generate_models(schemas_path)
    
    # Step 3: Update imports across codebase
    click.echo("🔄 Updating imports...")
    scripts_dir = Path('scripts')
    
    replacements = [
        ('from scripts.core.schemas import', 'from scripts.core.schemas_generated import'),
        ('from core.schemas import', 'from core.schemas_generated import'),
    ]
    
    updated_files = []
    for py_file in scripts_dir.rglob('*.py'):
        if py_file.name == 'schemas.py':
            continue
            
        content = py_file.read_text()
        original = content
        
        for old, new in replacements:
            content = content.replace(old, new)
        
        if content != original:
            updated_files.append(py_file)
            if not dry_run:
                py_file.write_text(content)
    
    # Step 4: Generate Redis schemas
    click.echo("🔄 Generating Redis schemas...")
    if not dry_run:
        redis_schemas = engine.generate_redis_schemas()
        redis_path = Path('scripts/cache/redis_schemas.json')
        redis_path.parent.mkdir(exist_ok=True)
        
        import json
        with open(redis_path, 'w') as f:
            json.dump(redis_schemas, f, indent=2)
    
    # Summary
    click.echo("\n📊 Migration Summary:")
    click.echo(f"  • Tables found: {len(engine.reflector.inspector.get_table_names())}")
    click.echo(f"  • Files updated: {len(updated_files)}")
    
    if dry_run:
        click.echo("\n⚠️  This was a dry run. No changes were made.")
        click.echo("Run without --dry-run to apply changes.")
    else:
        click.echo("\n✅ Migration complete!")
        click.echo("Next steps:")
        click.echo("  1. Review generated models in scripts/core/schemas_generated.py")
        click.echo("  2. Run tests to ensure everything works")
        click.echo("  3. Commit changes")


if __name__ == '__main__':
    migrate()
```

## Benefits Over Manual Approach

1. **Automatic Type Mapping**: SQLAlchemy handles complex PostgreSQL types correctly
2. **Relationship Detection**: Foreign keys automatically discovered
3. **Constraint Preservation**: Check constraints, unique constraints maintained
4. **Index Awareness**: Performance-critical indexes identified
5. **Migration Safety**: Automated backup and rollback capabilities

## Implementation Timeline

### Week 1: Core Infrastructure
- Implement SchemaReflector with SQLAlchemy
- Create ConformanceEngine
- Basic CLI commands

### Week 2: Integration
- Script validation
- Redis schema generation
- Import migration

### Week 3: Automation
- CI/CD integration
- Automated tests
- Documentation

### Week 4: Rollout
- Team training
- Gradual migration
- Monitoring setup

## Risk Mitigation

1. **Backup Strategy**: All changes create timestamped backups
2. **Dry Run Mode**: Preview all changes before applying
3. **Incremental Migration**: Can migrate table by table
4. **Rollback Plan**: Restore from backups if needed

## Conclusion

This SQLAlchemy-based approach provides:
- **Single source of truth**: Database schema drives everything
- **Type safety**: Proper type mapping throughout the stack
- **Automation**: Minimal manual intervention required
- **Scalability**: Handles schema evolution gracefully
- **Industry standard**: Leverages battle-tested SQLAlchemy

The solution transforms schema management from a reactive debugging exercise to a proactive, automated process that maintains consistency across all system components.