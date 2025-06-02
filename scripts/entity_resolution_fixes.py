"""
Entity resolution fixes to properly deduplicate entities and save to database
"""
import os
import uuid
import logging
from typing import List, Dict, Any, Optional
from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

def create_canonical_entity_for_minimal_model(
    entity_name: str,
    entity_type: str,
    mention_uuids: List[uuid.UUID],
    aliases: List[str],
    confidence: float = 0.9
) -> Dict[str, Any]:
    """
    Create a canonical entity dictionary compatible with minimal models
    """
    return {
        'canonical_entity_uuid': uuid.uuid4(),
        'canonical_name': entity_name,  # Changed from entity_name to canonical_name
        'entity_type': entity_type,
        'aliases': aliases,  # Store as JSON
        'mention_count': len(mention_uuids),
        'confidence_score': confidence,
        'resolution_method': 'fuzzy' if confidence < 0.9 else 'llm',
        'created_at': datetime.utcnow(),
        'metadata': {
            'mention_uuids': [str(u) for u in mention_uuids],
            'aliases': aliases,
            'resolution_method': 'fuzzy' if confidence < 0.9 else 'llm'
        }
    }

def resolve_entities_simple(
    entity_mentions: List[Any],
    document_uuid: str,
    threshold: float = 0.8
) -> Dict[str, Any]:
    """
    Simple entity resolution using fuzzy matching
    Returns both canonical entities and updated mentions
    """
    logger.info(f"Resolving {len(entity_mentions)} entity mentions for document {document_uuid}")
    
    # Group mentions by type
    mentions_by_type = defaultdict(list)
    for mention in entity_mentions:
        entity_type = mention.entity_type if hasattr(mention, 'entity_type') else mention.get('entity_type')
        mentions_by_type[entity_type].append(mention)
    
    canonical_entities = []
    mention_to_canonical = {}  # Map mention UUID to canonical UUID
    
    # Process each entity type
    for entity_type, mentions in mentions_by_type.items():
        logger.info(f"Processing {len(mentions)} {entity_type} entities")
        
        # Group similar mentions
        groups = []
        processed = set()
        
        for i, mention1 in enumerate(mentions):
            if i in processed:
                continue
                
            # Get mention text and UUID
            text1 = mention1.entity_text if hasattr(mention1, 'entity_text') else mention1.get('entity_text')
            uuid1 = mention1.mention_uuid if hasattr(mention1, 'mention_uuid') else mention1.get('mention_uuid')
            
            group = [(mention1, text1, uuid1)]
            processed.add(i)
            
            # Find similar mentions
            for j, mention2 in enumerate(mentions[i+1:], i+1):
                if j in processed:
                    continue
                    
                text2 = mention2.entity_text if hasattr(mention2, 'entity_text') else mention2.get('entity_text')
                uuid2 = mention2.mention_uuid if hasattr(mention2, 'mention_uuid') else mention2.get('mention_uuid')
                
                # Calculate similarity
                similarity = SequenceMatcher(None, text1.lower(), text2.lower()).ratio()
                
                # Also check for common variations
                if (similarity >= threshold or 
                    is_entity_variation(text1, text2, entity_type)):
                    group.append((mention2, text2, uuid2))
                    processed.add(j)
            
            groups.append(group)
        
        # Create canonical entities for each group
        for group in groups:
            # Choose the longest mention as canonical name
            canonical_name = max(group, key=lambda x: len(x[1]))[1]
            
            # Collect all variations and UUIDs
            aliases = list(set(item[1] for item in group))
            mention_uuids = [item[2] for item in group]
            
            # Ensure UUIDs are proper UUID objects
            mention_uuids = [
                uuid.UUID(str(u)) if not isinstance(u, uuid.UUID) else u 
                for u in mention_uuids
            ]
            
            # Create canonical entity
            canonical_entity = create_canonical_entity_for_minimal_model(
                entity_name=canonical_name,
                entity_type=entity_type,
                mention_uuids=mention_uuids,
                aliases=aliases,
                confidence=0.8 if len(group) > 1 else 1.0
            )
            
            canonical_entities.append(canonical_entity)
            
            # Map mentions to canonical entity
            canonical_uuid = canonical_entity['canonical_entity_uuid']
            for _, _, mention_uuid in group:
                mention_to_canonical[str(mention_uuid)] = canonical_uuid
    
    logger.info(f"Created {len(canonical_entities)} canonical entities from {len(entity_mentions)} mentions")
    
    return {
        'canonical_entities': canonical_entities,
        'mention_to_canonical': mention_to_canonical,
        'total_mentions': len(entity_mentions),
        'total_canonical': len(canonical_entities),
        'deduplication_rate': 1 - (len(canonical_entities) / len(entity_mentions)) if entity_mentions else 0
    }

