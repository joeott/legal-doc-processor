# Context 120: Airtable-Supabase Schema Integration and UUID Synchronization

## Executive Summary

This document provides detailed implementation guidance for synchronizing Airtable and Supabase schemas, with specific focus on UUID field mapping and entity relationship management. Based on schema analysis, we've identified key differences in UUID naming conventions and developed a comprehensive mapping strategy to ensure data consistency across systems.

## Schema Comparison Analysis

### Airtable Schema Structure

Based on the Airtable schema discovery:

```json
{
  "Projects": {
    "fields": {
      "projectid": "UUID (e.g., '2c7be107-77c9-4111-92d2-37626e233e4c')",
      "projectname": "string",
      "projectstatus": "select",
      "people": ["recXXX", "recYYY"],  // Links to People table
      "staff": ["recAAA"],              // Links to Staff table
      "tasks": ["recBBB", "recCCC"]     // Links to Tasks table
    }
  },
  "People": {
    "fields": {
      "People_uuid": "UUID (e.g., '0b1ff8ab-4a39-4525-9ec9-3beea3545558')",
      "Name": "string",
      "First Name": "string", 
      "Last Name": "string",
      "Organization / Company": "string",
      "Email": "email",
      "Phone": "phone",
      "Projects": ["recDDD"],  // Back-reference to Projects
      "Tasks": ["recEEE"]      // Tasks assigned to person
    }
  }
}
```

### Supabase Schema Structure

From the Supabase schema extraction:

```json
{
  "projects": {
    "columns": {
      "id": "integer (primary key)",
      "projectId": "string (legacy, being migrated to project_uuid)",
      "project_uuid": "UUID",
      "name": "string",
      "airtable_id": "string (for record ID reference)",
      "metadata": "JSONB"
    }
  },
  "neo4j_canonical_entities": {
    "columns": {
      "id": "integer (primary key)",
      "canonicalEntityId": "UUID",
      "canonicalName": "string",
      "entity_type": "string (PERSON, ORGANIZATION, etc.)",
      "document_uuid": "UUID (reference)",
      "emails": "JSONB array",
      "phones": "JSONB array"
    }
  }
}
```

## UUID Field Mapping Strategy

### 1. Primary UUID Mappings

```python
UUID_FIELD_MAPPINGS = {
    # Airtable Field → Supabase Field
    "Projects": {
        "projectid": "project_uuid",           # Direct UUID mapping
        "Record ID": "airtable_id",            # Airtable's internal ID
        "projectname": "name"
    },
    "People": {
        "People_uuid": "canonicalEntityId",    # Map to canonical entities
        "Record ID": "airtable_person_id",     # Store in metadata
        "Name": "canonicalName",
        "First Name": "metadata.first_name",
        "Last Name": "metadata.last_name",
        "Email": "emails[0]",                  # Primary email
        "Phone": "phones[0]"                   # Primary phone
    }
}
```

### 2. Entity Resolution Strategy

Since Airtable People records need to map to Supabase canonical entities:

```python
class AirtableEntityResolver:
    """Resolves Airtable People to Supabase canonical entities"""
    
    def resolve_person_to_entity(self, airtable_person: Dict) -> Dict:
        """
        Convert Airtable Person to Supabase canonical entity format
        
        Args:
            airtable_person: Person record from Airtable
            
        Returns:
            Canonical entity data for Supabase
        """
        person_uuid = airtable_person['fields'].get('People_uuid')
        
        # Build canonical entity
        entity_data = {
            'canonicalEntityId': person_uuid,
            'canonicalName': airtable_person['fields'].get('Name', ''),
            'display_name': airtable_person['fields'].get('Name', ''),
            'entity_type': 'PERSON',
            'entity_source': 'airtable_import',
            'emails': [],
            'phones': [],
            'metadata': {
                'airtable_record_id': airtable_person['id'],
                'airtable_fields': {
                    'first_name': airtable_person['fields'].get('First Name'),
                    'last_name': airtable_person['fields'].get('Last Name'),
                    'organization': airtable_person['fields'].get('Organization / Company')
                },
                'import_timestamp': datetime.now().isoformat()
            }
        }
        
        # Add contact information
        if email := airtable_person['fields'].get('Email'):
            entity_data['emails'] = [email]
            
        if phone := airtable_person['fields'].get('Phone'):
            entity_data['phones'] = [phone]
            
        return entity_data
```

