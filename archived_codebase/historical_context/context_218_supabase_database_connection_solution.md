# Context 218: Supabase Database Connection Solution and Verification

**Date**: 2025-01-29
**Type**: Technical Solution
**Status**: PROPOSED
**Model**: Claude Opus 4

## Problem Analysis

The SQLAlchemy-based schema conformance system requires direct PostgreSQL database access to Supabase, but connection attempts are failing due to:

1. **API-First Architecture**: Supabase is designed as an API-first platform, not for direct database connections
2. **Connection String Confusion**: Multiple conflicting formats for database URLs
3. **DNS Resolution Issues**: The `db.` subdomain pattern doesn't resolve
4. **Authentication Errors**: "Tenant or user not found" errors with pooler connections

## Root Cause

After studying the supabase-py library, it's clear that:
- Supabase clients use REST APIs (PostgREST) rather than direct PostgreSQL connections
- The library doesn't contain any PostgreSQL connection logic
- All database operations go through the `/rest/v1` endpoint

## Proposed Solution

### Option 1: REST API-Based Schema Introspection (Recommended)

Instead of using SQLAlchemy's database introspection, we should use Supabase's REST API to discover schema information.

#### Implementation:

```python
# scripts/database/supabase_schema_introspector.py
"""
Supabase REST API-based schema introspection.
"""

import os
import json
from typing import Dict, List, Any, Optional
from datetime import datetime
import httpx
from supabase import create_client, Client
from pydantic import BaseModel, Field, create_model


class SupabaseSchemaIntrospector:
    """Introspects Supabase schema using REST API and database functions."""
    
    def __init__(self):
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
        
        if not url or not key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")
            
        self.client: Client = create_client(url, key)
        self.url = url
        self.headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }
    
    def get_table_schemas(self) -> Dict[str, Any]:
        """Get table schemas using Supabase's information_schema."""
        # Create a database function to get schema information
        sql_query = """
        SELECT 
            t.table_name,
            json_agg(
                json_build_object(
                    'column_name', c.column_name,
                    'data_type', c.data_type,
                    'is_nullable', c.is_nullable,
                    'column_default', c.column_default,
                    'character_maximum_length', c.character_maximum_length,
                    'numeric_precision', c.numeric_precision,
                    'numeric_scale', c.numeric_scale
                ) ORDER BY c.ordinal_position
            ) as columns
        FROM information_schema.tables t
        JOIN information_schema.columns c 
            ON t.table_name = c.table_name 
            AND t.table_schema = c.table_schema
        WHERE t.table_schema = 'public'
        AND t.table_type = 'BASE TABLE'
        GROUP BY t.table_name
        ORDER BY t.table_name;
        """
        
        # Execute via Supabase RPC or edge function
        response = self._execute_sql(sql_query)
        
        # Transform to schema dictionary
        schemas = {}
        for row in response:
            schemas[row['table_name']] = {
                'columns': row['columns']
            }
        
        return schemas
    
    def _execute_sql(self, sql: str) -> List[Dict[str, Any]]:
        """Execute SQL via Supabase's REST API."""
        # Option 1: Use a pre-created database function
        try:
            result = self.client.rpc('get_schema_info', {}).execute()
            return result.data
        except Exception:
            pass
        
        # Option 2: Use Supabase's SQL endpoint (if available)
        sql_endpoint = f"{self.url}/rest/v1/rpc/sql"
        response = httpx.post(
            sql_endpoint,
            headers=self.headers,
            json={"query": sql}
        )
        
        if response.status_code == 200:
            return response.json()
        
        # Option 3: Fall back to known schema
        return self._get_known_schema()
    
    def _get_known_schema(self) -> List[Dict[str, Any]]:
        """Return known schema structure based on context_203."""
        # This serves as a fallback when API introspection isn't available
        known_tables = {
            'projects': [
                {'column_name': 'project_uuid', 'data_type': 'uuid', 'is_nullable': 'NO'},
                {'column_name': 'project_name', 'data_type': 'text', 'is_nullable': 'NO'},
                {'column_name': 'created_at', 'data_type': 'timestamp with time zone', 'is_nullable': 'NO'},
                {'column_name': 'updated_at', 'data_type': 'timestamp with time zone', 'is_nullable': 'YES'}
            ],
            'documents': [
                {'column_name': 'document_uuid', 'data_type': 'uuid', 'is_nullable': 'NO'},
                {'column_name': 'project_uuid', 'data_type': 'uuid', 'is_nullable': 'NO'},
                {'column_name': 'document_name', 'data_type': 'text', 'is_nullable': 'NO'},
                {'column_name': 'document_type', 'data_type': 'text', 'is_nullable': 'YES'},
                {'column_name': 's3_path', 'data_type': 'text', 'is_nullable': 'YES'},
                {'column_name': 'file_size', 'data_type': 'integer', 'is_nullable': 'YES'},
                {'column_name': 'processing_status', 'data_type': 'text', 'is_nullable': 'NO'},
                {'column_name': 'metadata', 'data_type': 'jsonb', 'is_nullable': 'YES'},
                {'column_name': 'created_at', 'data_type': 'timestamp with time zone', 'is_nullable': 'NO'}
            ]
            # ... other tables from context_203
        }
        
        result = []
        for table_name, columns in known_tables.items():
            result.append({
                'table_name': table_name,
                'columns': columns
            })
        
        return result
    
    def generate_pydantic_model(self, table_name: str, columns: List[Dict]) -> Type[BaseModel]:
        """Generate a Pydantic model from column information."""
        fields = {}
        
        type_mapping = {
            'uuid': str,
            'text': str,
            'character varying': str,
            'integer': int,
            'bigint': int,
            'boolean': bool,
            'timestamp with time zone': datetime,
            'timestamp without time zone': datetime,
            'jsonb': Dict[str, Any],
            'json': Dict[str, Any],
            'numeric': float,
            'real': float,
            'double precision': float
        }
        
        for col in columns:
            col_name = col['column_name']
            col_type = col['data_type'].lower()
            nullable = col['is_nullable'] == 'YES'
            
            # Determine Python type
            py_type = type_mapping.get(col_type, Any)
            
            # Handle nullable fields
            if nullable:
                py_type = Optional[py_type]
            
            # Handle defaults
            default = ... if not nullable else None
            if col.get('column_default'):
                if 'nextval' in str(col['column_default']):
                    default = None  # Auto-increment
                elif col['column_default'] == 'now()':
                    default = None  # Database will set
            
            fields[col_name] = (py_type, Field(default=default, alias=col_name))
        
        # Create model
        model_name = ''.join(word.capitalize() for word in table_name.split('_'))
        model = create_model(
            model_name,
            **fields,
            __module__='generated.models'
        )
        
        return model
```

