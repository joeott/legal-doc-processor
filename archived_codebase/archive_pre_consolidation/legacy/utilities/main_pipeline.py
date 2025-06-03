# main_pipeline.py
import os
import logging
from datetime import datetime
import json # For handling JSON fields from SQL
import argparse # For command line arguments
from typing import Dict, Any

# Use SupabaseManager instead of db_utils directly
from supabase_utils import SupabaseManager # Assuming SupabaseManager is in supabase_utils.py

from config import (PROJECT_ID_GLOBAL, SOURCE_DOCUMENT_DIR, FORCE_REPROCESS_OCR,
                    USE_S3_FOR_INPUT, S3_TEMP_DOWNLOAD_DIR, DEPLOYMENT_STAGE, FORCE_CLOUD_LLMS) # etc.
from models_init import initialize_all_models
from redis_utils import get_redis_manager
from cache_keys import CacheKeys
from cache_warmer import run_cache_warming
# Remove db_utils imports that are now handled by SupabaseManager
# from db_utils import (get_db_session, get_or_create_project, create_source_document_entry, 
#                      update_source_document_text, create_neo4j_document_entry, 
#                      update_neo4j_document_details, create_chunk_entry, 
#                      create_entity_mention_entry, create_canonical_entity_entry,
#                      update_entity_mention_with_canonical_id, update_neo4j_document_status)
from ocr_extraction import (
    extract_text_from_pdf_qwen_vl_ocr, extract_text_from_pdf_textract,
    extract_text_from_docx, extract_text_from_txt, extract_text_from_eml,
    transcribe_audio_whisper
)
from text_processing import (clean_extracted_text, categorize_document_text, 
                           process_document_with_semantic_chunking)
from entity_extraction import extract_entities_from_chunk
from entity_resolution import resolve_document_entities
from relationship_builder import stage_structural_relationships # Will need db_manager

# S3 imports
if USE_S3_FOR_INPUT:
    from s3_storage import S3FileManager # Removed sync_s3_input_files as queue processor might handle downloads

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(module)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Stage Validation Functions ---
def validate_stage1_requirements():
    """Validate Stage 1 deployment requirements."""
    from config import (OPENAI_API_KEY, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
                       USE_OPENAI_FOR_ENTITY_EXTRACTION, USE_OPENAI_FOR_AUDIO_TRANSCRIPTION, 
                       STAGE_CLOUD_ONLY)
    
    errors = []
    
    # Check required API keys
    if not OPENAI_API_KEY:
        errors.append("OPENAI_API_KEY is required for Stage 1 entity extraction and resolution")
    
    # Check AWS credentials for Textract
    if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
        errors.append("AWS credentials (AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY) are required for Stage 1 deployment (Textract)")
    
    # Verify stage-specific settings
    if DEPLOYMENT_STAGE == STAGE_CLOUD_ONLY:
        if not USE_OPENAI_FOR_ENTITY_EXTRACTION:
            errors.append("USE_OPENAI_FOR_ENTITY_EXTRACTION must be True for Stage 1")
        
        if not USE_OPENAI_FOR_AUDIO_TRANSCRIPTION:
            errors.append("USE_OPENAI_FOR_AUDIO_TRANSCRIPTION must be True for Stage 1")
        
        if not FORCE_CLOUD_LLMS:
            errors.append("FORCE_CLOUD_LLMS must be True for Stage 1")
    
    # If any errors, raise exception with all issues
    if errors:
        error_msg = "Stage 1 validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ValueError(error_msg)
    
    logger.info("Stage 1 requirements validated successfully")

# Document processing state tracking functions
def update_document_state(document_uuid: str, phase: str, status: str, metadata: Dict[str, Any] = None):
    """Update document processing state in Redis."""
    try:
        redis_mgr = get_redis_manager()
        if redis_mgr and redis_mgr.is_available():
            state_key = CacheKeys.format_key(CacheKeys.DOC_STATE, document_uuid=document_uuid)
            
            # Update specific phase status
            redis_mgr.hset(state_key, f"{phase}_status", status)
            redis_mgr.hset(state_key, f"{phase}_timestamp", datetime.now().isoformat())
            
            # Update metadata if provided
            if metadata:
                redis_mgr.hset(state_key, f"{phase}_metadata", json.dumps(metadata))
            
            # Update overall progress
            phases = ['ocr', 'chunking', 'entity_extraction', 'entity_resolution', 'relationship_staging']
            completed_count = sum(1 for p in phases if redis_mgr.hget(state_key, f"{p}_status") == "completed")
            redis_mgr.hset(state_key, "progress", f"{completed_count}/{len(phases)}")
            redis_mgr.hset(state_key, "last_updated", datetime.now().isoformat())
            
            # Log pool stats periodically
            redis_mgr.log_pool_stats()
            
            logger.debug(f"Updated state for document {document_uuid}: {phase} = {status}")
    except Exception as e:
        logger.debug(f"Error updating document state: {e}")