## Implementation Details

### 1. Enhanced Airtable Client with People Support

```python
# airtable/airtable_client.py - Enhanced version

class AirtableProjectManager:
    """Extended to handle People and entity relationships"""
    
    def get_all_people(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Fetch all people from Airtable People table"""
        if not force_refresh and self._people_cache_valid():
            return self._people_cache
            
        try:
            people_url = f"https://api.airtable.com/v0/{self.base_id}/People"
            all_people = []
            offset = None
            
            while True:
                params = {"pageSize": 100}
                if offset:
                    params["offset"] = offset
                    
                response = requests.get(people_url, headers=self.headers, params=params)
                response.raise_for_status()
                
                data = response.json()
                all_people.extend(data.get("records", []))
                
                offset = data.get("offset")
                if not offset:
                    break
                    
            # Cache results
            self._people_cache = all_people
            self._people_cache_timestamp = datetime.now()
            
            return all_people
            
        except Exception as e:
            logger.error(f"Failed to fetch people from Airtable: {e}")
            return self._people_cache if self._people_cache else []
    
    def get_project_people(self, project_id: str) -> List[Dict[str, Any]]:
        """Get all people associated with a project"""
        projects = self.get_all_projects()
        people = self.get_all_people()
        
        # Find project
        project = next((p for p in projects if p['project_id'] == project_id), None)
        if not project:
            return []
            
        # Get people record IDs from project
        people_ids = project.get('metadata', {}).get('people_record_ids', [])
        
        # Return matching people
        return [p for p in people if p['id'] in people_ids]
```

### 2. Synchronization Module with Entity Support

```python
# airtable/airtable_sync.py - Enhanced version

class AirtableSupabaseSync:
    """Extended sync with people/entity synchronization"""
    
    def sync_people_to_entities(self, dry_run: bool = False) -> Dict[str, Any]:
        """Synchronize Airtable People to Supabase canonical entities"""
        logger.info("Starting Airtable People to Supabase entities sync")
        
        stats = {
            "airtable_people": 0,
            "existing_entities": 0,
            "created": 0,
            "updated": 0,
            "errors": 0
        }
        
        try:
            # Get all people from Airtable
            airtable_people = self.airtable_mgr.get_all_people(force_refresh=True)
            stats["airtable_people"] = len(airtable_people)
            
            # Get existing canonical entities that came from Airtable
            entities_response = self.supabase_mgr.client.table('neo4j_canonical_entities').select(
                'id, canonicalEntityId, canonicalName, metadata'
            ).eq('entity_source', 'airtable_import').execute()
            
            existing_entities = {
                e['canonicalEntityId']: e for e in entities_response.data
            }
            stats["existing_entities"] = len(existing_entities)
            
            # Process each person
            resolver = AirtableEntityResolver()
            
            for person in airtable_people:
                try:
                    # Convert to entity format
                    entity_data = resolver.resolve_person_to_entity(person)
                    entity_uuid = entity_data['canonicalEntityId']
                    
                    if not entity_uuid:
                        logger.warning(f"Person missing UUID: {person}")
                        stats["errors"] += 1
                        continue
                    
                    if entity_uuid in existing_entities:
                        # Update existing entity
                        if not dry_run:
                            # Preserve certain fields from existing entity
                            existing = existing_entities[entity_uuid]
                            entity_data['id'] = existing['id']
                            entity_data['mention_count'] = existing.get('mention_count', 0)
                            
                            self.supabase_mgr.client.table('neo4j_canonical_entities').update(
                                entity_data
                            ).eq('canonicalEntityId', entity_uuid).execute()
                            
                        stats["updated"] += 1
                    else:
                        # Create new entity
                        if not dry_run:
                            entity_data['createdAt'] = datetime.now().isoformat()
                            entity_data['updatedAt'] = datetime.now().isoformat()
                            
                            self.supabase_mgr.client.table('neo4j_canonical_entities').insert(
                                entity_data
                            ).execute()
                            
                        stats["created"] += 1
                        
                except Exception as e:
                    logger.error(f"Failed to sync person {person.get('id')}: {e}")
                    stats["errors"] += 1
                    
            logger.info(f"People sync completed: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"People sync failed: {e}")
            stats["errors"] += 1
            return stats
    
    def sync_project_relationships(self, project_id: str) -> Dict[str, Any]:
        """Sync relationships between project and its associated people"""
        stats = {"relationships_created": 0, "errors": 0}
        
        try:
            # Get project people from Airtable
            people = self.airtable_mgr.get_project_people(project_id)
            
            # Get project UUID mapping
            project_response = self.supabase_mgr.client.table('projects').select(
                'id, project_uuid'
            ).eq('project_uuid', project_id).execute()
            
            if not project_response.data:
                logger.error(f"Project {project_id} not found in Supabase")
                return stats
                
            project_data = project_response.data[0]
            
            # Create relationships in staging table
            for person in people:
                person_uuid = person['fields'].get('People_uuid')
                if not person_uuid:
                    continue
                    
                try:
                    relationship_data = {
                        'fromNodeId': project_id,
                        'fromNodeLabel': 'Project',
                        'toNodeId': person_uuid,
                        'toNodeLabel': 'Person',
                        'relationshipType': 'HAS_PARTICIPANT',
                        'properties': {
                            'source': 'airtable_sync',
                            'airtable_person_id': person['id'],
                            'role': person['fields'].get('Role', 'participant'),
                            'synced_at': datetime.now().isoformat()
                        },
                        'batchProcessId': f'airtable_sync_{datetime.now().strftime("%Y%m%d_%H%M%S")}',
                        'createdAt': datetime.now().isoformat()
                    }
                    
                    # Check if relationship already exists
                    existing = self.supabase_mgr.client.table('neo4j_relationships_staging').select(
                        'id'
                    ).eq('fromNodeId', project_id).eq('toNodeId', person_uuid).execute()
                    
                    if not existing.data:
                        self.supabase_mgr.client.table('neo4j_relationships_staging').insert(
                            relationship_data
                        ).execute()
                        stats["relationships_created"] += 1
                        
                except Exception as e:
                    logger.error(f"Failed to create relationship: {e}")
                    stats["errors"] += 1
                    
        except Exception as e:
            logger.error(f"Failed to sync project relationships: {e}")
            stats["errors"] += 1
            
        return stats
```

