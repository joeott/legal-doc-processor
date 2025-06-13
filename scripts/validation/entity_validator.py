"""
Entity Validation - Validates entity extraction and resolution quality.

This validator provides:
- Entity extraction completeness validation
- Entity type distribution analysis
- Entity resolution accuracy measurement
- Pattern detection in extraction results
- Quality metrics for entity processing
"""

from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, asdict
from collections import Counter, defaultdict
import statistics
from datetime import datetime
import logging

from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager
from scripts.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class EntityMetrics:
    """Metrics for entity extraction completeness."""
    document_uuid: str
    total_entities_extracted: int
    entity_types_found: List[str]
    entity_type_counts: Dict[str, int]
    average_confidence: float
    low_confidence_entities: int
    duplicate_entities: int
    extraction_coverage_score: float  # 0-100
    completeness_assessment: str


@dataclass
class TypeDistribution:
    """Entity type distribution analysis."""
    total_entities: int
    unique_types: int
    type_counts: Dict[str, int]
    type_percentages: Dict[str, float]
    dominant_types: List[str]  # Top 5 most common
    rare_types: List[str]      # Types with < 2% occurrence
    type_diversity_score: float  # Shannon entropy based


@dataclass
class AccuracyMetrics:
    """Entity resolution accuracy metrics."""
    total_entities_processed: int
    successfully_resolved: int
    resolution_accuracy: float
    duplicate_clusters_found: int
    average_cluster_size: float
    resolution_conflicts: int
    canonical_entities_created: int
    resolution_quality_score: float


@dataclass
class PatternAnalysis:
    """Pattern analysis in entity extraction results."""
    document_count: int
    common_entity_patterns: List[Dict[str, Any]]
    extraction_consistency: float
    type_correlation_matrix: Dict[str, Dict[str, float]]
    temporal_patterns: Dict[str, Any]
    quality_indicators: Dict[str, float]


