"""
OCR Validation - Validates text extraction quality and completeness.

This validator provides:
- Text extraction success rate validation
- Confidence score distribution analysis
- Extraction anomaly detection
- Scanned vs text PDF comparison
- OCR quality metrics calculation
"""

from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
import re
import statistics
from datetime import datetime
import logging

from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager
from scripts.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class OCRValidationResult:
    """Result of OCR validation for a document."""
    document_uuid: str
    validation_timestamp: str
    text_extracted: bool
    text_length: int
    confidence_score: float
    page_count: int
    method_used: str
    quality_score: float  # 0-100
    anomalies_detected: List[str]
    validation_passed: bool
    recommendations: List[str]


@dataclass
class ConfidenceMetrics:
    """Confidence score distribution metrics."""
    total_documents: int
    average_confidence: float
    median_confidence: float
    min_confidence: float
    max_confidence: float
    low_confidence_count: int  # < 70%
    medium_confidence_count: int  # 70-90%
    high_confidence_count: int  # > 90%
    confidence_distribution: Dict[str, int]


@dataclass
class ComparisonReport:
    """Comparison between scanned and text PDF results."""
    total_scanned_pdfs: int
    total_text_pdfs: int
    scanned_success_rate: float
    text_success_rate: float
    average_confidence_scanned: float
    average_confidence_text: float
    processing_time_comparison: Dict[str, float]
    quality_comparison: Dict[str, float]


@dataclass
class Anomaly:
    """Detected anomaly in text extraction."""
    type: str
    description: str
    severity: str  # low, medium, high, critical
    suggested_action: str
    metadata: Dict[str, Any]


