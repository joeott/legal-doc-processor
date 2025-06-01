# Context 215: CLI CRUD Operations Enhancement Needed

**Date**: 2025-01-29
**Type**: Feature Request / Development Task
**Status**: IDENTIFIED

## Overview

During production deployment testing, it became apparent that the CLI lacks basic CRUD (Create, Read, Update, Delete) operations for managing core database entities. This gap requires creating ad-hoc scripts for simple operations that should be available through the standard CLI interface.

## Issue Identified

When attempting to import documents, we discovered:
1. No CLI command exists to create projects
2. Had to create a temporary script just to insert a project record
3. This pattern will repeat for other entities (canonical entities, relationships, etc.)

## Proposed CLI Enhancements

### 1. Project Management Commands

```bash
# Create a new project
python -m scripts.cli.admin projects create --name "Project Name" --uuid <optional-uuid>

# List all projects
python -m scripts.cli.admin projects list

# Update project details
python -m scripts.cli.admin projects update <uuid> --name "New Name"

# Delete a project (with cascade confirmation)
python -m scripts.cli.admin projects delete <uuid> --cascade
```

### 2. Document Management Commands

```bash
# Move documents between projects
python -m scripts.cli.admin documents move <doc-uuid> --to-project <project-uuid>

# Update document metadata
python -m scripts.cli.admin documents update <doc-uuid> --metadata '{"key": "value"}'

# Delete documents and related data
python -m scripts.cli.admin documents delete <doc-uuid> --cascade
```

### 3. Entity Management Commands

```bash
# Create canonical entities
python -m scripts.cli.admin entities create --name "Entity Name" --type "person"

# Merge duplicate entities
python -m scripts.cli.admin entities merge <entity-uuid-1> <entity-uuid-2>

# List entities by type
python -m scripts.cli.admin entities list --type "organization"
```

### 4. Import Session Management

```bash
# Resume failed imports
python -m scripts.cli.admin imports resume <session-id>

# List import sessions with status
python -m scripts.cli.admin imports list --status failed

# Retry failed documents in a session
python -m scripts.cli.admin imports retry <session-id>
```

## Implementation Recommendations

1. **Extend admin.py**: Add new command groups for each entity type
2. **Use Click subcommands**: Organize commands hierarchically
3. **Consistent patterns**: Follow REST-like naming (create, list, update, delete)
4. **Rich output**: Use tables for list operations, confirmations for destructive operations
5. **Validation**: Use Pydantic models for input validation

## Benefits

1. **Operational efficiency**: No need for ad-hoc scripts
2. **Consistency**: Standardized interface for all operations
3. **Safety**: Built-in validations and cascade confirmations
4. **Discoverability**: Help commands show available operations
5. **Auditability**: CLI commands can be logged and tracked

## Priority

**HIGH** - These commands are essential for:
- Production operations
- Testing and development
- Data maintenance
- Troubleshooting

## Related Contexts

- Context 214: Document Import System Design
- Context 203: Supabase Schema Design
- Context 213: Production Deployment Checklist

## Next Steps

1. Implement project CRUD commands first (most immediate need)
2. Add document management commands
3. Implement entity and relationship management
4. Add import session management utilities