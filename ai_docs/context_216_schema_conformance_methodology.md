# Context 216: Schema Conformance Methodology and Solution

**Date**: 2025-01-29
**Type**: Architecture Solution / Development Methodology
**Status**: PROPOSED

## Problem Analysis

### Root Causes of Schema Drift

1. **Multiple Sources of Truth**
   - Supabase database (actual schema)
   - Pydantic models (expected schema)
   - Redis cache structures
   - Script hardcoded assumptions
   - AI documentation definitions

2. **Lack of Visibility**
   - No automated way to compare schemas across systems
   - Schema changes not propagated automatically
   - Developers unaware of actual database structure

3. **Manual Synchronization**
   - Schema updates require manual changes in multiple places
   - Easy to miss updating one component
   - No validation that all components match

4. **Temporal Drift**
   - Schemas evolve over time
   - Documentation becomes outdated
   - Cache schemas diverge from reality

## Proposed Solution: Schema Conformance System

### Core Principles

1. **Database as Single Source of Truth**: The Supabase database schema is authoritative
2. **Automated Generation**: Pydantic models generated from database schema
3. **Runtime Validation**: Verify schema compatibility before operations
4. **Continuous Monitoring**: Detect and alert on schema drift

### Implementation Components

#### 1. Schema Introspection Service