class OCRValidator:
    """Validator for OCR text extraction quality."""
    
    def __init__(self, db_manager: DatabaseManager = None):
        self.db_manager = db_manager or DatabaseManager()
        self.redis = get_redis_manager()
        
        # Quality thresholds
        self.MIN_CONFIDENCE_THRESHOLD = 70.0
        self.MIN_TEXT_LENGTH = 50
        self.MAX_ANOMALY_SCORE = 3
        
    def validate_text_extraction(self, doc_id: str) -> OCRValidationResult:
        """
        Validate text extraction quality for a document.
        
        Args:
            doc_id: Document UUID to validate
            
        Returns:
            OCRValidationResult with comprehensive validation
        """
        logger.info(f"Validating OCR extraction for document {doc_id}")
        
        try:
            # Get OCR results from database
            ocr_data = self._get_ocr_data(doc_id)
            
            if not ocr_data:
                return self._create_failed_validation(doc_id, "No OCR data found")
            
            # Extract validation parameters
            text = ocr_data.get('raw_text', '')
            confidence = ocr_data.get('ocr_confidence_score', 0.0)
            page_count = ocr_data.get('textract_page_count', 0)
            method = ocr_data.get('ocr_method', 'unknown')
            
            # Validate text extraction
            text_extracted = len(text.strip()) > 0
            text_length = len(text)
            
            # Detect anomalies
            anomalies = self.detect_extraction_anomalies(text, {
                'confidence': confidence,
                'page_count': page_count,
                'method': method
            })
            
            # Calculate quality score
            quality_score = self._calculate_quality_score(
                text_length, confidence, len(anomalies), method
            )
            
            # Generate recommendations
            recommendations = self._generate_recommendations(
                text_length, confidence, anomalies, method
            )
            
            # Determine if validation passed
            validation_passed = (
                text_extracted and
                confidence >= self.MIN_CONFIDENCE_THRESHOLD and
                text_length >= self.MIN_TEXT_LENGTH and
                len([a for a in anomalies if a.severity in ['high', 'critical']]) == 0
            )
            
            result = OCRValidationResult(
                document_uuid=doc_id,
                validation_timestamp=datetime.now().isoformat(),
                text_extracted=text_extracted,
                text_length=text_length,
                confidence_score=confidence,
                page_count=page_count,
                method_used=method,
                quality_score=quality_score,
                anomalies_detected=[a.description for a in anomalies],
                validation_passed=validation_passed,
                recommendations=recommendations
            )
            
            # Cache validation result
            self._cache_validation_result(doc_id, result)
            
            return result
            
        except Exception as e:
            logger.error(f"Error validating OCR extraction for {doc_id}: {e}")
            return self._create_failed_validation(doc_id, f"Validation error: {e}")
    
    def measure_confidence_distribution(self, results: List[Dict[str, Any]]) -> ConfidenceMetrics:
        """
        Analyze confidence score distribution across multiple documents.
        
        Args:
            results: List of OCR results with confidence scores
            
        Returns:
            ConfidenceMetrics with distribution analysis
        """
        if not results:
            return ConfidenceMetrics(
                total_documents=0,
                average_confidence=0.0,
                median_confidence=0.0,
                min_confidence=0.0,
                max_confidence=0.0,
                low_confidence_count=0,
                medium_confidence_count=0,
                high_confidence_count=0,
                confidence_distribution={}
            )
        
        # Extract confidence scores
        confidences = []
        for result in results:
            confidence = result.get('ocr_confidence_score', 0.0)
            if confidence > 0:  # Only include valid confidence scores
                confidences.append(confidence)
        
        if not confidences:
            return ConfidenceMetrics(
                total_documents=len(results),
                average_confidence=0.0,
                median_confidence=0.0,
                min_confidence=0.0,
                max_confidence=0.0,
                low_confidence_count=0,
                medium_confidence_count=0,
                high_confidence_count=0,
                confidence_distribution={}
            )
        
        # Calculate statistics
        avg_confidence = statistics.mean(confidences)
        median_confidence = statistics.median(confidences)
        min_confidence = min(confidences)
        max_confidence = max(confidences)
        
        # Count by confidence ranges
        low_confidence = sum(1 for c in confidences if c < 70)
        medium_confidence = sum(1 for c in confidences if 70 <= c < 90)
        high_confidence = sum(1 for c in confidences if c >= 90)
        
        # Create distribution buckets
        distribution = {}
        for confidence in confidences:
            bucket = f"{int(confidence // 10) * 10}-{int(confidence // 10) * 10 + 9}"
            distribution[bucket] = distribution.get(bucket, 0) + 1
        
        return ConfidenceMetrics(
            total_documents=len(results),
            average_confidence=round(avg_confidence, 2),
            median_confidence=round(median_confidence, 2),
            min_confidence=round(min_confidence, 2),
            max_confidence=round(max_confidence, 2),
            low_confidence_count=low_confidence,
            medium_confidence_count=medium_confidence,
            high_confidence_count=high_confidence,
            confidence_distribution=distribution
        )
    
    def detect_extraction_anomalies(self, text: str, metadata: Dict[str, Any]) -> List[Anomaly]:
        """
        Detect anomalies in extracted text.
        
        Args:
            text: Extracted text to analyze
            metadata: Additional metadata about extraction
            
        Returns:
            List of detected anomalies
        """
        anomalies = []
        
        try:
            # Check for empty or very short text
            if len(text.strip()) == 0:
                anomalies.append(Anomaly(
                    type="empty_text",
                    description="No text extracted from document",
                    severity="critical",
                    suggested_action="Check document integrity and OCR method",
                    metadata={"text_length": len(text)}
                ))
            elif len(text.strip()) < self.MIN_TEXT_LENGTH:
                anomalies.append(Anomaly(
                    type="short_text",
                    description=f"Very short text extracted ({len(text)} characters)",
                    severity="high",
                    suggested_action="Verify document contains readable text",
                    metadata={"text_length": len(text)}
                ))
            
            # Check for low confidence scores
            confidence = metadata.get('confidence', 0)
            if confidence < 50:
                anomalies.append(Anomaly(
                    type="low_confidence",
                    description=f"Very low confidence score ({confidence:.1f}%)",
                    severity="high",
                    suggested_action="Consider re-processing with different OCR method",
                    metadata={"confidence": confidence}
                ))
            elif confidence < self.MIN_CONFIDENCE_THRESHOLD:
                anomalies.append(Anomaly(
                    type="medium_confidence",
                    description=f"Below threshold confidence score ({confidence:.1f}%)",
                    severity="medium",
                    suggested_action="Review extracted text for accuracy",
                    metadata={"confidence": confidence}
                ))
            
            # Check for excessive repeated characters (OCR errors)
            repeated_chars = re.findall(r'(.)\1{5,}', text)
            if repeated_chars:
                anomalies.append(Anomaly(
                    type="repeated_characters",
                    description=f"Excessive repeated characters detected: {repeated_chars[:3]}",
                    severity="medium",
                    suggested_action="Check for OCR scanning artifacts",
                    metadata={"repeated_sequences": repeated_chars[:10]}
                ))
            
            # Check for non-printable characters
            non_printable = re.findall(r'[^\x20-\x7E\n\r\t]', text)
            if len(non_printable) > len(text) * 0.05:  # More than 5% non-printable
                anomalies.append(Anomaly(
                    type="non_printable_characters",
                    description=f"High percentage of non-printable characters ({len(non_printable)}/{len(text)})",
                    severity="medium",
                    suggested_action="Check character encoding and OCR quality",
                    metadata={"non_printable_count": len(non_printable)}
                ))
            
            # Check for very long lines (potential OCR parsing issues)
            lines = text.split('\n')
            long_lines = [line for line in lines if len(line) > 500]
            if len(long_lines) > len(lines) * 0.1:  # More than 10% of lines are very long
                anomalies.append(Anomaly(
                    type="long_lines",
                    description=f"Many very long lines detected ({len(long_lines)}/{len(lines)})",
                    severity="low",
                    suggested_action="Check if text formatting is preserved correctly",
                    metadata={"long_line_count": len(long_lines)}
                ))
            
            # Check for unusual character distribution
            alpha_chars = sum(1 for c in text if c.isalpha())
            if alpha_chars < len(text) * 0.3:  # Less than 30% alphabetic characters
                anomalies.append(Anomaly(
                    type="low_alpha_ratio",
                    description=f"Low ratio of alphabetic characters ({alpha_chars}/{len(text)})",
                    severity="medium",
                    suggested_action="Verify document contains readable text content",
                    metadata={"alpha_ratio": alpha_chars / len(text) if len(text) > 0 else 0}
                ))
            
        except Exception as e:
            logger.error(f"Error detecting anomalies: {e}")
            anomalies.append(Anomaly(
                type="analysis_error",
                description=f"Error during anomaly detection: {e}",
                severity="low",
                suggested_action="Review anomaly detection process",
                metadata={"error": str(e)}
            ))
        
        return anomalies
    
    def compare_scanned_vs_text_pdf_results(self, results: List[Dict[str, Any]]) -> ComparisonReport:
        """
        Compare results between scanned and text-based PDFs.
        
        Args:
            results: List of OCR results with method information
            
        Returns:
            ComparisonReport with comparison analysis
        """
        scanned_results = []
        text_results = []
        
        # Separate results by method
        for result in results:
            method = result.get('ocr_method', '')
            if 'scanned' in method.lower() or 'image' in method.lower():
                scanned_results.append(result)
            else:
                text_results.append(result)
        
        # Calculate success rates
        scanned_success = sum(1 for r in scanned_results if r.get('raw_text', '').strip()) / len(scanned_results) if scanned_results else 0
        text_success = sum(1 for r in text_results if r.get('raw_text', '').strip()) / len(text_results) if text_results else 0
        
        # Calculate average confidences
        scanned_confidences = [r.get('ocr_confidence_score', 0) for r in scanned_results if r.get('ocr_confidence_score', 0) > 0]
        text_confidences = [r.get('ocr_confidence_score', 0) for r in text_results if r.get('ocr_confidence_score', 0) > 0]
        
        avg_conf_scanned = statistics.mean(scanned_confidences) if scanned_confidences else 0
        avg_conf_text = statistics.mean(text_confidences) if text_confidences else 0
        
        # Calculate processing times (placeholder - would need actual timing data)
        processing_time_comparison = {
            'scanned_avg_minutes': 5.0,  # Placeholder
            'text_avg_minutes': 2.0,    # Placeholder
            'scanned_vs_text_ratio': 2.5
        }
        
        # Calculate quality comparison
        quality_comparison = {
            'scanned_avg_quality': avg_conf_scanned,
            'text_avg_quality': avg_conf_text,
            'quality_difference': avg_conf_text - avg_conf_scanned
        }
        
        return ComparisonReport(
            total_scanned_pdfs=len(scanned_results),
            total_text_pdfs=len(text_results),
            scanned_success_rate=round(scanned_success * 100, 2),
            text_success_rate=round(text_success * 100, 2),
            average_confidence_scanned=round(avg_conf_scanned, 2),
            average_confidence_text=round(avg_conf_text, 2),
            processing_time_comparison=processing_time_comparison,
            quality_comparison=quality_comparison
        )
    
    # Private helper methods
    
    def _get_ocr_data(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Get OCR data for a document from database."""
        try:
            with self.db_manager.get_session() as session:
                # Query source_documents for OCR results
                query = """
                    SELECT raw_text, ocr_confidence_score, textract_page_count, 
                           ocr_method, extracted_at
                    FROM source_documents 
                    WHERE document_uuid = :doc_id
                """
                result = session.execute(query, {'doc_id': doc_id}).fetchone()
                
                if result:
                    return {
                        'raw_text': result[0] or '',
                        'ocr_confidence_score': result[1] or 0.0,
                        'textract_page_count': result[2] or 0,
                        'ocr_method': result[3] or 'unknown',
                        'extracted_at': result[4]
                    }
                
                return None
                
        except Exception as e:
            logger.error(f"Error getting OCR data for {doc_id}: {e}")
            return None
    
    def _calculate_quality_score(self, text_length: int, confidence: float, 
                               anomaly_count: int, method: str) -> float:
        """Calculate overall quality score (0-100)."""
        base_score = 100.0
        
        # Deduct for short text
        if text_length < self.MIN_TEXT_LENGTH:
            base_score -= 30
        elif text_length < 200:
            base_score -= 15
        
        # Deduct for low confidence
        if confidence < 50:
            base_score -= 40
        elif confidence < self.MIN_CONFIDENCE_THRESHOLD:
            base_score -= 20
        elif confidence < 90:
            base_score -= 10
        
        # Deduct for anomalies
        base_score -= anomaly_count * 10
        
        # Adjust for method (scanned PDFs typically have lower base quality)
        if 'scanned' in method.lower():
            base_score -= 5
        
        return max(0.0, min(100.0, base_score))
    
    def _generate_recommendations(self, text_length: int, confidence: float, 
                                anomalies: List[Anomaly], method: str) -> List[str]:
        """Generate recommendations for improving OCR quality."""
        recommendations = []
        
        if text_length < self.MIN_TEXT_LENGTH:
            recommendations.append("Document appears to contain minimal text - verify content")
        
        if confidence < self.MIN_CONFIDENCE_THRESHOLD:
            recommendations.append("Low confidence score - consider alternative OCR method")
        
        if any(a.severity in ['high', 'critical'] for a in anomalies):
            recommendations.append("Critical anomalies detected - manual review recommended")
        
        if 'scanned' in method.lower() and confidence < 80:
            recommendations.append("Scanned PDF with low quality - consider image enhancement")
        
        if len(anomalies) > self.MAX_ANOMALY_SCORE:
            recommendations.append("Multiple anomalies detected - review extraction process")
        
        if not recommendations:
            recommendations.append("OCR extraction appears successful")
        
        return recommendations
    
    def _create_failed_validation(self, doc_id: str, reason: str) -> OCRValidationResult:
        """Create a failed validation result."""
        return OCRValidationResult(
            document_uuid=doc_id,
            validation_timestamp=datetime.now().isoformat(),
            text_extracted=False,
            text_length=0,
            confidence_score=0.0,
            page_count=0,
            method_used="unknown",
            quality_score=0.0,
            anomalies_detected=[reason],
            validation_passed=False,
            recommendations=[f"Failed validation: {reason}"]
        )
    
    def _cache_validation_result(self, doc_id: str, result: OCRValidationResult) -> None:
        """Cache validation result in Redis."""
        if self.redis.is_available():
            try:
                key = f"ocr:validation:{doc_id}"
                self.redis.set_cached(key, asdict(result), ttl=3600)  # 1 hour
            except Exception as e:
                logger.error(f"Error caching validation result: {e}")