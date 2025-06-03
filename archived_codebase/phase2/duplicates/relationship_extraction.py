"""
Relationship extraction from document content
Analyzes text to find relationships between canonical entities
"""
import os
import re
import uuid
import json
import logging
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger(__name__)

# Legal relationship patterns
LEGAL_RELATIONSHIP_PATTERNS = [
    # Party relationships
    (r'{entity1}\s+(?:v\.?|versus|against)\s+{entity2}', 'OPPOSING_PARTY', 0.9),
    (r'{entity1}.*?(?:plaintiff|petitioner|claimant).*?{entity2}.*?(?:defendant|respondent)', 'PLAINTIFF_V_DEFENDANT', 0.85),
    (r'{entity2}.*?(?:defendant|respondent).*?{entity1}.*?(?:plaintiff|petitioner|claimant)', 'PLAINTIFF_V_DEFENDANT', 0.85),
    
    # Representation
    (r'{entity1}\s+(?:represents?|represented\s+by|counsel\s+for)\s+{entity2}', 'REPRESENTS', 0.8),
    (r'{entity2}\s+(?:represented\s+by|retained)\s+{entity1}', 'REPRESENTS', 0.8),
    
    # Employment/Corporate
    (r'{entity1}\s+(?:is|was|serves?\s+as)\s+(?:an?\s+)?(?:employee|officer|director)\s+(?:of|at)\s+{entity2}', 'EMPLOYED_BY', 0.85),
    (r'{entity1}\s+(?:works?|worked)\s+(?:for|at)\s+{entity2}', 'EMPLOYED_BY', 0.8),
    (r'{entity1}\s+(?:is|was)\s+(?:a\s+)?(?:subsidiary|division|unit)\s+of\s+{entity2}', 'SUBSIDIARY_OF', 0.9),
    (r'{entity1}\s+(?:owns?|owned|acquired)\s+{entity2}', 'OWNS', 0.85),
    
    # Location
    (r'{entity1}\s+(?:located|based|headquartered)\s+(?:in|at)\s+{entity2}', 'LOCATED_IN', 0.8),
    (r'{entity1}.*?(?:a\s+)?{entity2}\s+(?:corporation|company|entity)', 'INCORPORATED_IN', 0.75),
    
    # Contractual
    (r'{entity1}\s+(?:entered\s+into|signed|executed)\s+(?:a\s+)?(?:contract|agreement)\s+with\s+{entity2}', 'CONTRACT_WITH', 0.85),
    (r'(?:contract|agreement)\s+between\s+{entity1}\s+and\s+{entity2}', 'CONTRACT_WITH', 0.9),
    
    # Financial
    (r'{entity1}\s+(?:paid|pays|owed|owes)\s+.*?\s+to\s+{entity2}', 'FINANCIAL_TRANSACTION', 0.8),
    (r'{entity2}\s+(?:received|receives)\s+.*?\s+from\s+{entity1}', 'FINANCIAL_TRANSACTION', 0.8),
    
    # Temporal/Event
    (r'{entity1}.*?(?:on|dated?)\s+{entity2}', 'OCCURRED_ON', 0.7),
    (r'{entity1}.*?(?:filed|submitted|served).*?{entity2}', 'FILED_ON', 0.75),
]