```python
#!/usr/bin/env python3
"""
Schema Conformance Manager
Ensures all system components use consistent schemas derived from the database.
"""

import json
from typing import Dict, List, Any, Optional
from datetime import datetime
import click
from dataclasses import dataclass
from enum import Enum

from supabase import create_client
from pydantic import BaseModel, Field


class SchemaSource(Enum):
    DATABASE = "database"
    PYDANTIC = "pydantic"
    REDIS = "redis"
    SCRIPTS = "scripts"
    DOCUMENTATION = "documentation"


@dataclass
class SchemaField:
    name: str
    data_type: str
    nullable: bool
    default: Optional[Any] = None
    constraints: List[str] = None


@dataclass
class SchemaDefinition:
    source: SchemaSource
    table_name: str
    fields: Dict[str, SchemaField]
    relationships: Dict[str, str] = None
    last_updated: datetime = None


class SchemaConformanceManager:
    """Manages schema conformance across all system components."""
    
    def __init__(self):
        self.supabase = self._get_supabase_client()
        self.schemas: Dict[str, Dict[SchemaSource, SchemaDefinition]] = {}
        
    def _get_supabase_client(self):
        """Initialize Supabase client."""
        import os
        from dotenv import load_dotenv
        load_dotenv()
        
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_ANON_KEY")
        return create_client(url, key)
    
    def introspect_database_schema(self) -> Dict[str, SchemaDefinition]:
        """Extract actual schema from Supabase database."""
        # Query information schema
        query = """
        SELECT 
            t.table_name,
            c.column_name,
            c.data_type,
            c.is_nullable,
            c.column_default,
            c.character_maximum_length,
            tc.constraint_type
        FROM information_schema.tables t
        JOIN information_schema.columns c 
            ON t.table_name = c.table_name 
            AND t.table_schema = c.table_schema
        LEFT JOIN information_schema.constraint_column_usage ccu
            ON c.column_name = ccu.column_name 
            AND c.table_name = ccu.table_name
        LEFT JOIN information_schema.table_constraints tc
            ON ccu.constraint_name = tc.constraint_name
        WHERE t.table_schema = 'public'
        AND t.table_type = 'BASE TABLE'
        ORDER BY t.table_name, c.ordinal_position;
        """
        
        result = self.supabase.rpc('sql_query', {'query': query}).execute()
        
        # Parse results into schema definitions
        schemas = {}
        for row in result.data:
            table_name = row['table_name']
            if table_name not in schemas:
                schemas[table_name] = SchemaDefinition(
                    source=SchemaSource.DATABASE,
                    table_name=table_name,
                    fields={},
                    last_updated=datetime.now()
                )
            
            field = SchemaField(
                name=row['column_name'],
                data_type=row['data_type'],
                nullable=row['is_nullable'] == 'YES',
                default=row['column_default'],
                constraints=[row['constraint_type']] if row['constraint_type'] else []
            )
            
            schemas[table_name].fields[row['column_name']] = field
        
        return schemas
    
    def extract_pydantic_schema(self) -> Dict[str, SchemaDefinition]:
        """Extract schema from Pydantic models."""
        from scripts.core import schemas
        import inspect
        
        schemas_dict = {}
        
        # Find all Pydantic models
        for name, obj in inspect.getmembers(schemas):
            if inspect.isclass(obj) and issubclass(obj, BaseModel):
                # Map model to table name
                table_name = self._model_to_table_name(name)
                if table_name:
                    schema_def = SchemaDefinition(
                        source=SchemaSource.PYDANTIC,
                        table_name=table_name,
                        fields={},
                        last_updated=datetime.now()
                    )
                    
                    # Extract fields from model
                    for field_name, field_info in obj.model_fields.items():
                        field = SchemaField(
                            name=field_info.alias or field_name,
                            data_type=str(field_info.annotation),
                            nullable=not field_info.is_required(),
                            default=field_info.default
                        )
                        schema_def.fields[field_name] = field
                    
                    schemas_dict[table_name] = schema_def
        
        return schemas_dict
    
    def _model_to_table_name(self, model_name: str) -> Optional[str]:
        """Map Pydantic model name to database table name."""
        mappings = {
            'ProjectModel': 'projects',
            'DocumentModel': 'documents',
            'ImportSessionModel': 'import_sessions',
            'ProcessingPipelineModel': 'processing_pipeline',
            'ProcessingQueueModel': 'processing_queue',
            'DocumentChunkModel': 'document_chunks',
            'EntityMentionModel': 'entity_mentions',
            'CanonicalEntityModel': 'canonical_entities',
            'RelationshipStagingModel': 'relationship_staging',
            'ProcessingMetricsModel': 'processing_metrics'
        }
        return mappings.get(model_name)
    
    def compare_schemas(self, table_name: str) -> Dict[str, Any]:
        """Compare schemas from different sources for a table."""
        comparisons = {
            'table': table_name,
            'discrepancies': [],
            'missing_in_pydantic': [],
            'missing_in_database': [],
            'type_mismatches': []
        }
        
        db_schema = self.schemas.get(table_name, {}).get(SchemaSource.DATABASE)
        py_schema = self.schemas.get(table_name, {}).get(SchemaSource.PYDANTIC)
        
        if not db_schema or not py_schema:
            comparisons['error'] = f"Schema not found for {table_name}"
            return comparisons
        
        # Check fields in database
        for field_name, db_field in db_schema.fields.items():
            if field_name not in py_schema.fields:
                comparisons['missing_in_pydantic'].append({
                    'field': field_name,
                    'type': db_field.data_type,
                    'nullable': db_field.nullable
                })
            else:
                # Compare types
                py_field = py_schema.fields[field_name]
                if not self._types_compatible(db_field.data_type, py_field.data_type):
                    comparisons['type_mismatches'].append({
                        'field': field_name,
                        'database_type': db_field.data_type,
                        'pydantic_type': py_field.data_type
                    })
        
        # Check fields in Pydantic
        for field_name, py_field in py_schema.fields.items():
            if field_name not in db_schema.fields:
                comparisons['missing_in_database'].append({
                    'field': field_name,
                    'type': py_field.data_type,
                    'nullable': py_field.nullable
                })
        
        return comparisons
    
    def _types_compatible(self, db_type: str, py_type: str) -> bool:
        """Check if database and Pydantic types are compatible."""
        type_mappings = {
            'uuid': ['UUID', 'str'],
            'text': ['str'],
            'varchar': ['str'],
            'integer': ['int'],
            'bigint': ['int'],
            'boolean': ['bool'],
            'timestamp': ['datetime'],
            'jsonb': ['dict', 'Dict', 'Any']
        }
        
        db_type_lower = db_type.lower()
        for db_t, py_types in type_mappings.items():
            if db_t in db_type_lower:
                return any(py_t in py_type for py_t in py_types)
        
        return False
    
    def generate_pydantic_models(self, output_path: str = None):
        """Generate Pydantic models from database schema."""
        output = []
        output.append("# Auto-generated Pydantic models from database schema")
        output.append("# Generated at: " + datetime.now().isoformat())
        output.append("")
        output.append("from pydantic import BaseModel, Field")
        output.append("from typing import Optional, Dict, Any, List")
        output.append("from datetime import datetime")
        output.append("from uuid import UUID")
        output.append("")
        
        db_schemas = self.introspect_database_schema()
        
        for table_name, schema in db_schemas.items():
            # Convert table name to model name
            model_name = ''.join(word.capitalize() for word in table_name.split('_'))
            model_name += 'Model'
            
            output.append(f"class {model_name}(BaseModel):")
            output.append(f'    """Auto-generated model for {table_name} table."""')
            
            # Generate fields
            for field_name, field in schema.fields.items():
                py_type = self._db_type_to_python(field.data_type)
                if field.nullable:
                    py_type = f"Optional[{py_type}]"
                
                default = " = None" if field.nullable else ""
                alias = f', alias="{field_name}"' if '_' in field_name else ""
                
                output.append(f"    {field_name}: {py_type}{default} = Field(...{alias})")
            
            output.append("")
            output.append("    class Config:")
            output.append("        from_attributes = True")
            output.append("")
        
        model_code = '\n'.join(output)
        
        if output_path:
            with open(output_path, 'w') as f:
                f.write(model_code)
        
        return model_code
    
    def _db_type_to_python(self, db_type: str) -> str:
        """Convert database type to Python type."""
        type_map = {
            'uuid': 'UUID',
            'text': 'str',
            'character varying': 'str',
            'integer': 'int',
            'bigint': 'int',
            'boolean': 'bool',
            'timestamp': 'datetime',
            'jsonb': 'Dict[str, Any]',
            'json': 'Dict[str, Any]'
        }
        
        db_type_lower = db_type.lower()
        for db_t, py_t in type_map.items():
            if db_t in db_type_lower:
                return py_t
        
        return 'Any'
    
    def validate_script_usage(self, script_path: str) -> List[Dict[str, Any]]:
        """Validate that a script uses correct schema."""
        issues = []
        
        with open(script_path, 'r') as f:
            content = f.read()
        
        # Look for table operations
        import re
        
        # Find Supabase table operations
        table_ops = re.findall(r'\.table\([\'"](\w+)[\'"]\)', content)
        for table in table_ops:
            if table not in self.schemas:
                issues.append({
                    'type': 'unknown_table',
                    'table': table,
                    'line': self._find_line_number(content, f".table('{table}')")
                })
        
        # Find column references
        column_refs = re.findall(r'[\'"](\w+)[\'"]:\s*[^,\}]+[,\}]', content)
        
        # More sophisticated validation would parse AST
        
        return issues
    
    def generate_conformance_report(self) -> Dict[str, Any]:
        """Generate comprehensive conformance report."""
        report = {
            'timestamp': datetime.now().isoformat(),
            'tables': {},
            'summary': {
                'total_tables': 0,
                'conformant_tables': 0,
                'issues_found': 0
            }
        }
        
        # Load all schemas
        self.schemas = {}
        db_schemas = self.introspect_database_schema()
        py_schemas = self.extract_pydantic_schema()
        
        for table_name in db_schemas:
            self.schemas[table_name] = {
                SchemaSource.DATABASE: db_schemas[table_name]
            }
        
        for table_name in py_schemas:
            if table_name not in self.schemas:
                self.schemas[table_name] = {}
            self.schemas[table_name][SchemaSource.PYDANTIC] = py_schemas[table_name]
        
        # Compare all tables
        for table_name in self.schemas:
            comparison = self.compare_schemas(table_name)
            report['tables'][table_name] = comparison
            
            # Update summary
            report['summary']['total_tables'] += 1
            if not any([comparison.get('missing_in_pydantic'),
                       comparison.get('missing_in_database'),
                       comparison.get('type_mismatches')]):
                report['summary']['conformant_tables'] += 1
            else:
                report['summary']['issues_found'] += sum([
                    len(comparison.get('missing_in_pydantic', [])),
                    len(comparison.get('missing_in_database', [])),
                    len(comparison.get('type_mismatches', []))
                ])
        
        return report


# CLI Commands
@click.group()
def cli():
    """Schema conformance management tools."""
    pass


@cli.command()
@click.option('--output', '-o', help='Output file for report')
def check():
    """Check schema conformance across all components."""
    manager = SchemaConformanceManager()
    report = manager.generate_conformance_report()
    
    # Display summary
    click.echo(f"Schema Conformance Report - {report['timestamp']}")
    click.echo("=" * 60)
    click.echo(f"Total tables: {report['summary']['total_tables']}")
    click.echo(f"Conformant tables: {report['summary']['conformant_tables']}")
    click.echo(f"Total issues: {report['summary']['issues_found']}")
    click.echo("")
    
    # Display issues by table
    for table_name, comparison in report['tables'].items():
        issues = []
        if comparison.get('missing_in_pydantic'):
            issues.extend([f"Missing in Pydantic: {f['field']}" 
                          for f in comparison['missing_in_pydantic']])
        if comparison.get('missing_in_database'):
            issues.extend([f"Missing in Database: {f['field']}" 
                          for f in comparison['missing_in_database']])
        if comparison.get('type_mismatches'):
            issues.extend([f"Type mismatch: {f['field']}" 
                          for f in comparison['type_mismatches']])
        
        if issues:
            click.echo(f"❌ {table_name}:")
            for issue in issues:
                click.echo(f"   • {issue}")
        else:
            click.echo(f"✅ {table_name}: OK")
    
    # Save detailed report
    if output:
        with open(output, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        click.echo(f"\nDetailed report saved to: {output}")


@cli.command()
@click.option('--output', '-o', default='generated_models.py', help='Output file')
def generate():
    """Generate Pydantic models from database schema."""
    manager = SchemaConformanceManager()
    code = manager.generate_pydantic_models(output)
    click.echo(f"✅ Generated Pydantic models saved to: {output}")
    click.echo("\nPreview:")
    click.echo("-" * 40)
    click.echo(code[:500] + "...")


@cli.command()
@click.argument('script_path')
def validate_script(script_path):
    """Validate that a script uses correct schema."""
    manager = SchemaConformanceManager()
    issues = manager.validate_script_usage(script_path)
    
    if issues:
        click.echo(f"❌ Found {len(issues)} issues in {script_path}:")
        for issue in issues:
            click.echo(f"   • {issue['type']}: {issue.get('table', 'unknown')}")
    else:
        click.echo(f"✅ No schema issues found in {script_path}")


@cli.command()
def sync():
    """Synchronize all schemas to match database."""
    manager = SchemaConformanceManager()
    
    # Generate new models
    click.echo("🔄 Generating Pydantic models from database...")
    manager.generate_pydantic_models('scripts/core/schemas_generated.py')
    
    # Update Redis schemas
    click.echo("🔄 Updating Redis cache schemas...")
    # Implementation would update Redis cache structures
    
    # Generate migration report
    click.echo("📝 Generating migration report...")
    report = manager.generate_conformance_report()
    
    with open('schema_migration_report.json', 'w') as f:
        json.dump(report, f, indent=2, default=str)
    
    click.echo("✅ Schema synchronization complete")


if __name__ == '__main__':
    cli()
```