### 3. Document Processing with Entity Linking

```python
# airtable/document_ingestion.py - Enhanced version

class ProjectAwareDocumentIngestion:
    """Extended with entity relationship awareness"""
    
    def link_document_to_project_people(
        self, 
        document_uuid: str, 
        project_id: str
    ) -> Dict[str, Any]:
        """
        Create relationships between document and project participants
        
        This enables the knowledge graph to show which people are
        associated with which documents through their project membership
        """
        stats = {"linked_people": 0, "errors": 0}
        
        try:
            # Get project people
            people = self.sync_manager.airtable_mgr.get_project_people(project_id)
            
            for person in people:
                person_uuid = person['fields'].get('People_uuid')
                if not person_uuid:
                    continue
                    
                try:
                    # Create document-person relationship
                    relationship = {
                        'fromNodeId': document_uuid,
                        'fromNodeLabel': 'Document',
                        'toNodeId': person_uuid,
                        'toNodeLabel': 'Person',
                        'relationshipType': 'MENTIONS_PARTICIPANT',
                        'properties': {
                            'source': 'project_association',
                            'project_id': project_id,
                            'confidence': 0.9,  # High confidence from project association
                            'created_at': datetime.now().isoformat()
                        },
                        'batchProcessId': f'doc_people_link_{datetime.now().strftime("%Y%m%d_%H%M%S")}',
                        'createdAt': datetime.now().isoformat()
                    }
                    
                    self.db_manager.client.table('neo4j_relationships_staging').insert(
                        relationship
                    ).execute()
                    
                    stats["linked_people"] += 1
                    
                except Exception as e:
                    logger.error(f"Failed to link person {person_uuid}: {e}")
                    stats["errors"] += 1
                    
        except Exception as e:
            logger.error(f"Failed to link document to people: {e}")
            stats["errors"] += 1
            
        return stats
```

### 4. Migration Scripts