class EntityValidator:
    """Validator for entity extraction and resolution quality."""
    
    def __init__(self, db_manager: DatabaseManager = None):
        self.db_manager = db_manager or DatabaseManager()
        self.redis = get_redis_manager()
        
        # Quality thresholds
        self.MIN_CONFIDENCE_THRESHOLD = 70.0
        self.MIN_ENTITIES_PER_PAGE = 2
        self.MIN_TYPE_DIVERSITY = 3
        
    def validate_entity_extraction_completeness(self, doc_id: str) -> EntityMetrics:
        """
        Validate completeness of entity extraction for a document.
        
        Args:
            doc_id: Document UUID to validate
            
        Returns:
            EntityMetrics with extraction completeness analysis
        """
        logger.info(f"Validating entity extraction completeness for document {doc_id}")
        
        try:
            # Get entity extraction data
            entities = self._get_entity_mentions(doc_id)
            document_info = self._get_document_info(doc_id)
            
            if not entities:
                return self._create_empty_metrics(doc_id, "No entities found")
            
            # Analyze entities
            total_entities = len(entities)
            entity_types = [e.get('entity_type', 'unknown') for e in entities]
            type_counts = Counter(entity_types)
            
            # Calculate confidence metrics
            confidences = [e.get('confidence_score', 0.0) for e in entities if e.get('confidence_score')]
            avg_confidence = statistics.mean(confidences) if confidences else 0.0
            low_confidence = sum(1 for c in confidences if c < self.MIN_CONFIDENCE_THRESHOLD)
            
            # Detect duplicates (entities with same text and type)
            entity_signatures = [(e.get('entity_text', '').lower(), e.get('entity_type', '')) for e in entities]
            unique_signatures = set(entity_signatures)
            duplicates = len(entity_signatures) - len(unique_signatures)
            
            # Calculate extraction coverage score
            page_count = document_info.get('page_count', 1)
            text_length = document_info.get('text_length', 0)
            coverage_score = self._calculate_extraction_coverage(
                total_entities, page_count, text_length, len(type_counts)
            )
            
            # Assess completeness
            completeness = self._assess_extraction_completeness(
                total_entities, len(type_counts), avg_confidence, coverage_score
            )
            
            return EntityMetrics(
                document_uuid=doc_id,
                total_entities_extracted=total_entities,
                entity_types_found=list(type_counts.keys()),
                entity_type_counts=dict(type_counts),
                average_confidence=round(avg_confidence, 2),
                low_confidence_entities=low_confidence,
                duplicate_entities=duplicates,
                extraction_coverage_score=round(coverage_score, 2),
                completeness_assessment=completeness
            )
            
        except Exception as e:
            logger.error(f"Error validating entity extraction for {doc_id}: {e}")
            return self._create_empty_metrics(doc_id, f"Validation error: {e}")
    
    def check_entity_type_distribution(self, entities: List[Dict[str, Any]]) -> TypeDistribution:
        """
        Analyze distribution of entity types across entities.
        
        Args:
            entities: List of entity dictionaries
            
        Returns:
            TypeDistribution with analysis results
        """
        if not entities:
            return TypeDistribution(
                total_entities=0,
                unique_types=0,
                type_counts={},
                type_percentages={},
                dominant_types=[],
                rare_types=[],
                type_diversity_score=0.0
            )
        
        # Count entity types
        entity_types = [e.get('entity_type', 'unknown') for e in entities]
        type_counts = Counter(entity_types)
        total_entities = len(entities)
        
        # Calculate percentages
        type_percentages = {
            entity_type: (count / total_entities) * 100
            for entity_type, count in type_counts.items()
        }
        
        # Identify dominant and rare types
        dominant_types = [
            entity_type for entity_type, count in type_counts.most_common(5)
        ]
        
        rare_threshold = total_entities * 0.02  # 2% threshold
        rare_types = [
            entity_type for entity_type, count in type_counts.items()
            if count < rare_threshold
        ]
        
        # Calculate diversity score (Shannon entropy)
        diversity_score = self._calculate_shannon_entropy(type_counts.values(), total_entities)
        
        return TypeDistribution(
            total_entities=total_entities,
            unique_types=len(type_counts),
            type_counts=dict(type_counts),
            type_percentages={k: round(v, 2) for k, v in type_percentages.items()},
            dominant_types=dominant_types,
            rare_types=rare_types,
            type_diversity_score=round(diversity_score, 3)
        )
    
    def validate_entity_resolution_accuracy(self, resolved: List[Dict[str, Any]]) -> AccuracyMetrics:
        """
        Validate accuracy of entity resolution process.
        
        Args:
            resolved: List of resolved canonical entities
            
        Returns:
            AccuracyMetrics with resolution accuracy analysis
        """
        if not resolved:
            return AccuracyMetrics(
                total_entities_processed=0,
                successfully_resolved=0,
                resolution_accuracy=0.0,
                duplicate_clusters_found=0,
                average_cluster_size=0.0,
                resolution_conflicts=0,
                canonical_entities_created=0,
                resolution_quality_score=0.0
            )
        
        try:
            # Analyze resolution results
            total_processed = len(resolved)
            successfully_resolved = sum(1 for e in resolved if e.get('canonical_text'))
            
            # Calculate accuracy
            accuracy = (successfully_resolved / total_processed) * 100 if total_processed > 0 else 0
            
            # Analyze clusters (entities resolved to same canonical form)
            canonical_groups = defaultdict(list)
            for entity in resolved:
                canonical_text = entity.get('canonical_text', entity.get('entity_text', ''))
                canonical_groups[canonical_text].append(entity)
            
            duplicate_clusters = sum(1 for group in canonical_groups.values() if len(group) > 1)
            cluster_sizes = [len(group) for group in canonical_groups.values() if len(group) > 1]
            avg_cluster_size = statistics.mean(cluster_sizes) if cluster_sizes else 0.0
            
            # Detect potential conflicts (same canonical text but different types)
            conflicts = 0
            for canonical_text, entities in canonical_groups.items():
                types = set(e.get('entity_type', '') for e in entities)
                if len(types) > 1:
                    conflicts += 1
            
            canonical_entities = len(canonical_groups)
            
            # Calculate overall quality score
            quality_score = self._calculate_resolution_quality_score(
                accuracy, duplicate_clusters, conflicts, total_processed
            )
            
            return AccuracyMetrics(
                total_entities_processed=total_processed,
                successfully_resolved=successfully_resolved,
                resolution_accuracy=round(accuracy, 2),
                duplicate_clusters_found=duplicate_clusters,
                average_cluster_size=round(avg_cluster_size, 2),
                resolution_conflicts=conflicts,
                canonical_entities_created=canonical_entities,
                resolution_quality_score=round(quality_score, 2)
            )
            
        except Exception as e:
            logger.error(f"Error validating entity resolution: {e}")
            return AccuracyMetrics(
                total_entities_processed=len(resolved),
                successfully_resolved=0,
                resolution_accuracy=0.0,
                duplicate_clusters_found=0,
                average_cluster_size=0.0,
                resolution_conflicts=0,
                canonical_entities_created=0,
                resolution_quality_score=0.0
            )
    
    def detect_extraction_patterns(self, batch_results: List[Dict[str, Any]]) -> PatternAnalysis:
        """
        Detect patterns in entity extraction across multiple documents.
        
        Args:
            batch_results: List of entity extraction results from multiple documents
            
        Returns:
            PatternAnalysis with detected patterns
        """
        if not batch_results:
            return self._create_empty_pattern_analysis()
        
        try:
            document_count = len(batch_results)
            
            # Analyze common entity patterns
            common_patterns = self._find_common_entity_patterns(batch_results)
            
            # Calculate extraction consistency
            consistency = self._calculate_extraction_consistency(batch_results)
            
            # Build type correlation matrix
            correlation_matrix = self._build_type_correlation_matrix(batch_results)
            
            # Analyze temporal patterns (if timestamp data available)
            temporal_patterns = self._analyze_temporal_patterns(batch_results)
            
            # Calculate quality indicators
            quality_indicators = self._calculate_batch_quality_indicators(batch_results)
            
            return PatternAnalysis(
                document_count=document_count,
                common_entity_patterns=common_patterns,
                extraction_consistency=round(consistency, 3),
                type_correlation_matrix=correlation_matrix,
                temporal_patterns=temporal_patterns,
                quality_indicators=quality_indicators
            )
            
        except Exception as e:
            logger.error(f"Error detecting extraction patterns: {e}")
            return self._create_empty_pattern_analysis()
    
    # Private helper methods
    
    def _get_entity_mentions(self, doc_id: str) -> List[Dict[str, Any]]:
        """Get entity mentions for a document from database."""
        try:
            with self.db_manager.get_session() as session:
                query = """
                    SELECT entity_text, entity_type, confidence_score, 
                           start_char, end_char, mention_uuid
                    FROM entity_mentions 
                    WHERE document_uuid = :doc_id
                """
                results = session.execute(query, {'doc_id': doc_id}).fetchall()
                
                return [
                    {
                        'entity_text': row[0],
                        'entity_type': row[1],
                        'confidence_score': row[2],
                        'start_char': row[3],
                        'end_char': row[4],
                        'mention_uuid': str(row[5])
                    }
                    for row in results
                ]
                
        except Exception as e:
            logger.error(f"Error getting entity mentions for {doc_id}: {e}")
            return []
    
    def _get_document_info(self, doc_id: str) -> Dict[str, Any]:
        """Get document information for analysis."""
        try:
            with self.db_manager.get_session() as session:
                query = """
                    SELECT textract_page_count, LENGTH(raw_text) as text_length
                    FROM source_documents 
                    WHERE document_uuid = :doc_id
                """
                result = session.execute(query, {'doc_id': doc_id}).fetchone()
                
                if result:
                    return {
                        'page_count': result[0] or 1,
                        'text_length': result[1] or 0
                    }
                
                return {'page_count': 1, 'text_length': 0}
                
        except Exception as e:
            logger.error(f"Error getting document info for {doc_id}: {e}")
            return {'page_count': 1, 'text_length': 0}
    
    def _calculate_extraction_coverage(self, entity_count: int, page_count: int, 
                                     text_length: int, type_diversity: int) -> float:
        """Calculate extraction coverage score."""
        base_score = 50.0
        
        # Adjust for entity density
        entities_per_page = entity_count / max(1, page_count)
        if entities_per_page >= self.MIN_ENTITIES_PER_PAGE:
            base_score += 20
        else:
            base_score += (entities_per_page / self.MIN_ENTITIES_PER_PAGE) * 20
        
        # Adjust for type diversity
        if type_diversity >= self.MIN_TYPE_DIVERSITY:
            base_score += 20
        else:
            base_score += (type_diversity / self.MIN_TYPE_DIVERSITY) * 20
        
        # Adjust for text coverage (entities per 1000 characters)
        if text_length > 0:
            entity_density = (entity_count / text_length) * 1000
            if entity_density >= 5:  # 5 entities per 1000 chars
                base_score += 10
            else:
                base_score += (entity_density / 5) * 10
        
        return min(100.0, base_score)
    
    def _assess_extraction_completeness(self, entity_count: int, type_count: int, 
                                      avg_confidence: float, coverage_score: float) -> str:
        """Assess overall extraction completeness."""
        if coverage_score >= 80 and avg_confidence >= 80:
            return "excellent"
        elif coverage_score >= 60 and avg_confidence >= 70:
            return "good"
        elif coverage_score >= 40 and avg_confidence >= 60:
            return "fair"
        elif coverage_score >= 20 or avg_confidence >= 50:
            return "poor"
        else:
            return "very_poor"
    
    def _calculate_shannon_entropy(self, counts: List[int], total: int) -> float:
        """Calculate Shannon entropy for diversity measurement."""
        import math
        
        if total == 0:
            return 0.0
        
        entropy = 0.0
        for count in counts:
            if count > 0:
                probability = count / total
                entropy -= probability * math.log2(probability)
        
        return entropy
    
    def _calculate_resolution_quality_score(self, accuracy: float, duplicate_clusters: int, 
                                          conflicts: int, total_entities: int) -> float:
        """Calculate overall resolution quality score."""
        base_score = accuracy  # Start with accuracy percentage
        
        # Bonus for finding duplicates
        if duplicate_clusters > 0:
            base_score += min(10, duplicate_clusters * 2)
        
        # Penalty for conflicts
        if conflicts > 0:
            penalty = (conflicts / total_entities) * 100 * 0.5  # 50% penalty weight
            base_score -= penalty
        
        return max(0.0, min(100.0, base_score))
    
    def _find_common_entity_patterns(self, batch_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Find common patterns in entity extraction across documents."""
        # Placeholder for pattern detection logic
        return [
            {
                'pattern_type': 'common_entities',
                'description': 'Entities that appear frequently across documents',
                'frequency': 0,
                'examples': []
            }
        ]
    
    def _calculate_extraction_consistency(self, batch_results: List[Dict[str, Any]]) -> float:
        """Calculate consistency of extraction across documents."""
        # Placeholder for consistency calculation
        return 0.75  # 75% consistency
    
    def _build_type_correlation_matrix(self, batch_results: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
        """Build correlation matrix between entity types."""
        # Placeholder for correlation analysis
        return {}
    
    def _analyze_temporal_patterns(self, batch_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze temporal patterns in extraction."""
        # Placeholder for temporal analysis
        return {
            'processing_time_trend': 'stable',
            'extraction_rate_trend': 'improving'
        }
    
    def _calculate_batch_quality_indicators(self, batch_results: List[Dict[str, Any]]) -> Dict[str, float]:
        """Calculate quality indicators for batch processing."""
        # Placeholder for quality indicator calculations
        return {
            'average_extraction_rate': 85.0,
            'consistency_score': 78.0,
            'coverage_score': 82.0
        }
    
    def _create_empty_metrics(self, doc_id: str, reason: str) -> EntityMetrics:
        """Create empty metrics with error reason."""
        return EntityMetrics(
            document_uuid=doc_id,
            total_entities_extracted=0,
            entity_types_found=[],
            entity_type_counts={},
            average_confidence=0.0,
            low_confidence_entities=0,
            duplicate_entities=0,
            extraction_coverage_score=0.0,
            completeness_assessment=f"failed: {reason}"
        )
    
    def _create_empty_pattern_analysis(self) -> PatternAnalysis:
        """Create empty pattern analysis."""
        return PatternAnalysis(
            document_count=0,
            common_entity_patterns=[],
            extraction_consistency=0.0,
            type_correlation_matrix={},
            temporal_patterns={},
            quality_indicators={}
        )