### Implementation Strategy

#### Phase 1: Discovery (Immediate)
1. Run introspection to understand current state
2. Generate conformance report
3. Identify all discrepancies

#### Phase 2: Alignment (Short-term)
1. Generate correct Pydantic models from database
2. Update all scripts to use generated models
3. Fix Redis cache structures

#### Phase 3: Enforcement (Long-term)
1. CI/CD checks for schema conformance
2. Automated model regeneration on migration
3. Runtime validation before operations

### Key Benefits

1. **Single Source of Truth**: Database schema drives everything
2. **Automated Synchronization**: No manual updates needed
3. **Early Detection**: Catch mismatches before runtime
4. **Documentation**: Auto-generated, always current
5. **Type Safety**: Proper types throughout the system

### Migration Path

1. **Run Conformance Check**: Identify all current issues
2. **Generate Models**: Create correct Pydantic models
3. **Update Imports**: Point scripts to generated models
4. **Fix Scripts**: Update hardcoded column names
5. **Validate**: Ensure all operations work

### Monitoring and Maintenance

1. **Pre-deployment Checks**: Validate schema conformance
2. **Post-migration Hooks**: Regenerate models after DB changes
3. **Alerting**: Notify on schema drift detection
4. **Regular Audits**: Weekly conformance reports

## Conclusion

The root problem is **lack of automated schema synchronization**. This solution provides:
- Visibility into actual schemas
- Automated conformance checking
- Single source of truth enforcement
- Continuous validation

This moves us from reactive fixes to proactive prevention of schema drift.