def get_document_state(document_uuid: str) -> Dict[str, Any]:
    """Get document processing state from Redis."""
    try:
        redis_mgr = get_redis_manager()
        if redis_mgr and redis_mgr.is_available():
            state_key = CacheKeys.format_key(CacheKeys.DOC_STATE, document_uuid=document_uuid)
            return redis_mgr.hgetall(state_key)
    except Exception as e:
        logger.debug(f"Error getting document state: {e}")
    return {}

def clear_document_state(document_uuid: str):
    """Clear document processing state from Redis."""
    try:
        redis_mgr = get_redis_manager()
        if redis_mgr and redis_mgr.is_available():
            state_key = CacheKeys.format_key(CacheKeys.DOC_STATE, document_uuid=document_uuid)
            redis_mgr.delete(state_key)
            logger.debug(f"Cleared state for document {document_uuid}")
    except Exception as e:
        logger.debug(f"Error clearing document state: {e}")

# MODIFIED process_single_document:
def process_single_document(db_manager: SupabaseManager, source_doc_sql_id: int, file_path: str, file_name: str, detected_file_type: str, project_sql_id: int):
    logger.info(f"Processing document in Stage {DEPLOYMENT_STAGE} mode: {file_name} (SQL ID: {source_doc_sql_id}) for Project SQL ID: {project_sql_id}")
    
    # Stage-specific validation
    if DEPLOYMENT_STAGE == "1":
        logger.info("Stage 1: Using cloud-only processing pipeline")
        validate_stage1_requirements()
    else:
        logger.info(f"Stage {DEPLOYMENT_STAGE}: Using hybrid/local processing pipeline")

    # --- Phase 1: Text Extraction & Initial Document Node Creation ---
    raw_text = None
    ocr_meta_for_db = None  # This will be the page_level_metadata list from Textract function

    # Fetch full source_document details, especially document_uuid
    source_doc_info = db_manager.get_document_by_id(source_doc_sql_id)
    if not source_doc_info:
        logger.error(f"CRITICAL: Source document with SQL ID {source_doc_sql_id} not found. Aborting processing for this item.")
        return
    
    source_doc_uuid = source_doc_info.get('document_uuid')
    if not source_doc_uuid:
        logger.error(f"CRITICAL: Source document SQL ID {source_doc_sql_id} is missing 'document_uuid'. Aborting.")
        db_manager.update_source_document_text(source_doc_sql_id, None, status="error_missing_uuid")
        return
    
    # Initialize document state tracking
    update_document_state(source_doc_uuid, "ocr", "started", {"file_type": detected_file_type})

    # Update source_documents.ocr_provider and related fields
    # Moved this initial update to be more prominent, before calling extraction
    if detected_file_type == '.pdf':
        db_manager.client.table('source_documents').update({
            'ocr_provider': 'textract',  # Set the provider early
            'textract_job_status': 'not_started'  # Initial state before job submission
            # updated_at is handled by database trigger
        }).eq('id', source_doc_sql_id).execute()

    if detected_file_type == '.pdf':
        logger.info(f"Using AWS Textract for text extraction from PDF: {file_name}")
        # `file_path` can be local, s3:// URI, or Supabase storage URL.
        # `extract_text_from_pdf_textract` now handles these and S3 upload if needed.
        raw_text, ocr_meta_for_db = extract_text_from_pdf_textract(
            db_manager=db_manager,
            source_doc_sql_id=source_doc_sql_id,
            pdf_path_or_s3_uri=file_path,  # This is the path from queue/direct intake
            document_uuid_from_db=source_doc_uuid
        )
        # Textract function now handles DB updates for job status and basic outcomes.
        # We only need to handle the final text and metadata here.
    elif detected_file_type == '.docx':
        raw_text = extract_text_from_docx(file_path)
        ocr_meta_for_db = [{"method": "docx_parser"}]  # Example metadata
        # Update ocr_provider for non-PDFs if applicable
        db_manager.client.table('source_documents').update({
            'ocr_provider': 'docx_parser', 
            'ocr_completed_at': datetime.now().isoformat()
        }).eq('id', source_doc_sql_id).execute()
    elif detected_file_type in ['.txt', 'text/plain']:
        raw_text = extract_text_from_txt(file_path)
        ocr_meta_for_db = [{"method": "txt_parser"}]
        db_manager.client.table('source_documents').update({
            'ocr_provider': None,  # No OCR needed for plain text
            'ocr_completed_at': datetime.now().isoformat()
        }).eq('id', source_doc_sql_id).execute()
    elif detected_file_type == '.eml':
        raw_text = extract_text_from_eml(file_path)
        ocr_meta_for_db = [{"method": "eml_parser"}]
        db_manager.client.table('source_documents').update({
            'ocr_provider': 'eml_parser',
            'ocr_completed_at': datetime.now().isoformat()
        }).eq('id', source_doc_sql_id).execute()
    elif detected_file_type in ['.wav', '.mp3']:  # Add more audio types
        raw_text = transcribe_audio_whisper(file_path)
        ocr_meta_for_db = [{"method": "whisper_transcription"}]
        db_manager.client.table('source_documents').update({
            'ocr_provider': 'openai',  # Example 'openai' for Whisper API
            'ocr_completed_at': datetime.now().isoformat()
        }).eq('id', source_doc_sql_id).execute()
    else:
        logger.warning(f"Unsupported file type for text extraction: {detected_file_type} for {file_name}")
        db_manager.update_source_document_text(source_doc_sql_id, None, status="extraction_unsupported")
        # Update ocr_provider if you have a category for this
        db_manager.client.table('source_documents').update({
            'ocr_provider': None, 
            'initial_processing_status': 'extraction_unsupported'
        }).eq('id', source_doc_sql_id).execute()
        return

    if raw_text:
        # Update source_document entry
        db_manager.update_source_document_text(source_doc_sql_id, raw_text,
                                    ocr_meta_json=json.dumps(ocr_meta_for_db) if ocr_meta_for_db else None,
                                    status="ocr_complete_pending_doc_node")
        # Update Redis state
        update_document_state(source_doc_uuid, "ocr", "completed", 
                            {"text_length": len(raw_text), "method": ocr_meta_for_db[0].get("method") if ocr_meta_for_db else "unknown"})
    else:
        logger.error(f"Failed to extract text for {file_name}")
        db_manager.update_source_document_text(source_doc_sql_id, None, status="extraction_failed")
        update_document_state(source_doc_uuid, "ocr", "failed", {"error": "Text extraction failed"})
        return # Exit processing

    # source_doc_uuid was already verified above, no need to check again
    
    # Fetch project_uuid for consistency if create_neo4j_document_entry needs it
    _project_uuid = db_manager.get_project_by_sql_id_or_global_project_id(project_sql_id, PROJECT_ID_GLOBAL) # You'll need to implement this helper in SupabaseManager

    if not _project_uuid:
        logger.error(f"Critical: Could not determine project_uuid for project_sql_id {project_sql_id}. Aborting {file_name}.")
        db_manager.update_source_document_text(source_doc_sql_id, raw_text, status="error_project_uuid_lookup")
        return


    # Create Neo4j Document Node Entry in SQL (using SupabaseManager)
    # Ensure create_neo4j_document_entry returns (sql_id, uuid)
    neo4j_doc_sql_id, neo4j_doc_uuid = db_manager.create_neo4j_document_entry(
        source_doc_fk_id=source_doc_sql_id, 
        source_doc_uuid=source_doc_uuid, 
        project_fk_id=project_sql_id,
        project_uuid=_project_uuid, # Pass the fetched project_uuid
        file_name=file_name
    )
    if not neo4j_doc_sql_id: # Check if creation failed
        logger.error(f"Failed to create neo4j_documents entry for {file_name}. Aborting further processing.")
        # Status already updated if raw_text failed. If neo4j_doc creation fails, source_doc status should reflect this.
        db_manager.update_source_document_text(source_doc_sql_id, raw_text, status="error_neo4j_doc_creation")
        return
    logger.info(f"Created neo4j_documents entry for {file_name}, SQL ID: {neo4j_doc_sql_id}, Neo4j UUID: {neo4j_doc_uuid}")

    # --- Phase 1.5: Cleaning & Categorization (neo4j_documents) ---
    cleaned_raw_text = clean_extracted_text(raw_text)
    doc_category = categorize_document_text(cleaned_raw_text, ocr_meta_for_db)

    db_manager.update_neo4j_document_details(neo4j_doc_sql_id,
                                  category=doc_category,
                                  file_type=detected_file_type,
                                  cleaned_text=cleaned_raw_text, # This field in SupabaseManager is 'cleaned_text_for_chunking'
                                  status="pending_chunking") # This field is 'processingStatus'
    logger.info(f"Document {neo4j_doc_uuid} categorized as '{doc_category}'. Cleaned text stored.")

    # --- Phase 2: Chunking with Structured Extraction ---
    logger.info(f"Starting chunking and structured extraction for document {neo4j_doc_uuid}...")
    update_document_state(source_doc_uuid, "chunking", "started", {"doc_category": doc_category})
    
    from config import USE_STRUCTURED_EXTRACTION # Already imported
    
    # This function is from text_processing.py and does NOT interact with DB directly
    structured_chunks_data_list, document_structured_data = process_document_with_semantic_chunking(
        db_manager,
        neo4j_doc_sql_id,
        neo4j_doc_uuid,
        cleaned_raw_text,
        ocr_meta_for_db,
        doc_category,
        use_structured_extraction=USE_STRUCTURED_EXTRACTION
    )
    
    if document_structured_data and USE_STRUCTURED_EXTRACTION:
        db_manager.update_neo4j_document_details(
            neo4j_doc_sql_id,
            metadata_json=document_structured_data # SupabaseManager should handle json.dumps if needed
        )
        logger.info(f"Stored document-level structured data for {neo4j_doc_uuid}")
    
    all_chunk_sql_data_for_pipeline = [] # Renamed to avoid confusion with DB schema names
    
    for chunk_data_from_processor in structured_chunks_data_list: # Iterate over the list of chunk dicts
        # Check if chunk was already inserted by process_and_insert_chunks
        if 'sql_id' in chunk_data_from_processor and 'chunk_uuid' in chunk_data_from_processor:
            # Chunk was already inserted, use existing IDs
            chunk_sql_id = chunk_data_from_processor['sql_id']
            chunk_neo4j_uuid = chunk_data_from_processor['chunk_uuid']
            logger.info(f"  Using existing chunk {chunk_data_from_processor['chunkIndex']} (SQL ID: {chunk_sql_id}, Neo4j ID: {chunk_neo4j_uuid})")
        else:
            # Create chunk entry using SupabaseManager
            # Ensure create_chunk_entry returns (sql_id, uuid)
            # SupabaseManager.create_chunk_entry signature:
            # (self, document_fk_id: int, document_uuid: str, chunk_index: int, text_content: str, ...)
            chunk_sql_id, chunk_neo4j_uuid = db_manager.create_chunk_entry(
                document_fk_id=neo4j_doc_sql_id,
                document_uuid=neo4j_doc_uuid, # Pass the parent neo4j_document's UUID
                chunk_index=chunk_data_from_processor['chunkIndex'],  # Changed from 'chunk_index' to 'chunkIndex'
                text_content=chunk_data_from_processor['text'],  # Changed from 'chunk_text' to 'text'
                # cleaned_text=chunk_data_from_processor['text'], # Assuming no separate cleaned text for chunk initially
                char_start_index=chunk_data_from_processor['char_start_index'],
                char_end_index=chunk_data_from_processor['char_end_index'],
                metadata_json=chunk_data_from_processor.get('metadata_json') # Ensure this is a dict or JSON string
            )
        
        if chunk_sql_id and chunk_neo4j_uuid:
            logger.info(f"  Created chunk {chunk_data_from_processor['chunkIndex']} (SQL ID: {chunk_sql_id}, Neo4j ID: {chunk_neo4j_uuid}) for doc {neo4j_doc_uuid}")
            
            # Prepare data for subsequent pipeline stages
            # This is data held in memory for the current document processing run
            chunk_info_for_pipeline = {
                "sql_id": chunk_sql_id,
                "neo4j_id": chunk_neo4j_uuid, # This is 'chunkId' in Supabase
                "text": chunk_data_from_processor['text'],  # Changed from 'chunk_text' to 'text'
                "index_int": chunk_data_from_processor['chunkIndex'], # Changed from 'chunk_index' to 'chunkIndex'
                "document_id_neo4j": neo4j_doc_uuid, # Parent document's Neo4j UUID
                "structured_data_from_text_processing": chunk_data_from_processor.get('structured_data') # If available
            }
            all_chunk_sql_data_for_pipeline.append(chunk_info_for_pipeline)
        else:
            logger.error(f"Failed to create chunk entry for index {chunk_data_from_processor['chunk_index']}, doc SQL ID {neo4j_doc_sql_id}. Skipping NER for this chunk.")

    db_manager.update_neo4j_document_status(neo4j_doc_sql_id, "pending_ner") # status field is 'processingStatus'
    update_document_state(source_doc_uuid, "chunking", "completed", {"chunk_count": len(all_chunk_sql_data_for_pipeline)})

    # --- Phase 3: Entity Extraction (neo4j_entity_mentions) ---
    logger.info(f"Starting entity extraction for document {neo4j_doc_uuid}...")
    update_document_state(source_doc_uuid, "entity_extraction", "started", {"chunk_count": len(all_chunk_sql_data_for_pipeline)})
    all_entity_mentions_for_doc_with_sql_ids = []
    
    for chunk_data_mem in all_chunk_sql_data_for_pipeline: # Use the in-memory list
        mentions_in_chunk_attrs = extract_entities_from_chunk(chunk_data_mem["text"], chunk_data_mem["index_int"])
        logger.info(f"  Extracted {len(mentions_in_chunk_attrs)} entities from chunk {chunk_data_mem['index_int']}")
        for idx, mention_attrs in enumerate(mentions_in_chunk_attrs):
            logger.debug(f"  Processing entity {idx + 1}/{len(mentions_in_chunk_attrs)}: {mention_attrs.get('value', 'UNKNOWN')}")
            # SupabaseManager.create_entity_mention_entry signature:
            # (self, chunk_sql_id: int, chunk_uuid: str, value: str, entity_type_label: str, ...)
            em_sql_id, em_neo4j_uuid = db_manager.create_entity_mention_entry(
                chunk_sql_id=chunk_data_mem["sql_id"], # This is chunk_fk_id
                chunk_uuid=chunk_data_mem["neo4j_id"], # This is chunk_uuid
                value=mention_attrs["value"],
                norm_value=mention_attrs["normalizedValue"],
                display_value=mention_attrs.get("displayValue"),
                entity_type_label=mention_attrs["entity_type"], # This is 'entity_type'
                rationale=mention_attrs.get("rationale"),
                attributes_json_str=json.dumps(mention_attrs.get("attributes_json", {})), # Ensure it's string
                phone=mention_attrs.get("phone"),
                email=mention_attrs.get("email"),
                start_offset=mention_attrs.get("offsetStart"), # 'start_char_offset_in_chunk'
                end_offset=mention_attrs.get("offsetEnd") # 'end_char_offset_in_chunk'
            )
            if em_sql_id and em_neo4j_uuid:
                logger.info(f"    Extracted entity '{mention_attrs['value']}' (SQL ID: {em_sql_id}, Neo4j ID: {em_neo4j_uuid}) in chunk {chunk_data_mem['neo4j_id']}")
                
                full_mention_data_for_resolution = mention_attrs.copy()
                full_mention_data_for_resolution['entity_mention_id_neo4j'] = em_neo4j_uuid # 'entityMentionId'
                full_mention_data_for_resolution['entity_mention_sql_id'] = em_sql_id
                full_mention_data_for_resolution['parent_chunk_id_neo4j'] = chunk_data_mem['neo4j_id'] # 'chunk_uuid'
                full_mention_data_for_resolution['chunk_index_int'] = chunk_data_mem['index_int']
                all_entity_mentions_for_doc_with_sql_ids.append(full_mention_data_for_resolution)
            else:
                logger.error(f"Failed to create entity mention entry for '{mention_attrs['value']}' in chunk SQL ID {chunk_data_mem['sql_id']}.")

    db_manager.update_neo4j_document_status(neo4j_doc_sql_id, "pending_canonicalization")
    update_document_state(source_doc_uuid, "entity_extraction", "completed", {"entity_count": len(all_entity_mentions_for_doc_with_sql_ids)})

    # --- Phase 4: Canonicalization (neo4j_canonical_entities) ---
    logger.info(f"Starting entity canonicalization for document {neo4j_doc_uuid}...")
    update_document_state(source_doc_uuid, "entity_resolution", "started", {"entity_count": len(all_entity_mentions_for_doc_with_sql_ids)})
    
    resolved_canonical_entity_data_list, updated_mentions_with_temp_canon_ids = \
        resolve_document_entities(all_entity_mentions_for_doc_with_sql_ids, cleaned_raw_text)
    
    map_temp_canon_id_to_neo4j_uuid = {}
    final_canonical_entities_for_relationships = []

    for ce_attrs_temp in resolved_canonical_entity_data_list:
        # SupabaseManager.create_canonical_entity_entry signature:
        # (self, neo4j_doc_sql_id: int, document_uuid: str, canonical_name: str, entity_type_label: str, ...)
        ce_sql_id, ce_neo4j_uuid = db_manager.create_canonical_entity_entry(
            neo4j_doc_sql_id=neo4j_doc_sql_id, # This is 'documentId' (FK to neo4j_documents.id)
            document_uuid=neo4j_doc_uuid, # This is 'document_uuid' (the UUID of the neo4j_document)
            canonical_name=ce_attrs_temp["canonicalName"],
            entity_type_label=ce_attrs_temp["entity_type"], # 'entity_type'
            aliases_json=ce_attrs_temp.get("allKnownAliasesInDoc_json"), # 'allKnownAliasesInDoc'
            mention_count=ce_attrs_temp.get("mention_count_in_doc", 1), # 'mention_count'
            first_seen_idx=ce_attrs_temp.get("firstSeenAtChunkIndex_int", 0) # 'firstSeenAtChunkIndex'
        )
        if ce_sql_id and ce_neo4j_uuid:
            map_temp_canon_id_to_neo4j_uuid[ce_attrs_temp["canonicalEntityId_temp"]] = ce_neo4j_uuid
            logger.info(f"  Created canonical entity '{ce_attrs_temp['canonicalName']}' (SQL ID: {ce_sql_id}, Neo4j ID: {ce_neo4j_uuid})")
            
            ce_attrs_temp_copy = ce_attrs_temp.copy()
            ce_attrs_temp_copy['canonical_entity_id_neo4j'] = ce_neo4j_uuid # 'canonicalEntityId'
            final_canonical_entities_for_relationships.append(ce_attrs_temp_copy)
        else:
            logger.error(f"Failed to create canonical entity entry for '{ce_attrs_temp['canonicalName']}'.")

    # Update entity mentions with the actual Neo4j UUID of their canonical entity
    # The db_utils.update_entity_mention_with_canonical_id was a placeholder.
    # In Supabase, this link is typically made when creating relationships,
    # or by adding a 'resolved_canonical_entity_uuid' column to 'neo4j_entity_mentions' table
    # and updating it. The SupabaseManager has update_entity_mention_with_canonical_id, but it was a pass.
    # For now, we assume the relationship builder will use the resolved_canonical_id_neo4j.
    # If you want to persist this link on the neo4j_entity_mentions table,
    # you'll need to add a column like `resolved_canonical_entity_uuid` and update `SupabaseManager`.
    final_entity_mentions_for_relationships = []
    for em_data_updated in updated_mentions_with_temp_canon_ids:
        temp_canon_id = em_data_updated.get("resolved_canonical_id_temp")
        if temp_canon_id and temp_canon_id in map_temp_canon_id_to_neo4j_uuid:
            actual_canonical_neo4j_uuid = map_temp_canon_id_to_neo4j_uuid[temp_canon_id]
            # Call SupabaseManager to update the entity mention if schema supports it
            # db_manager.update_entity_mention_with_canonical_id(em_data_updated["entity_mention_sql_id"], actual_canonical_neo4j_uuid)
            # logger.debug(f"  Updating EM SQL ID {em_data_updated['entity_mention_sql_id']} with Canonical Neo4j ID {actual_canonical_neo4j_uuid}")
            em_data_updated['resolved_canonical_id_neo4j'] = actual_canonical_neo4j_uuid
        else:
            logger.warning(f"Could not find mapping for temp canonical ID {temp_canon_id} for EM SQL ID {em_data_updated['entity_mention_sql_id']}")
        final_entity_mentions_for_relationships.append(em_data_updated)

    db_manager.update_neo4j_document_status(neo4j_doc_sql_id, "pending_relationships")
    update_document_state(source_doc_uuid, "entity_resolution", "completed", {"canonical_count": len(final_canonical_entities_for_relationships)})

    # --- Phase 5: Relationship Staging ---
    logger.info(f"Starting relationship staging for document {neo4j_doc_uuid}...")
    update_document_state(source_doc_uuid, "relationship_staging", "started", {})
    
    doc_data_for_rels = { # Align with relationship_builder.py expectations
        "documentId": neo4j_doc_uuid, # This is document_id_neo4j
        "sql_id": neo4j_doc_sql_id,
        "category": doc_category,
        "file_type": detected_file_type,
        "name": file_name
    }
    
    # `all_chunk_sql_data_for_pipeline` items need 'chunkId' key for relationship_builder
    # Its items currently have 'neo4j_id' (which is chunk_uuid or chunkId)
    chunks_for_rels = []
    for c in all_chunk_sql_data_for_pipeline:
        chunks_for_rels.append({
            "chunkId": c["neo4j_id"], # This is the chunk_uuid
            "chunkIndex": c["index_int"], # Ensure this is chunkIndex from schema
            # Add other fields if relationship_builder needs them
        })
    
    # `final_entity_mentions_for_relationships` items need 'entityMentionId'
    # Its items currently have 'entity_mention_id_neo4j'
    mentions_for_rels = []
    for m in final_entity_mentions_for_relationships:
        mentions_for_rels.append({
            "entityMentionId": m["entity_mention_id_neo4j"], # This is the entity_mention_uuid
            "chunk_uuid": m["parent_chunk_id_neo4j"], # This is the parent chunk's UUID
            "resolved_canonical_id_neo4j": m.get("resolved_canonical_id_neo4j")
            # Add other fields if relationship_builder needs them
        })

    # `final_canonical_entities_for_relationships` items need 'canonicalEntityId'
    # Its items currently have 'canonical_entity_id_neo4j'
    canonicals_for_rels = []
    for ce in final_canonical_entities_for_relationships:
        canonicals_for_rels.append({
            "canonicalEntityId": ce["canonical_entity_id_neo4j"], # This is the canonical_entity_uuid
            # Add other fields if relationship_builder needs them
        })

    # stage_structural_relationships expects project_id to be the UUID of the project
    stage_structural_relationships(
        db_manager, # Pass SupabaseManager instance
        doc_data_for_rels,
        _project_uuid, # Pass Project UUID
        chunks_for_rels,
        mentions_for_rels,
        canonicals_for_rels
    )

    # Final status update for the source document itself
    db_manager.update_source_document_text(source_doc_sql_id, raw_text, status="completed")
    # The trigger update_queue_on_document_terminal_state will handle the queue item.
    # Also update neo4j_document status
    db_manager.update_neo4j_document_status(neo4j_doc_sql_id, "complete")
    
    # Complete Redis state tracking
    update_document_state(source_doc_uuid, "relationship_staging", "completed", {})
    logger.info(f"Successfully processed document {file_name} (Neo4j ID: {neo4j_doc_uuid})")
    
    # Log final state summary
    final_state = get_document_state(source_doc_uuid)
    if final_state:
        logger.info(f"Document {source_doc_uuid} processing complete. Progress: {final_state.get('progress', 'unknown')}")
    
    return True