def is_entity_variation(text1: str, text2: str, entity_type: str) -> bool:
    """
    Check if two entity texts are variations of each other
    """
    t1_lower = text1.lower().strip()
    t2_lower = text2.lower().strip()
    
    # Exact match
    if t1_lower == t2_lower:
        return True
    
    # One is substring of the other (for abbreviations)
    if t1_lower in t2_lower or t2_lower in t1_lower:
        return True
    
    # Entity-type specific rules
    if entity_type == 'PERSON':
        # Check for initials
        if is_person_variation(text1, text2):
            return True
            
    elif entity_type == 'ORG':
        # Check for common org variations
        if is_org_variation(text1, text2):
            return True
            
    elif entity_type == 'DATE':
        # Dates with same numbers are likely the same
        nums1 = ''.join(c for c in text1 if c.isdigit())
        nums2 = ''.join(c for c in text2 if c.isdigit())
        if nums1 and nums1 == nums2:
            return True
    
    return False

def is_person_variation(name1: str, name2: str) -> bool:
    """Check if two person names are variations"""
    # Split into parts
    parts1 = name1.lower().replace(',', '').split()
    parts2 = name2.lower().replace(',', '').split()
    
    # Check if last names match
    if parts1 and parts2:
        # Handle "Last, First" format
        last1 = parts1[0] if ',' in name1 else parts1[-1] if parts1 else ''
        last2 = parts2[0] if ',' in name2 else parts2[-1] if parts2 else ''
        
        if last1 == last2:
            # Check if first names match or are initials
            first1 = parts1[-1] if ',' in name1 else parts1[0] if parts1 else ''
            first2 = parts2[-1] if ',' in name2 else parts2[0] if parts2 else ''
            
            # One is initial of the other
            if (first1 and first2 and 
                (first1[0] == first2[0] or first1 == first2)):
                return True
    
    return False

def is_org_variation(org1: str, org2: str) -> bool:
    """Check if two organization names are variations"""
    # Common abbreviations
    abbrevs = {
        'corporation': 'corp',
        'incorporated': 'inc',
        'limited': 'ltd',
        'company': 'co',
        'international': 'intl',
        'association': 'assoc',
    }
    
    # Normalize
    norm1 = org1.lower()
    norm2 = org2.lower()
    
    # Remove common suffixes and punctuation
    for full, abbrev in abbrevs.items():
        norm1 = norm1.replace(full, abbrev).replace(f'{abbrev}.', abbrev)
        norm2 = norm2.replace(full, abbrev).replace(f'{abbrev}.', abbrev)
    
    # Remove punctuation
    import string
    norm1 = ''.join(c for c in norm1 if c not in string.punctuation)
    norm2 = ''.join(c for c in norm2 if c not in string.punctuation)
    
    # Check if normalized forms match
    if norm1 == norm2:
        return True
    
    # Check if one is abbreviation of the other
    words1 = norm1.split()
    words2 = norm2.split()
    
    # Get initials
    if len(words1) > 1 and len(words2) == 1:
        initials = ''.join(w[0] for w in words1 if w)
        if initials == words2[0]:
            return True
    elif len(words2) > 1 and len(words1) == 1:
        initials = ''.join(w[0] for w in words2 if w)
        if initials == words1[0]:
            return True
    
    return False

