# Context 404: Project Association Architecture and Solutions

**Date**: June 5, 2025  
**Time**: 01:52 AM UTC  
**Status**: CRITICAL ARCHITECTURE ISSUE  
**Issue**: Documents require project association but no project management exists

## Problem Statement

The production pipeline is failing because documents must be associated with a project (via `project_fk_id` foreign key), but:
1. No projects exist in the database
2. No mechanism exists to create projects
3. No way to specify which project documents belong to
4. The pipeline hardcodes `project_fk_id = 1`

## Evidence of the Problem

### 1. Database Schema Requirement
```sql
-- source_documents table has foreign key constraint
CONSTRAINT "source_documents_project_fk_id_fkey" 
FOREIGN KEY (project_fk_id) REFERENCES projects(id)
```

### 2. Current Implementation Failure
```python
# scripts/batch_processor.py - hardcoded project ID
session.execute(text("""
    INSERT INTO source_documents (
        ... project_fk_id
    ) VALUES (
        ... 1  # Hardcoded!
    )
"""))
```

### 3. Error Evidence
```
ERROR: insert or update on table "source_documents" violates foreign key constraint
DETAIL: Key (project_fk_id)=(1) is not present in table "projects"
```

### 4. Missing Project Management
- No project creation in `production_processor.py`
- No project selection mechanism
- No project discovery utilities
- Projects table exists but is empty

## Immediate Solution (For Current Implementation)

### 1. Add Project Support to Production Processor

Modify `production_processor.py` to accept project parameter:

```python
@click.command()
@click.argument('input_dir', type=click.Path(exists=True))
@click.option('--project-id', type=int, default=1, 
              help='Project ID to associate documents with (default: 1)')
@click.option('--project-name', type=str, default='Default Project',
              help='Project name if creating new (default: Default Project)')
@click.option('--batch-strategy', type=click.Choice(['balanced', 'priority_first', 'size_optimized']), 
              default='balanced')
def process(input_dir: str, project_id: int, project_name: str, batch_strategy: str):
    """Process documents from INPUT_DIR."""
    processor = ProductionProcessor()
    
    # Ensure project exists
    processor.ensure_project_exists(project_id, project_name)
    
    # Pass project_id through the pipeline
    campaign_id = processor.execute_full_input_processing(
        input_dir, 
        batch_strategy=batch_strategy,
        project_id=project_id
    )
```

### 2. Add Project Management to ProductionProcessor

```python
def ensure_project_exists(self, project_id: int, project_name: str) -> None:
    """Ensure the specified project exists, create if not."""
    with self.db_manager.get_session() as session:
        # Check if project exists
        exists = session.execute(text(
            "SELECT COUNT(*) FROM projects WHERE id = :id"
        ), {'id': project_id}).scalar()
        
        if not exists:
            # Create project
            session.execute(text("""
                INSERT INTO projects (id, project_name, created_at, updated_at)
                VALUES (:id, :name, NOW(), NOW())
            """), {
                'id': project_id,
                'name': project_name
            })
            session.commit()
            logger.info(f"Created project {project_id}: {project_name}")
        else:
            logger.info(f"Using existing project {project_id}")
```

### 3. Pass Project ID Through Pipeline

Update `batch_processor.py` to accept project_id:

```python
def submit_batch_for_processing(self, batch: BatchManifest, project_id: int = 1) -> BatchJobId:
    """Submit a batch for processing via Celery."""
    # ... existing code ...
    
    for doc in batch.documents:
        try:
            # CREATE DATABASE RECORD WITH PROJECT
            for session in self.db_manager.get_session():
                document_uuid = create_document_record(
                    session,
                    original_filename=doc.get('filename'),
                    s3_bucket=doc.get('s3_bucket'),
                    s3_key=doc.get('s3_key'),
                    file_size_mb=doc.get('file_size_mb', 0.0),
                    mime_type=doc.get('mime_type', 'application/pdf'),
                    project_id=project_id  # Pass through!
                )
```

Update `create_document_record` to accept project_id:

```python
def create_document_record(session, original_filename: str, s3_bucket: str, s3_key: str, 
                          file_size_mb: float, mime_type: str, project_id: int = 1) -> str:
    """Create a source_documents record with project association."""
    # ... existing code ...
    session.execute(text("""
        INSERT INTO source_documents (
            document_uuid, original_file_name, file_name, s3_bucket, s3_key,
            file_size_bytes, file_type, detected_file_type, status,
            created_at, updated_at, project_fk_id
        ) VALUES (
            :uuid, :filename, :filename, :bucket, :key,
            :size_bytes, :file_type, :file_type, 'pending',
            NOW(), NOW(), :project_id
        )
    """), {
        'uuid': document_uuid,
        'filename': original_filename,
        'bucket': s3_bucket,
        'key': s3_key,
        'size_bytes': file_size_bytes,
        'file_type': mime_type,
        'project_id': project_id  # Use parameter!
    })
```

### 4. Usage Examples

```bash
# Use default project (ID: 1, creates if needed)
python -m scripts.production_processor process /opt/legal-doc-processor/input_docs

# Use specific project
python -m scripts.production_processor process /opt/legal-doc-processor/input_docs --project-id 5 --project-name "Acuity Case"

# Different batch strategy with project
python -m scripts.production_processor process /opt/legal-doc-processor/input_docs --project-id 2 --batch-strategy priority_first
```

## Future Implementation (Advanced Project Management)

### 1. Intelligent Project Association

