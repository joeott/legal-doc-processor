# Context 235: Complete Conformance Implementation Task List

## Overview
This document provides a comprehensive, step-by-step task list for implementing the SQLAlchemy-Pydantic conformance standard across all scripts. Designed for systematic execution by agentic coding tools.

## Implementation Strategy

### Phase 1: Core Infrastructure Setup

#### Task 1.1: Complete Conformance Engine Implementation
**Priority: Critical**
**Dependencies: None**
**Estimated Effort: High**

**Subtasks:**
1. **Complete Type Mapping System**
   - Extend `TYPE_MAP` in `conformance_engine.py` to cover all PostgreSQL types
   - Add support for arrays, JSONB, custom types, enums
   - Implement bidirectional type conversion logic

2. **SQL Generation Enhancement**
   - Complete `_generate_create_table_sql()` method
   - Implement proper constraint handling (NOT NULL, UNIQUE, CHECK)
   - Add foreign key relationship detection and creation
   - Support for indexes and database-specific optimizations

3. **Advanced Validation Logic**
   - Add constraint validation (foreign keys, check constraints)
   - Implement enum validation between Pydantic and PostgreSQL
   - Add field metadata validation (default values, descriptions)

4. **Error Recovery System**
   - Implement automatic rollback on failed migrations
   - Add backup creation before schema changes
   - Create recovery procedures for each error type

**Validation Criteria:**
- [ ] All PostgreSQL data types properly mapped to Pydantic types
- [ ] Generated SQL produces valid, executable statements
- [ ] Dry-run mode works without database connection
- [ ] Error conditions properly handled with rollback capability

#### Task 1.2: Database Connection Layer Standardization
**Priority: Critical**
**Dependencies: Task 1.1**
**Estimated Effort: Medium**

**Subtasks:**
1. **Standardize Database Manager Interface**
   ```python
   class DatabaseManager:
       def __init__(self):
           self.conformance_validated = False
           self.engine = create_engine(...)
           self.session_factory = sessionmaker(bind=self.engine)
       
       def validate_conformance(self) -> ConformanceReport:
           """Pre-flight conformance check."""
           if not self.conformance_validated:
               engine = ConformanceEngine()
               report = engine.check_conformance()
               if not report.is_conformant:
                   raise ConformanceError(f"Schema issues: {len(report.issues)}")
               self.conformance_validated = True
           return report
   ```

2. **Transaction Management**
   - Implement context managers for database transactions
   - Add automatic rollback on validation failures
   - Support for nested transactions and savepoints

3. **Connection Pooling Optimization**
   - Configure pool settings for production load
   - Implement connection health checks
   - Add connection retry logic with exponential backoff

**Validation Criteria:**
- [ ] All database operations use standardized manager
- [ ] Conformance validation occurs before any database operation
- [ ] Transaction boundaries properly managed
- [ ] Connection pool handles high concurrency

### Phase 2: Script-by-Script Conformance Implementation

#### Task 2.1: PDF Tasks Conformance (`scripts/pdf_tasks.py`)
**Priority: High**
**Dependencies: Task 1.1, 1.2**
**Estimated Effort: High**

**Subtasks:**
1. **Task Base Class Enhancement**
   ```python
   class PDFTask(Task):
       _db_manager = None
       _conformance_validated = False
       
       @property
       def db_manager(self):
           if self._db_manager is None:
               self._db_manager = DatabaseManager()
               # Validate conformance on first access
               if not self._conformance_validated:
                   self._db_manager.validate_conformance()
                   self._conformance_validated = True
           return self._db_manager
   ```

2. **Individual Task Conformance**
   - `extract_text_from_document`: Add Pydantic validation for OCR results
   - `chunk_document_text`: Validate chunk models before database insertion
   - `extract_entities_from_chunks`: Ensure entity models conform to schema
   - `resolve_document_entities`: Validate canonical entity creation
   - `build_document_relationships`: Validate relationship staging records

3. **Error Handling Integration**
   - Wrap each task with conformance error handling
   - Implement automatic retry for schema mismatch errors
   - Add detailed logging for validation failures

4. **State Management**
   - Validate document state transitions
   - Ensure processing status enum matches database constraints
   - Add rollback procedures for failed state changes

**Validation Criteria:**
- [ ] All tasks validate conformance before processing
- [ ] Pydantic models used for all data structures
- [ ] Database operations use validated models
- [ ] Error conditions properly handled and logged
- [ ] State transitions validated and reversible

#### Task 2.2: OCR Extraction Conformance (`scripts/ocr_extraction.py`)
**Priority: High**
**Dependencies: Task 2.1**
**Estimated Effort: Medium**

