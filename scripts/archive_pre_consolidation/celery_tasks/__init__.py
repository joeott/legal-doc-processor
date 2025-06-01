"""
Celery Tasks Package for NLP Document Processing Pipeline

This package contains all Celery task definitions organized by processing stage:
- ocr_tasks: Document OCR and text extraction
- text_tasks: Text processing, cleaning, and chunking
- entity_tasks: Named entity recognition and resolution
- graph_tasks: Relationship building and graph staging
"""

from scripts.celery_app import app

__all__ = ['app']