```python
class ProjectMatcher:
    """Match documents to projects based on rules."""
    
    def match_document_to_project(self, document_path: str, document_metadata: Dict) -> int:
        """
        Determine which project a document belongs to.
        
        Matching strategies:
        1. Directory name matching
        2. Filename patterns
        3. Content analysis
        4. Metadata tags
        """
        
        # Strategy 1: Directory-based matching
        # e.g., /input_docs/Paul, Michael (Acuity)/ -> "Acuity Case" project
        parent_dir = Path(document_path).parent.name
        if parent_dir:
            project = self.find_project_by_pattern(parent_dir)
            if project:
                return project.id
        
        # Strategy 2: Filename patterns
        # e.g., "Acuity_*" files -> Acuity project
        filename = Path(document_path).name
        for pattern, project_id in self.filename_rules.items():
            if fnmatch.fnmatch(filename, pattern):
                return project_id
        
        # Strategy 3: Content-based (future enhancement)
        # Scan document content for case numbers, client names, etc.
        
        # Default: return general intake project
        return self.get_or_create_intake_project()
```

### 2. Project Management CLI

```python
@click.group()
def project():
    """Manage projects."""
    pass

@project.command()
@click.option('--name', required=True)
@click.option('--description', default='')
@click.option('--client', default='')
@click.option('--matter-number', default='')
def create(name: str, description: str, client: str, matter_number: str):
    """Create a new project."""
    # Implementation

@project.command()
def list():
    """List all projects."""
    # Show projects with document counts

@project.command()
@click.argument('project_id', type=int)
@click.option('--pattern', help='Filename pattern to match')
@click.option('--directory', help='Directory name to match')
def add_rule(project_id: int, pattern: str, directory: str):
    """Add matching rule for automatic project assignment."""
    # Implementation
```

### 3. Multi-Project Batch Processing

```python
def execute_multi_project_processing(self, input_dir: str) -> Dict[int, str]:
    """
    Process documents, automatically sorting into projects.
    
    Returns:
        Dict mapping project_id to campaign_id
    """
    # Discover all documents
    all_documents = self.intake_service.discover_documents(input_dir)
    
    # Group by project
    project_documents = defaultdict(list)
    for doc in all_documents:
        project_id = self.project_matcher.match_document_to_project(
            doc.local_path, doc.to_dict()
        )
        project_documents[project_id].append(doc)
    
    # Process each project's documents as separate campaign
    campaigns = {}
    for project_id, documents in project_documents.items():
        logger.info(f"Processing {len(documents)} documents for project {project_id}")
        campaign_id = self._process_project_documents(
            project_id, documents
        )
        campaigns[project_id] = campaign_id
    
    return campaigns
```

### 4. Project Metadata Enhancement

```sql
-- Future schema enhancements
ALTER TABLE projects ADD COLUMN client_name VARCHAR(255);
ALTER TABLE projects ADD COLUMN matter_number VARCHAR(100);
ALTER TABLE projects ADD COLUMN case_type VARCHAR(50);
ALTER TABLE projects ADD COLUMN status VARCHAR(50) DEFAULT 'active';
ALTER TABLE projects ADD COLUMN auto_match_rules JSONB;

-- Project matching rules table
CREATE TABLE project_match_rules (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id),
    rule_type VARCHAR(50), -- 'directory', 'filename', 'content'
    pattern VARCHAR(255),
    priority INTEGER DEFAULT 100,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### 5. Smart Project Selection UI

Future frontend integration:
```javascript
// Project selection during upload
const ProjectSelector = () => {
    const [projects, setProjects] = useState([]);
    const [suggestedProject, setSuggestedProject] = useState(null);
    
    // Auto-suggest project based on upload path
    useEffect(() => {
        if (uploadPath) {
            const suggestion = await api.suggestProject(uploadPath);
            setSuggestedProject(suggestion);
        }
    }, [uploadPath]);
    
    return (
        <Select 
            value={selectedProject}
            onChange={setSelectedProject}
            placeholder="Select or create project..."
        >
            {suggestedProject && (
                <Option value={suggestedProject.id} highlighted>
                    {suggestedProject.name} (Suggested)
                </Option>
            )}
            {projects.map(p => (
                <Option key={p.id} value={p.id}>{p.name}</Option>
            ))}
            <Option value="new">+ Create New Project</Option>
        </Select>
    );
};
```

## Implementation Priority

### Phase 1 (Immediate - Current Fix)
1. ✅ Add `ensure_project_exists` to ProductionProcessor
2. ✅ Add `--project-id` parameter to CLI
3. ✅ Pass project_id through batch processor
4. ✅ Update create_document_record to use project_id parameter

### Phase 2 (Near Term)
1. Project management CLI commands
2. List projects with document counts
3. Basic filename pattern matching

### Phase 3 (Future)
1. Intelligent project matching
2. Multi-project batch processing
3. Frontend project selector
4. Advanced matching rules

## Benefits of This Architecture

1. **Immediate Fix**: Solves the current blocking issue
2. **Backward Compatible**: Default project (ID: 1) maintains compatibility
3. **Scalable**: Supports multiple projects/matters/clients
4. **Flexible**: Multiple matching strategies for automation
5. **User-Friendly**: Both CLI and future UI support
6. **Audit Trail**: Clear project association for all documents

## Testing Strategy

### Immediate Testing
```bash
# Test 1: Default project creation
python -m scripts.production_processor process /test/dir

# Test 2: Specific project
python -m scripts.production_processor process /test/dir --project-id 10 --project-name "Test Project"

# Test 3: Existing project
# Run Test 2 again - should use existing project
```

### Future Testing
- Pattern matching accuracy
- Multi-project sorting
- Performance with many projects
- Conflict resolution

## Conclusion

The project association architecture is a critical missing piece that needs both an immediate fix and a long-term strategy. The immediate solution unblocks production processing while laying groundwork for sophisticated project management features that will be essential for a legal document processing system handling multiple matters and clients.