def save_canonical_entities_to_db(
    canonical_entities: List[Dict[str, Any]], 
    document_uuid: str,
    db_manager: Any
) -> int:
    """Save canonical entities to database"""
    session = next(db_manager.get_session())
    
    saved_count = 0
    try:
        for entity in canonical_entities:
            try:
                # Use SQLAlchemy to insert with proper JSON handling
                from sqlalchemy import text as sql_text
                insert_query = sql_text("""
                    INSERT INTO canonical_entities (
                        canonical_entity_uuid, canonical_name, entity_type,
                        mention_count, confidence_score, resolution_method,
                        aliases, metadata, created_at
                    ) VALUES (
                        :canonical_entity_uuid, :canonical_name, :entity_type,
                        :mention_count, :confidence_score, :resolution_method,
                        CAST(:aliases AS jsonb), CAST(:metadata AS jsonb), :created_at
                    )
                    ON CONFLICT (canonical_entity_uuid) DO NOTHING
                """)
                
                # Convert aliases list to JSON
                import json
                
                result = session.execute(insert_query, {
                    'canonical_entity_uuid': str(entity['canonical_entity_uuid']),
                    'canonical_name': entity['canonical_name'],
                    'entity_type': entity['entity_type'],
                    'mention_count': entity.get('mention_count', 1),
                    'confidence_score': entity.get('confidence_score', 1.0),
                    'resolution_method': entity.get('resolution_method', 'fuzzy'),
                    'aliases': json.dumps(entity.get('aliases', [])),
                    'metadata': json.dumps(entity.get('metadata', {})),
                    'created_at': entity.get('created_at', datetime.utcnow())
                })
                
                if result.rowcount > 0:
                    saved_count += 1
                    logger.debug(f"Saved canonical entity: {entity['canonical_name']}")
                    
            except Exception as e:
                logger.error(f"Failed to save canonical entity {entity['canonical_name']}: {e}")
        
        session.commit()
        logger.info(f"Saved {saved_count}/{len(canonical_entities)} canonical entities to database")
        
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to save canonical entities: {e}")
        raise
    finally:
        session.close()
    
    return saved_count

def update_entity_mentions_with_canonical(
    mention_to_canonical: Dict[str, uuid.UUID],
    document_uuid: str,
    db_manager: Any
) -> int:
    """Update entity mentions with their canonical entity UUIDs"""
    from sqlalchemy import text as sql_text
    
    updated_count = 0
    session = next(db_manager.get_session())
    
    try:
        for mention_uuid_str, canonical_uuid in mention_to_canonical.items():
            try:
                update_query = sql_text("""
                    UPDATE entity_mentions 
                    SET canonical_entity_uuid = :canonical_uuid
                    WHERE mention_uuid = :mention_uuid
                    AND document_uuid = :document_uuid
                """)
                
                result = session.execute(update_query, {
                    'canonical_uuid': str(canonical_uuid),
                    'mention_uuid': str(mention_uuid_str),
                    'document_uuid': str(document_uuid)
                })
                
                if result.rowcount > 0:
                    updated_count += result.rowcount
                    
            except Exception as e:
                logger.error(f"Failed to update mention {mention_uuid_str}: {e}")
        
        session.commit()
        logger.info(f"Updated {updated_count} entity mentions with canonical UUIDs")
        
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to update entity mentions: {e}")
        raise
    finally:
        session.close()
    
    return updated_count

# Export the main resolution function
__all__ = ['resolve_entities_simple', 'save_canonical_entities_to_db', 'update_entity_mentions_with_canonical']