```sql
-- Migration to add Airtable person tracking
ALTER TABLE neo4j_canonical_entities 
ADD COLUMN IF NOT EXISTS airtable_person_id TEXT UNIQUE;

ALTER TABLE neo4j_canonical_entities 
ADD COLUMN IF NOT EXISTS entity_source TEXT DEFAULT 'document_extraction';

-- Index for Airtable person lookups
CREATE INDEX IF NOT EXISTS idx_canonical_entities_airtable_person 
ON neo4j_canonical_entities(airtable_person_id) 
WHERE airtable_person_id IS NOT NULL;

-- Index for entity source filtering
CREATE INDEX IF NOT EXISTS idx_canonical_entities_source 
ON neo4j_canonical_entities(entity_source);

-- Add metadata column if not exists
ALTER TABLE neo4j_canonical_entities
ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';
```

### 5. Full Sync Workflow

```python
# airtable/full_sync.py

class AirtableFullSync:
    """Orchestrates complete Airtable-Supabase synchronization"""
    
    def __init__(self):
        self.sync = AirtableSupabaseSync()
        
    def perform_full_sync(self, include_relationships: bool = True) -> Dict[str, Any]:
        """
        Perform complete sync of all Airtable data
        
        Order matters:
        1. Sync projects first (parent entities)
        2. Sync people/entities 
        3. Sync relationships between them
        """
        results = {
            "projects": {},
            "people": {},
            "relationships": {},
            "total_time": 0
        }
        
        start_time = time.time()
        
        try:
            # Step 1: Sync all projects
            logger.info("Step 1: Syncing projects...")
            results["projects"] = self.sync.sync_projects()
            
            # Step 2: Sync all people as canonical entities
            logger.info("Step 2: Syncing people as entities...")
            results["people"] = self.sync.sync_people_to_entities()
            
            # Step 3: Sync relationships if requested
            if include_relationships:
                logger.info("Step 3: Syncing project-person relationships...")
                
                # Get all active projects
                projects = self.sync.airtable_mgr.get_all_projects()
                relationship_stats = {"total": 0, "errors": 0}
                
                for project in projects:
                    project_id = project.get('project_id')
                    if project_id:
                        stats = self.sync.sync_project_relationships(project_id)
                        relationship_stats["total"] += stats.get("relationships_created", 0)
                        relationship_stats["errors"] += stats.get("errors", 0)
                        
                results["relationships"] = relationship_stats
                
        except Exception as e:
            logger.error(f"Full sync failed: {e}")
            results["error"] = str(e)
            
        results["total_time"] = time.time() - start_time
        
        logger.info(f"Full sync completed in {results['total_time']:.2f}s")
        logger.info(f"Results: {results}")
        
        return results
```

## UUID Synchronization Rules

### 1. Project UUID Rules
- **Source of Truth**: Airtable `projectid` field
- **Supabase Mapping**: Store in `project_uuid` column
- **Validation**: Must be valid UUID v4 format
- **Conflict Resolution**: Airtable always wins

### 2. Person/Entity UUID Rules
- **Source of Truth**: Airtable `People_uuid` field
- **Supabase Mapping**: Store in `canonicalEntityId` column
- **Entity Type**: Always set to 'PERSON' for Airtable imports
- **Metadata Preservation**: Store all Airtable fields in metadata JSONB

### 3. Relationship UUID Generation
- **Pattern**: Relationships use generated UUIDs
- **Tracking**: Store source record IDs in properties
- **Uniqueness**: Enforce unique constraint on (fromNodeId, toNodeId, relationshipType)

## Error Handling and Edge Cases

### 1. Missing UUIDs
```python
def handle_missing_uuid(record_type: str, record: Dict) -> str:
    """Generate UUID for records missing them"""
    if record_type == "project":
        # Use deterministic UUID based on project name
        project_name = record['fields'].get('projectname', '')
        if project_name:
            return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"airtable.project.{project_name}"))
    
    elif record_type == "person":
        # Use deterministic UUID based on email or name
        email = record['fields'].get('Email', '')
        name = record['fields'].get('Name', '')
        if email:
            return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"airtable.person.{email}"))
        elif name:
            return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"airtable.person.{name}"))
    
    # Fallback to random UUID
    return str(uuid.uuid4())
```