def extract_relationships_from_text(
    text: str,
    canonical_entities: List[Dict[str, Any]],
    chunk_uuid: Optional[str] = None,
    confidence_threshold: float = 0.7
) -> List[Dict[str, Any]]:
    """
    Extract relationships between canonical entities from text
    
    Args:
        text: Text to analyze
        canonical_entities: List of canonical entities to find relationships between
        chunk_uuid: UUID of the chunk this text comes from
        confidence_threshold: Minimum confidence to include relationship
        
    Returns:
        List of extracted relationships
    """
    relationships = []
    
    # Create entity lookup by name variations
    entity_lookup = {}
    for entity in canonical_entities:
        canonical_name = entity.get('canonical_name', '')
        entity_uuid = entity.get('canonical_entity_uuid')
        entity_type = entity.get('entity_type')
        
        # Add canonical name
        entity_lookup[canonical_name.lower()] = (entity_uuid, canonical_name, entity_type)
        
        # Add aliases
        for alias in entity.get('aliases', []):
            entity_lookup[alias.lower()] = (entity_uuid, canonical_name, entity_type)
    
    # Process each relationship pattern
    for pattern_template, rel_type, base_confidence in LEGAL_RELATIONSHIP_PATTERNS:
        # Try all entity pairs
        for name1, (uuid1, canonical1, type1) in entity_lookup.items():
            for name2, (uuid2, canonical2, type2) in entity_lookup.items():
                if uuid1 == uuid2:  # Skip self-relationships
                    continue
                
                # Skip if relationship doesn't make sense for entity types
                if not is_valid_relationship(type1, type2, rel_type):
                    continue
                
                # Create pattern with actual entity names
                pattern = pattern_template.format(
                    entity1=re.escape(name1),
                    entity2=re.escape(name2)
                )
                
                # Search for pattern in text (case insensitive)
                matches = list(re.finditer(pattern, text, re.IGNORECASE | re.DOTALL))
                
                if matches:
                    # Extract context around match
                    for match in matches:
                        start = max(0, match.start() - 50)
                        end = min(len(text), match.end() + 50)
                        context = text[start:end].strip()
                        
                        # Adjust confidence based on context quality
                        confidence = calculate_confidence(
                            base_confidence,
                            context,
                            name1,
                            name2,
                            rel_type
                        )
                        
                        if confidence >= confidence_threshold:
                            relationship = {
                                'relationship_uuid': uuid.uuid4(),
                                'source_entity_uuid': uuid1,
                                'source_entity_name': canonical1,
                                'source_entity_type': type1,
                                'target_entity_uuid': uuid2,
                                'target_entity_name': canonical2,
                                'target_entity_type': type2,
                                'relationship_type': rel_type,
                                'confidence_score': confidence,
                                'context': context,
                                'chunk_uuid': chunk_uuid,
                                'extraction_method': 'pattern_matching',
                                'created_at': datetime.utcnow()
                            }
                            
                            # Check if we already have this relationship
                            if not is_duplicate_relationship(relationships, relationship):
                                relationships.append(relationship)
                                logger.debug(f"Found relationship: {canonical1} -[{rel_type}]-> {canonical2} (confidence: {confidence:.2f})")
    
    return relationships

def is_valid_relationship(type1: str, type2: str, rel_type: str) -> bool:
    """Check if a relationship type makes sense for the entity types"""
    valid_combinations = {
        'OPPOSING_PARTY': [('PERSON', 'PERSON'), ('PERSON', 'ORG'), ('ORG', 'ORG')],
        'PLAINTIFF_V_DEFENDANT': [('PERSON', 'PERSON'), ('PERSON', 'ORG'), ('ORG', 'ORG')],
        'REPRESENTS': [('PERSON', 'PERSON'), ('PERSON', 'ORG'), ('ORG', 'PERSON'), ('ORG', 'ORG')],
        'EMPLOYED_BY': [('PERSON', 'ORG')],
        'SUBSIDIARY_OF': [('ORG', 'ORG')],
        'OWNS': [('PERSON', 'ORG'), ('ORG', 'ORG')],
        'LOCATED_IN': [('PERSON', 'LOCATION'), ('ORG', 'LOCATION')],
        'INCORPORATED_IN': [('ORG', 'LOCATION')],
        'CONTRACT_WITH': [('PERSON', 'PERSON'), ('PERSON', 'ORG'), ('ORG', 'ORG')],
        'FINANCIAL_TRANSACTION': [('PERSON', 'PERSON'), ('PERSON', 'ORG'), ('ORG', 'ORG')],
        'OCCURRED_ON': [('ANY', 'DATE')],  # Any entity type with date
        'FILED_ON': [('PERSON', 'DATE'), ('ORG', 'DATE')],
    }
    
    # Get valid combinations for this relationship type
    valid = valid_combinations.get(rel_type, [])
    
    # Check if this combination is valid
    for valid_type1, valid_type2 in valid:
        if valid_type1 == 'ANY' or valid_type2 == 'ANY':
            return True
        if (type1 == valid_type1 and type2 == valid_type2):
            return True
    
    return False

