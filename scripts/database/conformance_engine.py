"""
Central conformance engine that coordinates schema synchronization.
"""

from typing import Dict, List, Optional, Set, Any, Type, Union
from pathlib import Path
import ast
import importlib.util
from dataclasses import dataclass
from enum import Enum
from datetime import datetime
from decimal import Decimal

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
                # Find matching field (check both name and alias)
                model_field = None
                for field_name, field in model_fields.items():
                    if field_name == col_name or (hasattr(field, 'alias') and field.alias == col_name):
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
                field_db_name = field.alias if hasattr(field, 'alias') and field.alias else field_name
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
        db_type_str = str(db_column['type']).upper()
        
        # Get the model field type
        field_type = model_field.annotation
        
        # Handle optional types
        is_optional = False
        if hasattr(field_type, '__origin__') and field_type.__origin__ is Union:
            # Extract non-None types
            inner_types = [t for t in field_type.__args__ if t is not type(None)]
            if len(inner_types) == 1:
                field_type = inner_types[0]
                is_optional = True
        
        # Check nullability matches
        if db_column['nullable'] != is_optional:
            return False
        
        # Map database types to expected Python types
        type_mappings = {
            'UUID': [str],
            'TEXT': [str],
            'VARCHAR': [str],
            'CHAR': [str],
            'INTEGER': [int],
            'BIGINT': [int],
            'BOOLEAN': [bool],
            'BOOL': [bool],
            'TIMESTAMP': [datetime, str],
            'DATETIME': [datetime, str],
            'DATE': [datetime, str],
            'JSONB': [dict, Dict, Any],
            'JSON': [dict, Dict, Any],
            'NUMERIC': [float, Decimal, int],
            'FLOAT': [float],
            'DECIMAL': [float, Decimal]
        }
        
        # Check type compatibility
        for db_pattern, py_types in type_mappings.items():
            if db_pattern in db_type_str:
                return field_type in py_types or field_type.__name__ in [t.__name__ for t in py_types if hasattr(t, '__name__')]
        
        return True  # Default to compatible for unknown types
    
    def generate_models(self, output_path: Path, tables: Optional[List[str]] = None):
        """Generate Pydantic models for all or specified tables."""
        if tables is None:
            tables = self.reflector.get_table_names()
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Generate imports
        imports = [
            "# Auto-generated models from database schema",
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
                model = self.reflector.generate_pydantic_model(table_name)
                model_code = self.reflector._model_to_code(model, table_name)
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
        
        # Get all table names from database
        valid_tables = set(self.reflector.get_table_names())
        
        # Find database operations
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Look for .table() calls
                if (isinstance(node.func, ast.Attribute) and 
                    node.func.attr == 'table' and 
                    len(node.args) > 0):
                    
                    # Extract table name from first argument
                    if isinstance(node.args[0], ast.Str):
                        table_name = node.args[0].s
                    elif isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        table_name = node.args[0].value
                    else:
                        continue
                    
                    if table_name not in valid_tables:
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
        
        for table_name in self.reflector.get_table_names():
            table_info = self.reflector.reflect_table(table_name)
            
            # Create simplified schema for Redis
            redis_schema = {
                'table': table_name,
                'primary_key': table_info['primary_key']['constrained_columns'] if table_info['primary_key'] else [],
                'fields': {},
                'indexes': [],
                'foreign_keys': []
            }
            
            # Add field information
            for column in table_info['columns']:
                redis_schema['fields'][column['name']] = {
                    'type': str(column['type']),
                    'nullable': column['nullable'],
                    'default': column.get('default'),
                    'indexed': any(column['name'] in idx['column_names'] 
                                 for idx in table_info['indexes'])
                }
            
            # Add index information
            for index in table_info['indexes']:
                redis_schema['indexes'].append({
                    'name': index['name'],
                    'columns': index['column_names'],
                    'unique': index['unique']
                })
            
            # Add foreign key information
            for fk in table_info['foreign_keys']:
                redis_schema['foreign_keys'].append({
                    'name': fk.get('name'),
                    'columns': fk['constrained_columns'],
                    'ref_table': fk['referred_table'],
                    'ref_columns': fk['referred_columns']
                })
            
            schemas[table_name] = redis_schema
        
        return schemas
    
    def _table_exists(self, table_name: str) -> bool:
        """Check if a table exists in the database."""
        return table_name in self.reflector.get_table_names()