**Subtasks:**
1. **Input Validation**
   ```python
   def extract_text_from_pdf(
       file_path: str,
       document_uuid: str,
       db_manager: DatabaseManager
   ) -> OCRResult:
       # Validate inputs
       if not Path(file_path).exists():
           raise FileNotFoundError(f"PDF file not found: {file_path}")
       
       # Validate document exists in database
       document = db_manager.get_source_document(document_uuid)
       if not document:
           raise DocumentNotFoundError(f"Document {document_uuid} not found")
       
       # Validate document state allows OCR
       if document.processing_status != ProcessingStatus.PENDING:
           raise StateValidationError(f"Invalid state for OCR: {document.processing_status}")
   ```

2. **Output Validation**
   - Create `OCRResultModel` Pydantic model
   - Validate Textract response structure
   - Ensure extracted text meets quality thresholds
   - Validate confidence scores and warnings

3. **Database Integration**
   - Use validated models for all database operations
   - Implement proper error handling for database failures
   - Add rollback procedures for partial OCR failures

**Validation Criteria:**
- [ ] All inputs validated before processing
- [ ] OCR outputs use Pydantic models
- [ ] Database operations validated and reversible
- [ ] Quality thresholds enforced

#### Task 2.3: Text Processing Conformance (`scripts/text_processing.py`)
**Priority: High**
**Dependencies: Task 2.2**
**Estimated Effort: Medium**

**Subtasks:**
1. **Chunking Validation**
   ```python
   def create_validated_chunks(
       text: str,
       document_uuid: str,
       chunk_size: int = 2000,
       overlap: int = 200
   ) -> List[ChunkModel]:
       # Validate inputs
       if not text.strip():
           raise ValidationError("Text content cannot be empty")
       
       if chunk_size < 100 or chunk_size > 10000:
           raise ValidationError(f"Invalid chunk size: {chunk_size}")
       
       # Create chunks with validation
       chunks = simple_chunk_text(text, chunk_size, overlap)
       
       # Create Pydantic models
       chunk_models = []
       for i, chunk_text in enumerate(chunks):
           chunk_model = ChunkModel(
               chunk_uuid=uuid.uuid4(),
               document_uuid=document_uuid,
               chunk_index=i,
               text_content=chunk_text,
               start_char=calculate_start_char(chunks, i),
               end_char=calculate_end_char(chunks, i),
               word_count=len(chunk_text.split()),
               created_at=datetime.utcnow()
           )
           # Validate model
           chunk_model.model_validate(chunk_model.model_dump())
           chunk_models.append(chunk_model)
       
       return chunk_models
   ```

2. **Quality Assurance**
   - Validate chunk boundaries don't split words inappropriately
   - Ensure overlap calculations are correct
   - Validate chunk metadata (word counts, character indices)

3. **Performance Optimization**
   - Implement chunking performance metrics
   - Add caching for repeated chunking operations
   - Validate chunk size optimization based on content type

**Validation Criteria:**
- [ ] All chunking operations validated
- [ ] Chunk models conform to schema
- [ ] Quality metrics tracked and validated
- [ ] Performance optimizations implemented

#### Task 2.4: Entity Service Conformance (`scripts/entity_service.py`)
**Priority: High**
**Dependencies: Task 2.3**
**Estimated Effort: High**

**Subtasks:**
1. **Entity Extraction Validation**
   ```python
   class EntityService:
       def __init__(self, db_manager: DatabaseManager, openai_api_key: str):
           self.db = db_manager
           self.db.validate_conformance()  # Validate on initialization
           self.openai_client = OpenAI(api_key=openai_api_key)
       
       def extract_entities_validated(
           self,
           chunk: ChunkModel
       ) -> List[EntityMentionModel]:
           # Validate input chunk
           chunk.model_validate(chunk.model_dump())
           
           # Extract entities using LLM
           entities_raw = self._extract_with_openai(chunk.text_content)
           
           # Validate and create entity models
           entity_models = []
           for entity_data in entities_raw:
               try:
                   entity_model = EntityMentionModel(
                       mention_uuid=uuid.uuid4(),
                       document_uuid=chunk.document_uuid,
                       chunk_uuid=chunk.chunk_uuid,
                       entity_text=entity_data['text'],
                       entity_type=EntityType(entity_data['type']),
                       confidence_score=entity_data['confidence'],
                       start_char=entity_data['start_char'],
                       end_char=entity_data['end_char'],
                       created_at=datetime.utcnow()
                   )
                   # Validate model
                   entity_model.model_validate(entity_model.model_dump())
                   entity_models.append(entity_model)
               except ValidationError as e:
                   logger.warning(f"Invalid entity data: {e}")
                   continue
           
           return entity_models
   ```