def calculate_confidence(
    base_confidence: float,
    context: str,
    entity1: str,
    entity2: str,
    rel_type: str
) -> float:
    """
    Calculate adjusted confidence based on context quality
    """
    confidence = base_confidence
    
    # Boost confidence for certain indicators
    boost_indicators = {
        'OPPOSING_PARTY': ['plaintiff', 'defendant', 'petitioner', 'respondent', 'lawsuit'],
        'REPRESENTS': ['attorney', 'lawyer', 'counsel', 'law firm', 'representation'],
        'EMPLOYED_BY': ['employee', 'worked', 'position', 'title', 'department'],
        'CONTRACT_WITH': ['agreement', 'contract', 'terms', 'obligations', 'parties'],
        'FINANCIAL_TRANSACTION': ['paid', 'payment', 'invoice', 'amount', 'dollars', '$'],
    }
    
    indicators = boost_indicators.get(rel_type, [])
    for indicator in indicators:
        if indicator.lower() in context.lower():
            confidence += 0.05
    
    # Reduce confidence if entities are very far apart
    entity1_pos = context.lower().find(entity1.lower())
    entity2_pos = context.lower().find(entity2.lower())
    if entity1_pos >= 0 and entity2_pos >= 0:
        distance = abs(entity2_pos - entity1_pos)
        if distance > 100:
            confidence -= 0.1
    
    # Cap confidence at 0.95
    return min(0.95, max(0.0, confidence))

def is_duplicate_relationship(
    existing_relationships: List[Dict[str, Any]],
    new_relationship: Dict[str, Any]
) -> bool:
    """Check if relationship already exists"""
    for existing in existing_relationships:
        if (existing['source_entity_uuid'] == new_relationship['source_entity_uuid'] and
            existing['target_entity_uuid'] == new_relationship['target_entity_uuid'] and
            existing['relationship_type'] == new_relationship['relationship_type']):
            # Update confidence if new one is higher
            if new_relationship['confidence_score'] > existing['confidence_score']:
                existing['confidence_score'] = new_relationship['confidence_score']
                existing['context'] = new_relationship['context']
            return True
    return False