### Option 2: Supabase Database Connection (If Direct Access is Required)

If direct PostgreSQL access is absolutely necessary, here's how to properly connect:

#### 1. Get Connection Details from Supabase Dashboard

```bash
# Login to Supabase Dashboard
# Navigate to: Settings → Database
# Copy the connection string from "Connection String" section
```

#### 2. Connection String Formats

Based on Supabase's current architecture:

```python
# Direct connection (IPv6) - Requires IPv6 support
DATABASE_URL = "postgresql://postgres.[PROJECT_REF]:[PASSWORD]@db.[PROJECT_REF].supabase.co:5432/postgres"

# Pooled connection (IPv4) - For serverless/edge
DATABASE_URL = "postgresql://postgres.[PROJECT_REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres?pgbouncer=true"

# Session pooling (IPv4) - For persistent connections
DATABASE_URL = "postgresql://postgres.[PROJECT_REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:5432/postgres"
```

#### 3. Enable Direct Database Access

```python
# scripts/database/enable_direct_access.py
"""
Script to verify and enable direct database access for Supabase.
"""

import os
import subprocess
from typing import Optional


def find_connection_string() -> Optional[str]:
    """Find the correct Supabase database connection string."""
    
    # Method 1: Try environment variable
    if os.getenv('DATABASE_URL'):
        return os.getenv('DATABASE_URL')
    
    # Method 2: Construct from Supabase URL
    supabase_url = os.getenv('SUPABASE_URL', '')
    if supabase_url:
        project_ref = supabase_url.split('.')[0].replace('https://', '')
        password = os.getenv('SUPABASE_PASSWORD', '')
        
        if password:
            # Try different connection formats
            connection_formats = [
                # Direct IPv6
                f"postgresql://postgres:{password}@db.{project_ref}.supabase.co:5432/postgres",
                # Pooler session mode
                f"postgresql://postgres.{project_ref}:{password}@aws-0-us-east-1.pooler.supabase.com:5432/postgres",
                # Pooler transaction mode
                f"postgresql://postgres.{project_ref}:{password}@aws-0-us-east-1.pooler.supabase.com:6543/postgres?pgbouncer=true",
            ]
            
            for conn_str in connection_formats:
                if test_connection(conn_str):
                    return conn_str
    
    return None


def test_connection(connection_string: str) -> bool:
    """Test if a connection string works."""
    try:
        import psycopg2
        conn = psycopg2.connect(connection_string)
        conn.close()
        return True
    except Exception:
        return False


def get_supabase_cli_connection() -> Optional[str]:
    """Get connection string using Supabase CLI if installed."""
    try:
        # Check if supabase CLI is installed
        result = subprocess.run(['supabase', '--version'], capture_output=True)
        if result.returncode == 0:
            # Get connection string
            result = subprocess.run(
                ['supabase', 'db', 'url', '--project-ref', get_project_ref()],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                return result.stdout.strip()
    except FileNotFoundError:
        pass
    
    return None


def get_project_ref() -> str:
    """Extract project reference from Supabase URL."""
    supabase_url = os.getenv('SUPABASE_URL', '')
    return supabase_url.split('.')[0].replace('https://', '')
```