### 2. Duplicate Detection
```python
def detect_duplicate_entities(person_data: Dict) -> Optional[str]:
    """Check if person already exists under different UUID"""
    
    # Check by email
    if emails := person_data.get('emails', []):
        existing = supabase.client.table('neo4j_canonical_entities').select(
            'canonicalEntityId'
        ).contains('emails', emails[0]).execute()
        
        if existing.data:
            return existing.data[0]['canonicalEntityId']
    
    # Check by name + phone combination
    if name := person_data.get('canonicalName'):
        if phones := person_data.get('phones', []):
            existing = supabase.client.table('neo4j_canonical_entities').select(
                'canonicalEntityId'
            ).eq('canonicalName', name).contains('phones', phones[0]).execute()
            
            if existing.data:
                return existing.data[0]['canonicalEntityId']
    
    return None
```

## Testing Strategy

### 1. UUID Validation Tests
```python
def test_uuid_field_mapping():
    """Verify all UUIDs map correctly between systems"""
    
    # Test project UUID mapping
    airtable_project = {
        "fields": {"projectid": "2c7be107-77c9-4111-92d2-37626e233e4c"}
    }
    
    mapped = map_project_uuids(airtable_project)
    assert mapped["project_uuid"] == "2c7be107-77c9-4111-92d2-37626e233e4c"
    
    # Test person UUID mapping
    airtable_person = {
        "fields": {"People_uuid": "0b1ff8ab-4a39-4525-9ec9-3beea3545558"}
    }
    
    entity = resolve_person_to_entity(airtable_person)
    assert entity["canonicalEntityId"] == "0b1ff8ab-4a39-4525-9ec9-3beea3545558"
```

### 2. Relationship Integrity Tests
```python
def test_relationship_integrity():
    """Ensure all relationships use valid UUIDs"""
    
    # Get all relationships
    relationships = supabase.client.table('neo4j_relationships_staging').select(
        'fromNodeId, toNodeId, fromNodeLabel, toNodeLabel'
    ).execute()
    
    for rel in relationships.data:
        # Verify source node exists
        if rel['fromNodeLabel'] == 'Project':
            assert_project_exists(rel['fromNodeId'])
        elif rel['fromNodeLabel'] == 'Person':
            assert_entity_exists(rel['fromNodeId'])
            
        # Verify target node exists
        if rel['toNodeLabel'] == 'Person':
            assert_entity_exists(rel['toNodeId'])
```

## Monitoring and Validation

### 1. Sync Health Metrics
```python
SYNC_METRICS = {
    "uuid_mapping_success_rate": "Percentage of records with valid UUIDs",
    "entity_match_rate": "Percentage of people successfully matched to entities",
    "relationship_integrity": "Percentage of relationships with valid endpoints",
    "sync_latency": "Time between Airtable update and Supabase sync",
    "conflict_rate": "Number of UUID conflicts per sync"
}
```

### 2. Validation Queries
```sql
-- Find projects without valid UUIDs
SELECT COUNT(*) as invalid_projects
FROM projects 
WHERE project_uuid IS NULL 
   OR project_uuid !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';

-- Find orphaned relationships
SELECT COUNT(*) as orphaned_relationships
FROM neo4j_relationships_staging r
WHERE NOT EXISTS (
    SELECT 1 FROM projects p WHERE p.project_uuid = r.fromNodeId
    UNION
    SELECT 1 FROM neo4j_canonical_entities e WHERE e.canonicalEntityId = r.fromNodeId
)
OR NOT EXISTS (
    SELECT 1 FROM neo4j_canonical_entities e WHERE e.canonicalEntityId = r.toNodeId
);

-- Find duplicate entities
SELECT canonicalName, COUNT(*) as duplicates
FROM neo4j_canonical_entities
WHERE entity_source = 'airtable_import'
GROUP BY canonicalName
HAVING COUNT(*) > 1;
```

## Deployment Checklist

1. **Pre-deployment**
   - [ ] Backup existing canonical entities table
   - [ ] Run UUID validation on Airtable data
   - [ ] Test sync on staging environment
   - [ ] Verify no UUID conflicts exist

2. **Deployment**
   - [ ] Run database migrations
   - [ ] Deploy enhanced sync modules
   - [ ] Configure sync intervals
   - [ ] Enable monitoring

3. **Post-deployment**
   - [ ] Run full sync with dry_run=True
   - [ ] Verify entity counts match
   - [ ] Check relationship integrity
   - [ ] Monitor sync performance

## Conclusion

This implementation provides a robust UUID synchronization strategy between Airtable and Supabase, with special attention to person-entity mapping. The system maintains data integrity while allowing for flexible entity resolution and relationship management across both platforms.