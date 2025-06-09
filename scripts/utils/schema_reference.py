#!/usr/bin/env python3
"""
Authoritative schema reference based on actual database
Generated from information_schema queries
"""

SCHEMA_REFERENCE = {
    'source_documents': {
        'primary_key': 'document_uuid',  # NOT 'uuid'
        'foreign_keys': {
            'project_uuid': 'projects.project_id'  # Note: misnamed column
        },
        'status_columns': [
            'status',
            'textract_job_status',  # NOT 'ocr_status'
            'celery_status'
        ],
        'key_columns': [
            'document_uuid',
            'project_uuid',
            'file_name',  # NOT 'filename'
            's3_key',
            's3_bucket',
            'textract_job_id',
            'textract_job_status'
        ]
    },
    'document_chunks': {
        'primary_key': 'id',
        'foreign_key': 'document_uuid',  # NOT 'source_document_uuid'
        'content_column': 'cleaned_text',  # Actual candidates: 'text', 'cleaned_text'. Using 'cleaned_text'. NOT 'content'
        'key_columns': [
            'id',
            'document_uuid',
            'chunk_index',
            'cleaned_text'
        ]
    },
    'entity_mentions': {
        'primary_key': 'id',
        'foreign_key': 'document_uuid',  # NOT 'source_document_uuid'
        'key_columns': [
            'id',
            'document_uuid',
            'entity_text',
            'entity_type'
        ]
    },
    'canonical_entities': {
        'primary_key': 'id',
        'foreign_key': None,  # No direct FK column to source_documents like 'created_from_document_uuid' exists.
        'key_columns': [
            'id',
            'canonical_name',
            'entity_type'
        ]
    },
    'relationship_staging': {
        'primary_key': 'id',
        'foreign_key': 'source_chunk_uuid',  # Links to document_chunks.chunk_uuid, not directly to source_documents.document_uuid.
        'key_columns': [
            'id',
            'source_entity_uuid',
            'target_entity_uuid',
            'relationship_type'
        ]
    },
    'processing_tasks': {
        'primary_key': 'id',
        'foreign_key': 'document_id',  # NOT 'document_uuid'
        'key_columns': [
            'id',
            'celery_task_id',  # NOT 'task_id'
            'document_id',  # NOT 'document_uuid'
            'task_type',
            'status',
            'error_message'
        ]
    }
}

def get_correct_column_name(table, purpose):
    """Get the correct column name for a given purpose"""
    if purpose == 'document_fk':
        # Foreign key to documents table
        if table == 'canonical_entities':
            return SCHEMA_REFERENCE['canonical_entities'].get('foreign_key') # Was 'created_from_document_uuid', now reflects corrected SCHEMA_REFERENCE
        else:
            return 'document_uuid'
    elif purpose == 'content':
        if table == 'document_chunks':
            return SCHEMA_REFERENCE['document_chunks'].get('content_column') # Was 'text_content', now reflects corrected SCHEMA_REFERENCE
        else:
            return 'content'
    return None

# Common query patterns with correct column names
QUERY_PATTERNS = {
    'count_chunks': """
        SELECT COUNT(*) FROM document_chunks 
        WHERE document_uuid = :doc_uuid
    """,
    'count_entities': """
        SELECT COUNT(*) FROM entity_mentions 
        WHERE document_uuid = :doc_uuid
    """,
    'count_canonical': """
        SELECT COUNT(*) FROM canonical_entities 
        WHERE 1=0 -- FIXME: 'created_from_document_uuid' does not exist. Original SCHEMA_REFERENCE['canonical_entities']['foreign_key'] was corrected to None. This query needs re-evaluation based on actual linking logic to documents.
    """,
    'count_relationships': """
        SELECT COUNT(*) FROM relationship_staging 
        WHERE source_chunk_uuid = :chunk_uuid -- Corrected FK from 'document_uuid'. Parameter :doc_uuid may need to become :chunk_uuid in calling code.
    """,
    'document_status': """
        SELECT document_uuid, file_name, status, textract_job_status, 
               textract_job_id, s3_key, s3_bucket
        FROM source_documents 
        WHERE document_uuid = :doc_uuid
    """,
    'pipeline_summary': """
        SELECT 
            sd.document_uuid,
            sd.file_name,
            sd.status,
            sd.textract_job_status,
            COUNT(DISTINCT dc.id) as chunk_count,
            COUNT(DISTINCT em.id) as entity_count,
            COUNT(DISTINCT ce.id) as canonical_count,
            COUNT(DISTINCT rs.id) as relationship_count
        FROM source_documents sd
        LEFT JOIN document_chunks dc ON sd.document_uuid = dc.document_uuid
        LEFT JOIN entity_mentions em ON sd.document_uuid = em.document_uuid
        LEFT JOIN canonical_entities ce ON 1=0 -- FIXME: 'ce.created_from_document_uuid' does not exist. Original SCHEMA_REFERENCE['canonical_entities']['foreign_key'] corrected to None. Join condition needs re-evaluation.
        LEFT JOIN relationship_staging rs ON dc.chunk_uuid = rs.source_chunk_uuid -- Corrected FK. Original join 'sd.document_uuid = rs.document_uuid' was invalid.
        WHERE sd.document_uuid = :doc_uuid
        GROUP BY sd.document_uuid, sd.file_name, sd.status, sd.textract_job_status
    """
}