2. **Entity Resolution Validation**
   - Validate entity matching algorithms
   - Ensure canonical entity creation follows schema
   - Validate entity relationship mappings

3. **Quality Control**
   - Implement confidence score thresholds
   - Validate entity type classifications
   - Add duplicate detection and resolution

**Validation Criteria:**
- [ ] All entity extractions validated
- [ ] Entity models conform to schema
- [ ] Quality thresholds enforced
- [ ] Duplicate detection working

#### Task 2.5: Graph Service Conformance (`scripts/graph_service.py`)
**Priority: High**
**Dependencies: Task 2.4**
**Estimated Effort: High**

**Subtasks:**
1. **Relationship Validation**
   ```python
   def create_validated_relationships(
       self,
       entities: List[CanonicalEntityModel],
       document_uuid: str
   ) -> List[RelationshipStagingModel]:
       # Validate input entities
       for entity in entities:
           entity.model_validate(entity.model_dump())
       
       # Extract relationships
       relationships_raw = self._extract_relationships(entities)
       
       # Create validated relationship models
       relationship_models = []
       for rel_data in relationships_raw:
           try:
               relationship_model = RelationshipStagingModel(
                   relationship_uuid=uuid.uuid4(),
                   source_entity_id=rel_data['source_id'],
                   target_entity_id=rel_data['target_id'],
                   relationship_type=RelationshipType(rel_data['type']),
                   confidence_score=rel_data['confidence'],
                   source_id=document_uuid,
                   evidence_text=rel_data['evidence'],
                   created_at=datetime.utcnow()
               )
               # Validate model
               relationship_model.model_validate(relationship_model.model_dump())
               relationship_models.append(relationship_model)
           except ValidationError as e:
               logger.warning(f"Invalid relationship data: {e}")
               continue
       
       return relationship_models
   ```

2. **Graph Integrity Validation**
   - Validate entity references exist
   - Ensure relationship types are valid
   - Validate graph connectivity and consistency

3. **Performance Optimization**
   - Implement graph construction metrics
   - Add caching for relationship extraction
   - Validate relationship quality scores

**Validation Criteria:**
- [ ] All relationships validated
- [ ] Graph integrity maintained
- [ ] Performance metrics tracked
- [ ] Quality scores validated

### Phase 3: CLI and Monitoring Conformance

#### Task 3.1: CLI Tools Conformance (`scripts/cli/`)
**Priority: Medium**
**Dependencies: All Phase 2 tasks**
**Estimated Effort: Medium**

**Subtasks:**
1. **Import CLI Conformance (`scripts/cli/import.py`)**
   - Add conformance validation before import operations
   - Validate manifest files against Pydantic schemas
   - Implement rollback procedures for failed imports

2. **Monitor CLI Enhancement (`scripts/cli/monitor.py`)**
   - Add real-time conformance status display
   - Implement conformance alerts and notifications
   - Add schema drift detection and reporting

3. **Admin CLI Tools (`scripts/cli/admin.py`)**
   - Add conformance validation commands
   - Implement schema synchronization tools
   - Add database health check with conformance status

**Validation Criteria:**
- [ ] All CLI tools validate conformance
- [ ] Real-time monitoring includes schema status
- [ ] Admin tools provide conformance management
- [ ] Error handling and rollback implemented

#### Task 3.2: Monitoring Integration Enhancement
**Priority: Medium**
**Dependencies: Task 3.1**
**Estimated Effort: Medium**

**Subtasks:**
1. **Dashboard Enhancement**
   ```python
   def display_conformance_dashboard():
       """Enhanced dashboard with conformance monitoring."""
       engine = ConformanceEngine()
       report = engine.check_conformance()
       
       # Create conformance panel
       conformance_status = "✅ CONFORMANT" if report.is_conformant else "❌ NON-CONFORMANT"
       conformance_panel = Panel(
           f"[bold]Schema Conformance[/bold]\n"
           f"Status: {conformance_status}\n"
           f"Tables: {report.conformant_tables}/{report.total_tables}\n"
           f"Issues: {len(report.issues)}",
           title="System Health",
           border_style="green" if report.is_conformant else "red"
       )
       
       return conformance_panel
   ```

2. **Alert System**
   - Implement conformance alerts
   - Add email/Slack notifications for schema drift
   - Create escalation procedures for critical issues

3. **Metrics Collection**
   - Track conformance validation performance
   - Monitor schema change frequency
   - Collect validation error patterns

**Validation Criteria:**
- [ ] Dashboard shows real-time conformance status
- [ ] Alert system functional
- [ ] Metrics properly collected and displayed
- [ ] Performance tracking implemented

### Phase 4: Testing and Validation

#### Task 4.1: Comprehensive Test Suite
**Priority: High**
**Dependencies: All previous tasks**
**Estimated Effort: High**

