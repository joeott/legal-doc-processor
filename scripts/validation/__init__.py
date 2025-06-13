"""
Pipeline Validation Framework - Comprehensive validation for document processing pipeline.

This package provides validation for:
- OCR text extraction quality and completeness
- Entity extraction accuracy and coverage
- Entity resolution effectiveness
- End-to-end pipeline integration
- Performance and quality metrics
"""

from .ocr_validator import OCRValidator
from .entity_validator import EntityValidator
from .pipeline_validator import PipelineValidator

__all__ = ['OCRValidator', 'EntityValidator', 'PipelineValidator']