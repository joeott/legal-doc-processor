#!/usr/bin/env python3
"""Clear failed OCR states to allow retry."""

from scripts.cache import get_redis_manager
import json

def clear_failed_ocr_states():
    """Reset failed OCR states in Redis to allow retry."""
    redis_manager = get_redis_manager()
    failed_docs = []
    reset_docs = []

    # Find all documents with failed OCR
    client = redis_manager.get_client()
    for key in client.scan_iter("doc:state:*"):
        key_str = key.decode() if isinstance(key, bytes) else key
        state = redis_manager.get_dict(key_str)
        
        if state and state.get('ocr', {}).get('status') == 'failed':
            doc_uuid = key_str.split(':')[-1]
            failed_docs.append(doc_uuid)
            
            # Reset to allow retry
            state['ocr']['status'] = 'pending'
            if 'last_update' in state:
                state['last_update']['status'] = 'pending'
            
            redis_manager.store_dict(key_str, state)
            reset_docs.append(doc_uuid)
            print(f"Reset OCR state for document: {doc_uuid}")

    print(f"\nFound {len(failed_docs)} failed documents")
    print(f"Reset {len(reset_docs)} documents to pending state")
    
    return reset_docs

if __name__ == "__main__":
    clear_failed_ocr_states()