**Subtasks:**
1. **Unit Tests for Conformance Engine**
   ```python
   class TestConformanceEngine:
       def test_schema_validation(self):
           """Test basic schema validation."""
           engine = ConformanceEngine()
           report = engine.check_conformance()
           assert isinstance(report, ConformanceReport)
       
       def test_type_mapping(self):
           """Test type compatibility checking."""
           engine = ConformanceEngine()
           # Test various type combinations
           assert engine._check_type_compatibility(...)
       
       def test_sql_generation(self):
           """Test SQL generation for fixes."""
           engine = ConformanceEngine()
           sql = engine._generate_add_column_sql(...)
           assert "ALTER TABLE" in sql
   ```

2. **Integration Tests**
   - End-to-end pipeline test with conformance validation
   - Multi-document processing with schema validation
   - Error recovery and rollback testing

3. **Performance Tests**
   - Schema validation performance under load
   - Database operation performance with validation
   - Memory usage and optimization validation

**Validation Criteria:**
- [ ] All unit tests pass
- [ ] Integration tests cover full pipeline
- [ ] Performance tests meet requirements
- [ ] Error conditions properly tested

#### Task 4.2: Production Readiness Validation
**Priority: Critical**
**Dependencies: Task 4.1**
**Estimated Effort: Medium**

**Subtasks:**
1. **Single Document E2E Test**
   ```python
   def test_single_document_complete_pipeline():
       """Test complete pipeline with conformance validation."""
       # Initialize with conformance check
       engine = ConformanceEngine()
       assert engine.check_conformance().is_conformant
       
       # Submit document
       test_doc = "/input/Paul, Michael (Acuity)/test_document.pdf"
       result = submit_document_with_validation(test_doc, "test-project")
       
       # Monitor all stages
       stages = ["ocr", "chunking", "entity_extraction", "graph_building"]
       for stage in stages:
           wait_for_stage_completion(result["document_uuid"], stage)
           validate_stage_conformance(result["document_uuid"], stage)
       
       # Validate final state
       final_doc = db.get_source_document(result["document_uuid"])
       assert final_doc.processing_status == ProcessingStatus.COMPLETED
   ```

2. **Load Testing**
   - Multiple documents processed simultaneously
   - Conformance validation under high load
   - Resource usage monitoring with validation overhead

3. **Error Scenario Testing**
   - Schema mismatch error handling
   - Database connection failure recovery
   - Partial processing failure and rollback

**Validation Criteria:**
- [ ] Single document test passes completely
- [ ] Load testing meets performance requirements
- [ ] Error scenarios properly handled
- [ ] System maintains conformance under all conditions

## Implementation Timeline

### Week 1: Core Infrastructure
- Complete Tasks 1.1 and 1.2
- Establish conformance validation foundation

### Week 2: Critical Scripts
- Complete Tasks 2.1, 2.2, and 2.3
- Focus on PDF processing and text extraction

### Week 3: Advanced Processing
- Complete Tasks 2.4 and 2.5
- Implement entity and graph processing conformance

### Week 4: Monitoring and Testing
- Complete Tasks 3.1, 3.2, 4.1, and 4.2
- Full system validation and testing

## Success Criteria

### Technical Requirements
- [ ] All scripts validate conformance before processing
- [ ] Pydantic models used for all data structures
- [ ] Database operations fully validated
- [ ] Error handling and rollback implemented
- [ ] Performance impact < 5% overhead
- [ ] Real-time monitoring includes conformance status

### Operational Requirements
- [ ] Zero undetected schema drift incidents
- [ ] Automatic recovery from common validation errors
- [ ] Clear error messages for manual intervention cases
- [ ] Comprehensive logging and monitoring
- [ ] Documentation and runbooks complete

### Quality Assurance
- [ ] 100% test coverage for conformance engine
- [ ] All error scenarios tested and handled
- [ ] Performance benchmarks established and met
- [ ] Production deployment successful
- [ ] Monitoring and alerting functional

## Risk Mitigation

### High-Risk Areas
1. **Database Migration Failures**
   - Mitigation: Comprehensive backup and rollback procedures
   - Testing: Extensive schema migration testing

2. **Performance Degradation**
   - Mitigation: Caching and optimization strategies
   - Testing: Load testing with conformance validation

3. **Complex Type Mapping Errors**
   - Mitigation: Conservative type mapping with manual overrides
   - Testing: Extensive type compatibility testing

### Monitoring and Alerts
- Schema conformance status alerts
- Performance degradation detection
- Error rate monitoring with conformance context
- Resource usage tracking

This task list provides a complete roadmap for implementing the conformance standard across all scripts, designed for systematic execution by agentic coding tools with clear validation criteria and success metrics.