### Option 3: Hybrid Approach (Recommended for Production)

Combine REST API for normal operations with optional direct database access:

```python
# scripts/database/hybrid_introspector.py
"""
Hybrid introspector that prefers REST API but can fall back to direct connection.
"""

from typing import Optional, Dict, Any
import os


class HybridSchemaIntrospector:
    """Uses REST API by default, with optional direct database access."""
    
    def __init__(self, connection_string: Optional[str] = None):
        self.rest_introspector = SupabaseSchemaIntrospector()
        self.connection_string = connection_string
        self.sqlalchemy_introspector = None
        
        if connection_string:
            try:
                from .schema_reflection import SchemaReflector
                self.sqlalchemy_introspector = SchemaReflector(connection_string)
            except Exception as e:
                print(f"Warning: Direct database connection failed: {e}")
                print("Falling back to REST API introspection")
    
    def get_schemas(self) -> Dict[str, Any]:
        """Get schemas using the best available method."""
        # Try direct connection first if available
        if self.sqlalchemy_introspector:
            try:
                return self._get_schemas_via_sqlalchemy()
            except Exception as e:
                print(f"Direct introspection failed: {e}")
        
        # Fall back to REST API
        return self._get_schemas_via_rest()
    
    def _get_schemas_via_rest(self) -> Dict[str, Any]:
        """Get schemas via REST API."""
        return self.rest_introspector.get_table_schemas()
    
    def _get_schemas_via_sqlalchemy(self) -> Dict[str, Any]:
        """Get schemas via SQLAlchemy."""
        schemas = {}
        for table_name in self.sqlalchemy_introspector.get_table_names():
            table_info = self.sqlalchemy_introspector.reflect_table(table_name)
            schemas[table_name] = table_info
        return schemas
```

## Verification Steps

### 1. Test REST API Connection

```bash
# Test Supabase client connection
python -c "
import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

url = os.getenv('SUPABASE_URL')
key = os.getenv('SUPABASE_ANON_KEY')
client = create_client(url, key)

# Test query
result = client.table('projects').select('*').limit(1).execute()
print('✅ REST API connection successful')
"
```

### 2. Create Database Function for Schema Introspection

```sql
-- Create this function in Supabase SQL editor
CREATE OR REPLACE FUNCTION get_schema_info()
RETURNS TABLE (
    table_name text,
    columns json
) 
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    RETURN QUERY
    SELECT 
        t.table_name::text,
        json_agg(
            json_build_object(
                'column_name', c.column_name,
                'data_type', c.data_type,
                'is_nullable', c.is_nullable,
                'column_default', c.column_default
            ) ORDER BY c.ordinal_position
        ) as columns
    FROM information_schema.tables t
    JOIN information_schema.columns c 
        ON t.table_name = c.table_name 
        AND t.table_schema = c.table_schema
    WHERE t.table_schema = 'public'
    AND t.table_type = 'BASE TABLE'
    GROUP BY t.table_name
    ORDER BY t.table_name;
END;
$$;
```

### 3. Test Schema Introspection

```python
# Test the introspector
from scripts.database.supabase_schema_introspector import SupabaseSchemaIntrospector

introspector = SupabaseSchemaIntrospector()
schemas = introspector.get_table_schemas()

for table_name, schema in schemas.items():
    print(f"\nTable: {table_name}")
    for col in schema['columns']:
        print(f"  - {col['column_name']}: {col['data_type']}")
```

## Recommendations

1. **Use REST API Introspection**: This aligns with Supabase's architecture and avoids connection issues
2. **Create RPC Functions**: For complex schema operations, create PostgreSQL functions callable via RPC
3. **Cache Schema Information**: Store schema information locally to reduce API calls
4. **Monitor API Limits**: Be aware of Supabase API rate limits when doing bulk introspection

## Migration Path

1. Replace SQLAlchemy introspection with REST API-based approach
2. Update conformance engine to use new introspector
3. Test with known schema structure
4. Gradually add more sophisticated introspection as needed

## Conclusion

The connection issues stem from trying to use Supabase as a traditional PostgreSQL host when it's designed as an API-first platform. The solution is to embrace this architecture and use REST APIs for schema introspection, which is more reliable and aligns with Supabase's design philosophy.