# MODIFIED main function
def preload_critical_cache():
    """Preload critical data into cache on startup."""
    logger.info("Preloading critical cache data...")
    
    redis_mgr = get_redis_manager()
    if not redis_mgr.is_available():
        logger.warning("Redis not available, skipping cache preload")
        return
        
    db_manager = SupabaseManager()
    
    try:
        # Preload active document states
        active_docs = db_manager.client.table('source_documents').select(
            'document_uuid', 'initial_processing_status'
        ).in_('initial_processing_status', ['processing', 'pending_ocr']).execute()
        
        preloaded_count = 0
        for doc in active_docs.data:
            state_key = CacheKeys.format_key(CacheKeys.DOC_STATE, document_uuid=doc['document_uuid'])
            redis_mgr.hset(state_key, 'status', doc['initial_processing_status'])
            redis_mgr.hset(state_key, 'preloaded', 'true')
            preloaded_count += 1
            
        # Preload recent Textract job statuses
        from datetime import datetime, timedelta
        recent_jobs = db_manager.client.table('textract_jobs').select(
            'job_id', 'job_status'
        ).gte('created_at', (datetime.now() - timedelta(hours=1)).isoformat()).execute()
        
        job_count = 0
        for job in recent_jobs.data:
            cache_key = CacheKeys.format_key(CacheKeys.TEXTRACT_JOB_STATUS, job_id=job['job_id'])
            redis_mgr.set_cached(cache_key, {'JobStatus': job['job_status']}, ttl=3600)
            job_count += 1
            
        logger.info(f"Preloaded {preloaded_count} document states and {job_count} job statuses")
        
        # Run comprehensive cache warming
        logger.info("Running cache warming for recent documents...")
        warming_results = run_cache_warming(hours=24, limit=50)
        logger.info(f"Cache warming results: {warming_results}")
        
    except Exception as e:
        logger.error(f"Error during cache preloading: {e}")