def extract_relationships_from_document(
    chunks: List[Dict[str, Any]],
    canonical_entities: List[Dict[str, Any]],
    document_uuid: str,
    confidence_threshold: float = 0.7
) -> Dict[str, Any]:
    """
    Extract all relationships from a document's chunks
    
    Args:
        chunks: List of document chunks with text
        canonical_entities: List of canonical entities
        document_uuid: UUID of the document
        confidence_threshold: Minimum confidence threshold
        
    Returns:
        Dict with relationships and statistics
    """
    logger.info(f"Extracting relationships from {len(chunks)} chunks with {len(canonical_entities)} canonical entities")
    
    all_relationships = []
    chunks_with_relationships = 0
    
    for chunk in chunks:
        chunk_text = chunk.get('text') or chunk.get('chunk_text') or chunk.get('text_content', '')
        chunk_uuid = chunk.get('chunk_uuid') or chunk.get('chunkId')
        
        if not chunk_text:
            continue
        
        # Extract relationships from this chunk
        chunk_relationships = extract_relationships_from_text(
            text=chunk_text,
            canonical_entities=canonical_entities,
            chunk_uuid=chunk_uuid,
            confidence_threshold=confidence_threshold
        )
        
        if chunk_relationships:
            chunks_with_relationships += 1
            all_relationships.extend(chunk_relationships)
    
    # Deduplicate relationships across chunks
    unique_relationships = []
    seen = set()
    
    for rel in all_relationships:
        # Create unique key
        key = (
            rel['source_entity_uuid'],
            rel['target_entity_uuid'],
            rel['relationship_type']
        )
        
        if key not in seen:
            seen.add(key)
            unique_relationships.append(rel)
        else:
            # Update existing with higher confidence
            for existing in unique_relationships:
                if (existing['source_entity_uuid'] == rel['source_entity_uuid'] and
                    existing['target_entity_uuid'] == rel['target_entity_uuid'] and
                    existing['relationship_type'] == rel['relationship_type']):
                    if rel['confidence_score'] > existing['confidence_score']:
                        existing['confidence_score'] = rel['confidence_score']
                        existing['context'] = rel['context']
    
    # Calculate statistics
    relationship_types = defaultdict(int)
    for rel in unique_relationships:
        relationship_types[rel['relationship_type']] += 1
    
    logger.info(f"Extracted {len(unique_relationships)} unique relationships from {chunks_with_relationships} chunks")
    logger.info(f"Relationship types: {dict(relationship_types)}")
    
    return {
        'relationships': unique_relationships,
        'total_relationships': len(unique_relationships),
        'chunks_with_relationships': chunks_with_relationships,
        'relationship_types': dict(relationship_types),
        'document_uuid': document_uuid,
        'extraction_timestamp': datetime.utcnow()
    }

def save_relationships_to_database(
    relationships: List[Dict[str, Any]],
    document_uuid: str,
    db_manager: Any
) -> int:
    """Save extracted relationships to relationship_staging table"""
    session = next(db_manager.get_session())
    saved_count = 0
    
    try:
        from sqlalchemy import text as sql_text
        
        insert_query = sql_text("""
            INSERT INTO relationship_staging (
                relationship_uuid, source_entity_uuid, target_entity_uuid,
                relationship_type, confidence_score, document_uuid,
                chunk_uuid, context, extraction_metadata, created_at
            ) VALUES (
                :relationship_uuid, :source_entity_uuid, :target_entity_uuid,
                :relationship_type, :confidence_score, :document_uuid,
                :chunk_uuid, :context, CAST(:metadata AS jsonb), :created_at
            )
            ON CONFLICT (relationship_uuid) DO NOTHING
        """)
        
        for rel in relationships:
            try:
                # Prepare metadata
                metadata = {
                    'source_entity_name': rel.get('source_entity_name'),
                    'source_entity_type': rel.get('source_entity_type'),
                    'target_entity_name': rel.get('target_entity_name'),
                    'target_entity_type': rel.get('target_entity_type'),
                    'extraction_method': rel.get('extraction_method', 'pattern_matching')
                }
                
                result = session.execute(insert_query, {
                    'relationship_uuid': str(rel['relationship_uuid']),
                    'source_entity_uuid': str(rel['source_entity_uuid']),
                    'target_entity_uuid': str(rel['target_entity_uuid']),
                    'relationship_type': rel['relationship_type'],
                    'confidence_score': rel['confidence_score'],
                    'document_uuid': str(document_uuid),
                    'chunk_uuid': str(rel.get('chunk_uuid')) if rel.get('chunk_uuid') else None,
                    'context': rel.get('context', ''),
                    'metadata': json.dumps(metadata),
                    'created_at': rel.get('created_at', datetime.utcnow())
                })
                
                if result.rowcount > 0:
                    saved_count += 1
                    
            except Exception as e:
                logger.error(f"Failed to save relationship: {e}")
        
        session.commit()
        logger.info(f"Saved {saved_count}/{len(relationships)} relationships to database")
        
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to save relationships: {e}")
        raise
    finally:
        session.close()
    
    return saved_count

# Export main functions
__all__ = [
    'extract_relationships_from_document',
    'extract_relationships_from_text',
    'save_relationships_to_database'
]