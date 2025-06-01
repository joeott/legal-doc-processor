"""
Supabase-compatible conformance engine that uses REST API introspection.
"""

from typing import Dict, List, Optional, Set, Any, Type, Union
from pathlib import Path
import ast
import importlib.util
from dataclasses import dataclass
from enum import Enum
from datetime import datetime
from decimal import Decimal

from .supabase_introspector import SupabaseIntrospector
from .conformance_engine import ConformanceStatus, ConformanceIssue
from pydantic import BaseModel


class SupabaseConformanceEngine:
    """Manages schema conformance using Supabase REST API introspection."""
    
    def __init__(self):
        self.introspector = SupabaseIntrospector()
        self.issues: List[ConformanceIssue] = []
        
    def check_model_conformance(self, model_path: Path) -> List[ConformanceIssue]:
        """Check if Pydantic models match database schema."""
        issues = []
        
        # Test connection first
        if not self.introspector.test_connection():
            issues.append(ConformanceIssue(
                table="",
                field=None,
                status=ConformanceStatus.MISSING_IN_DB,
                details="Cannot connect to Supabase. Check SUPABASE_URL and SUPABASE_KEY",
                severity="error"
            ))
            return issues
        
        # Load existing models
        existing_models = self._load_pydantic_models(model_path)
        
        # Get all tables from introspector
        table_names = self.introspector.get_table_names()
        
        for table_name in table_names:
            model_name = self.introspector._table_to_model_name(table_name)
            
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
            try:
                db_columns = {col['column_name']: col for col in 
                             self.introspector.get_columns(table_name)}
            except ValueError as e:
                issues.append(ConformanceIssue(
                    table=table_name,
                    field=None,
                    status=ConformanceStatus.MISSING_IN_DB,
                    details=str(e),
                    severity="error"
                ))
                continue
            
            # Get model fields (handle both Pydantic v1 and v2)
            model = existing_models[model_name]
            model_fields = model.model_fields if hasattr(model, 'model_fields') else model.__fields__
            
            # Check each database column
            for col_name, col_info in db_columns.items():
                # Find matching field (check both name and alias)
                model_field = None
                for field_name, field in model_fields.items():
                    field_alias = getattr(field, 'alias', None) if hasattr(field, 'alias') else None
                    if field_name == col_name or field_alias == col_name:
                        model_field = field
                        break
                
                if model_field is None:
                    issues.append(ConformanceIssue(
                        table=table_name,
                        field=col_name,
                        status=ConformanceStatus.MISSING_IN_MODEL,
                        details=f"Column {col_name} missing in Pydantic model",
                        severity="error"
                    ))
                else:
                    # Check type compatibility
                    if not self._types_compatible(col_info, model_field):
                        issues.append(ConformanceIssue(
                            table=table_name,
                            field=col_name,
                            status=ConformanceStatus.TYPE_MISMATCH,
                            details=f"Type mismatch for {col_name}",
                            severity="error"
                        ))
            
            # Check for extra fields in model
            for field_name, field in model_fields.items():
                field_alias = getattr(field, 'alias', None) if hasattr(field, 'alias') else None
                field_db_name = field_alias if field_alias else field_name
                
                if field_db_name not in db_columns:
                    # Skip computed fields and relationships
                    if not field_name.endswith('_collection') and not field_name.startswith('_'):
                        issues.append(ConformanceIssue(
                            table=table_name,
                            field=field_name,
                            status=ConformanceStatus.MISSING_IN_DB,
                            details=f"Field {field_name} in model but not in database",
                            severity="warning"
                        ))
        
        # Check for models without corresponding tables
        for model_name, model in existing_models.items():
            # Try to find corresponding table name
            possible_table_names = [
                # Convert ModelName to table_name
                '_'.join(word.lower() for word in 
                        ''.join(c if c.isupper() else f' {c}' for c in model_name).split()),
                # Handle special cases
                model_name.lower(),
                model_name.lower() + 's',  # Pluralized
            ]
            
            found = False
            for table_name in possible_table_names:
                if table_name in table_names:
                    found = True
                    break
            
            if not found:
                issues.append(ConformanceIssue(
                    table=model_name,
                    field=None,
                    status=ConformanceStatus.MISSING_IN_DB,
                    details=f"Model {model_name} has no corresponding table",
                    severity="warning"
                ))
        
        return issues
    
    def _load_pydantic_models(self, model_path: Path) -> Dict[str, Type[BaseModel]]:
        """Load Pydantic models from a Python file."""
        models = {}
        
        if not model_path.exists():
            return models
        
        # Load the module
        spec = importlib.util.spec_from_file_location("models", model_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Find all BaseModel subclasses
            for name in dir(module):
                obj = getattr(module, name)
                if (isinstance(obj, type) and 
                    issubclass(obj, BaseModel) and 
                    obj is not BaseModel):
                    models[name] = obj
        
        return models
    
    def _types_compatible(self, db_column: Dict[str, Any], model_field: Any) -> bool:
        """Check if database and Pydantic types are compatible."""
        # Get the database type
        db_type_str = str(db_column['data_type']).lower()
        
        # Get the model field type
        field_type = model_field.annotation
        
        # Handle optional types
        is_optional = False
        if hasattr(field_type, '__origin__'):
            origin = field_type.__origin__
            if origin is Union:
                # Extract non-None types
                args = field_type.__args__
                inner_types = [t for t in args if t is not type(None)]
                if len(inner_types) == 1:
                    field_type = inner_types[0]
                    is_optional = True
        
        # Check nullability matches
        db_nullable = db_column['is_nullable'] == 'YES'
        if db_nullable != is_optional:
            return False
        
        # Map database types to expected Python types
        type_mappings = {
            'uuid': [str],
            'text': [str],
            'varchar': [str],
            'char': [str],
            'integer': [int],
            'bigint': [int],
            'smallint': [int],
            'boolean': [bool],
            'bool': [bool],
            'timestamp': [datetime, str],
            'timestamptz': [datetime, str],
            'date': [datetime, str],
            'jsonb': [dict, Dict, Any],
            'json': [dict, Dict, Any],
            'numeric': [float, Decimal, int],
            'decimal': [float, Decimal],
            'real': [float],
            'double': [float],
            'float': [float]
        }
        
        # Check type compatibility
        for db_pattern, py_types in type_mappings.items():
            if db_pattern in db_type_str:
                field_type_name = getattr(field_type, '__name__', str(field_type))
                return (field_type in py_types or 
                       field_type_name in [getattr(t, '__name__', str(t)) for t in py_types])
        
        return True  # Default to compatible for unknown types
    
    def generate_models(self, output_path: Path, tables: Optional[List[str]] = None):
        """Generate Pydantic models for all or specified tables."""
        if tables is None:
            tables = self.introspector.get_table_names()
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Generate imports
        imports = [
            "# Auto-generated models from Supabase schema",
            f"# Generated at: {datetime.now().isoformat()}",
            "# DO NOT EDIT MANUALLY - Use 'python -m scripts.database.cli generate' to regenerate",
            "",
            "from typing import Optional, Dict, Any, List, Union",
            "from datetime import datetime",
            "from decimal import Decimal",
            "from pydantic import BaseModel, Field",
            ""
        ]
        
        models = []
        for table_name in sorted(tables):
            try:
                model = self.introspector.generate_pydantic_model(table_name)
                model_code = self.introspector._model_to_code(model, table_name)
                models.append(model_code)
            except Exception as e:
                print(f"Error generating model for {table_name}: {e}")
        
        # Write to file
        with open(output_path, 'w') as f:
            f.write('\n'.join(imports))
            f.write('\n\n'.join(models))
            f.write('\n')  # End with newline
    
    def validate_script(self, script_path: Path) -> List[ConformanceIssue]:
        """Validate that a script uses correct table/column names."""
        issues = []
        
        with open(script_path, 'r') as f:
            content = f.read()
            
        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            issues.append(ConformanceIssue(
                table="",
                field=None,
                status=ConformanceStatus.MISSING_IN_DB,
                details=f"Syntax error in script: {e}",
                severity="error"
            ))
            return issues
        
        # Get all table names
        valid_tables = set(self.introspector.get_table_names())
        
        # Find database operations
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Look for .table() calls
                if (isinstance(node.func, ast.Attribute) and 
                    node.func.attr == 'table' and 
                    len(node.args) > 0):
                    
                    # Extract table name from first argument
                    table_name = None
                    if hasattr(ast, 'Str') and isinstance(node.args[0], ast.Str):
                        table_name = node.args[0].s
                    elif isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        table_name = node.args[0].value
                    
                    if table_name and table_name not in valid_tables:
                        issues.append(ConformanceIssue(
                            table=table_name,
                            field=None,
                            status=ConformanceStatus.MISSING_IN_DB,
                            details=f"Table '{table_name}' not found in database (line {node.lineno})",
                            severity="error"
                        ))
        
        return issues
    
    def generate_redis_schemas(self) -> Dict[str, Any]:
        """Generate Redis-compatible schema definitions."""
        schemas = {}
        
        for table_name in self.introspector.get_table_names():
            table_info = self.introspector.reflect_table(table_name)
            
            # Create simplified schema for Redis
            redis_schema = {
                'table': table_name,
                'primary_key': table_info['primary_key']['constrained_columns'] if table_info['primary_key'] else [],
                'fields': {},
                'indexes': []
            }
            
            # Add field information
            for column in table_info['columns']:
                redis_schema['fields'][column['column_name']] = {
                    'type': column['data_type'],
                    'nullable': column['is_nullable'] == 'YES',
                    'default': column.get('column_default'),
                    'indexed': False  # Would need index information
                }
            
            # Add index information (if available)
            for index in table_info.get('indexes', []):
                redis_schema['indexes'].append({
                    'name': index.get('name', f"{table_name}_idx"),
                    'columns': index.get('column_names', []),
                    'unique': index.get('unique', False)
                })
            
            schemas[table_name] = redis_schema
        
        return schemas