def main(processing_mode: str): # Renamed arg for clarity
    logger.info(f"Starting Legal NLP Pre-processing Pipeline in '{processing_mode}' mode (Stage {DEPLOYMENT_STAGE})...")
    
    # Preload cache before processing
    preload_critical_cache()
    
    # Stage-aware model initialization
    if DEPLOYMENT_STAGE == "1":
        logger.info("Stage 1: Initializing cloud-only processing")
        validate_stage1_requirements()
        from models_init import validate_cloud_api_keys
        validate_cloud_api_keys()
    else:
        logger.info(f"Stage {DEPLOYMENT_STAGE}: Initializing with local models")
        initialize_all_models() # Load all ML/DL models once

    db_manager = SupabaseManager() # Instantiate SupabaseManager

    # Get or Create Project (needed for both modes)
    # project_sql_id, project_uuid = db_manager.get_or_create_project(PROJECT_ID_GLOBAL, "My Legal Project")
    # Project info will be fetched by QueueProcessor or here in direct mode.

    if processing_mode == "queue":
        logger.info("Running in QUEUE mode.")
        from queue_processor import QueueProcessor # Import here to avoid circular deps if any
        
        # Default queue processor arguments, can be configurable too
        queue_proc = QueueProcessor(batch_size=5) # Batch size from config or arg
        queue_proc.process_queue(max_documents_to_process=None, single_run=False) # Run continuously

    elif processing_mode == "direct":
        logger.info("Running in DIRECT mode (processing local/S3 files directly).")
        
        # Get Project Info for direct mode
        try:
            project_sql_id, project_uuid_for_direct_mode = db_manager.get_or_create_project(PROJECT_ID_GLOBAL, "My Legal Project")
            logger.info(f"Using Project SQL ID: {project_sql_id}, Project UUID: {project_uuid_for_direct_mode}")
        except Exception as e:
            logger.error(f"Failed to get or create project in direct mode: {e}. Exiting.")
            return
            
        # Logic for S3 or local file iteration (from original main)
        source_files_to_process = []
        s3_file_manager_instance = None
        if USE_S3_FOR_INPUT:
            logger.info("Using S3 for input files in DIRECT mode...")
            s3_file_manager_instance = S3FileManager()
            try:
                logger.info(f"Syncing files from S3 bucket to {S3_TEMP_DOWNLOAD_DIR}")
                # This syncs ALL files. For direct mode, you might want to process one by one.
                # For simplicity, let's assume it syncs and then we iterate.
                # A true "direct S3" mode might list S3 keys and download one by one.
                # The current s3_utils.sync_s3_input_files implies downloading many.
                # This could be inefficient if only processing a few in direct mode.
                # Let's adapt to download one by one for direct s3.
                # For now, using the existing sync logic for simplicity of prompt.
                # Re-evaluate if s3_utils.sync_input_files should be used or a more targeted download.
                # The original code syncs ALL files then iterates.

                # The original code had sync_s3_input_files here.
                # For direct mode, it's better to list keys and process one by one.
                # However, the prompt is getting very long. Let's stick to the user's original flow for S3 direct.
                # This means `s3_manager.sync_input_files` would be called if that's the intended S3 direct mode.
                # The provided `main_pipeline.py` used `s3_manager.sync_input_files(S3_TEMP_DOWNLOAD_DIR)`.

                local_files_synced = s3_file_manager_instance.sync_input_files(S3_TEMP_DOWNLOAD_DIR) # Assumes this method exists
                
                for file_p in local_files_synced:
                    file_n = os.path.basename(file_p)
                    source_files_to_process.append({
                        "path": file_p, "name": file_n, "type": os.path.splitext(file_n)[1].lower(),
                        "s3_original": True # Flag that it came from S3 for potential cleanup
                    })
                logger.info(f"Synced {len(local_files_synced)} files from S3 for direct processing.")

            except Exception as e:
                logger.error(f"Error syncing files from S3 in DIRECT mode: {e}", exc_info=True)
                # Decide if to proceed with local files or exit
        else: # Local directory
            if os.path.exists(SOURCE_DOCUMENT_DIR):
                for root, _, files in os.walk(SOURCE_DOCUMENT_DIR):
                    for file in files:
                        source_files_to_process.append({
                            "path": os.path.join(root, file), "name": file, "type": os.path.splitext(file)[1].lower(),
                            "s3_original": False
                        })
            else:
                logger.warning(f"Source document directory '{SOURCE_DOCUMENT_DIR}' does not exist for DIRECT mode.")

        for file_info in source_files_to_process:
            try:
                # Create source_document entry using SupabaseManager
                src_doc_sql_id, src_doc_uuid = db_manager.create_source_document_entry(
                    project_fk_id=project_sql_id, # SQL ID of the project
                    project_uuid=project_uuid_for_direct_mode,  # UUID of the project
                    original_file_path=file_info["path"],
                    original_file_name=file_info["name"],
                    detected_file_type=file_info["type"]
                    # S3 key can also be stored here if file_info["s3_original"] is true
                )
                if not src_doc_sql_id:
                    logger.error(f"Failed to create source document entry for {file_info['name']} in DIRECT mode. Skipping.")
                    continue
                
                logger.info(f"DIRECT Intake: {file_info['name']} registered with SQL ID: {src_doc_sql_id}, UUID: {src_doc_uuid}")

                # CRITICAL CHANGE: Submit to Celery instead of processing synchronously
                from celery_submission import submit_document_to_celery
                
                # First, ensure file is in S3 if it's a local file
                final_path = file_info["path"]
                if not file_info.get("s3_original", False) and not final_path.startswith("s3://"):
                    # Upload local file to S3
                    from s3_storage import S3Storage
                    s3_storage = S3Storage(bucket_name=S3_PRIMARY_DOCUMENT_BUCKET)
                    final_path = s3_storage.upload_document(
                        file_path=file_info["path"],
                        original_filename=file_info["name"]
                    )
                    logger.info(f"Uploaded local file to S3: {final_path}")
                
                # Submit to Celery
                task_id, success = submit_document_to_celery(
                    document_id=src_doc_sql_id,
                    document_uuid=src_doc_uuid,
                    file_path=final_path,
                    file_type=file_info["type"],
                    project_id=PROJECT_ID_GLOBAL
                )
                
                if success:
                    logger.info(f"✅ Document {file_info['name']} submitted to Celery. Task ID: {task_id}")
                else:
                    logger.error(f"❌ Failed to submit {file_info['name']} to Celery")
                    db_manager.update_source_document_text(src_doc_sql_id, None, status="error_celery_submission")
            except Exception as e:
                logger.error(f"Error processing file {file_info['name']} in DIRECT mode: {e}", exc_info=True)
                # If src_doc_sql_id was created, mark it as error
                if 'src_doc_sql_id' in locals() and src_doc_sql_id:
                    db_manager.update_source_document_text(src_doc_sql_id, None, status="error_direct_processing")


        # CSV Export (remains commented as per original)
        logger.info("Legal NLP Pipeline (DIRECT mode) completed.")
        
        # Clean up S3 temporary files if used in direct mode
        if USE_S3_FOR_INPUT and s3_file_manager_instance:
            try:
                logger.info("Cleaning up S3 temporary files from DIRECT mode processing...")
                s3_file_manager_instance.cleanup_temp_files() # Ensure this method exists and works
                logger.info("S3 temporary files (DIRECT mode) cleaned up.")
            except Exception as e:
                logger.error(f"Error cleaning up S3 temp files (DIRECT mode): {e}")
    else:
        logger.error(f"Invalid processing_mode: {processing_mode}. Choose 'direct' or 'queue'.")

    # db_sess.close() - No longer needed as SupabaseManager manages its client.
    logger.info("Processing finished.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Legal NLP Pre-processing Pipeline.")
    parser.add_argument('--mode', type=str, default='queue', choices=['direct', 'queue'],
                        help="Processing mode: 'direct' for immediate file processing, 'queue' for queue-based processing.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Set the logging level.")

    args = parser.parse_args()

    # Reconfigure logging level if specified
    logging.getLogger().setLevel(args.log_level.upper())
    logger.setLevel(args.log_level.upper())
    for handler in logging.getLogger().handlers: # Apply to all handlers
        handler.setLevel(args.log_level.upper())

    main(processing_mode=args.mode)