#!/usr/bin/env python3
"""Clear cache for a specific document"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from scripts.cache import get_cache_manager

doc_uuid = '0697af52-8bc6-4299-90ec-5d67b7eeb858'
cache_mgr = get_cache_manager()

# Clear all cache for this document
cleared = cache_mgr.clear_document_cache(doc_uuid)
print(f"Cleared {cleared} cache entries for document {doc_uuid}")