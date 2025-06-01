"""
Advanced validation and error recovery for conformance engine.
"""
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import inspect, text
from pydantic import BaseModel, ValidationError

from scripts.db import engine
from scripts.core.conformance_engine import ConformanceEngine, ConformanceReport

logger = logging.getLogger(__name__)


@dataclass
class ValidationMetrics:
    """Metrics for validation performance tracking."""
    validation_time: float
    tables_checked: int
    fields_validated: int
    errors_found: int
    auto_fixable: int
    manual_required: int


class ConformanceValidator:
    """Advanced validator with error recovery and performance tracking."""
    
    def __init__(self):
        self.engine = ConformanceEngine()
        self.metrics = []
        
    def validate_with_recovery(
        self, 
        auto_fix: bool = False,
        max_retries: int = 3
    ) -> Tuple[bool, ConformanceReport, List[str]]:
        """
        Validate conformance with automatic error recovery.
        
        Args:
            auto_fix: Whether to attempt automatic fixes
            max_retries: Maximum retry attempts
            
        Returns:
            Tuple of (success, final_report, recovery_actions)
        """
        start_time = datetime.utcnow()
        recovery_actions = []
        
        for attempt in range(max_retries + 1):
            try:
                report = self.engine.check_conformance()
                
                if report.is_conformant:
                    validation_time = (datetime.utcnow() - start_time).total_seconds()
                    self._record_metrics(validation_time, report, 0)
                    return True, report, recovery_actions
                
                if not auto_fix or attempt == max_retries:
                    validation_time = (datetime.utcnow() - start_time).total_seconds()
                    self._record_metrics(validation_time, report, len(report.issues))
                    return False, report, recovery_actions
                
                # Attempt automatic fix
                fix_success, fix_message = self.engine.enforce_conformance(
                    dry_run=False, 
                    backup=True
                )
                
                if fix_success:
                    recovery_actions.append(f"Attempt {attempt + 1}: {fix_message}")
                else:
                    recovery_actions.append(f"Attempt {attempt + 1} failed: {fix_message}")
                    if "Manual intervention required" in fix_message:
                        break  # No point in retrying
                
            except Exception as e:
                recovery_actions.append(f"Attempt {attempt + 1} error: {str(e)}")
                logger.error(f"Validation attempt {attempt + 1} failed: {e}")
        
        # Final validation attempt
        final_report = self.engine.check_conformance()
        validation_time = (datetime.utcnow() - start_time).total_seconds()
        self._record_metrics(validation_time, final_report, len(final_report.issues))
        
        return final_report.is_conformant, final_report, recovery_actions
    
    def validate_critical_tables(self, critical_tables: List[str]) -> Dict[str, bool]:
        """
        Validate only critical tables for fast startup checks.
        
        Args:
            critical_tables: List of table names that must be conformant
            
        Returns:
            Dict mapping table names to conformance status
        """
        results = {}
        
        for table_name in critical_tables:
            try:
                # Find model for this table
                model_class = None
                for model, table in self.engine.MODEL_TABLE_MAP.items():
                    if table == table_name:
                        model_class = model
                        break
                
                if not model_class:
                    results[table_name] = False
                    continue
                
                # Check just this table
                issues = self.engine._check_table_conformance(model_class, table_name)
                results[table_name] = len(issues) == 0
                
            except Exception as e:
                logger.error(f"Error validating critical table {table_name}: {e}")
                results[table_name] = False
        
        return results
    
    def get_validation_summary(self) -> Dict[str, Any]:
        """Get summary of validation performance over time."""
        if not self.metrics:
            return {"message": "No validation metrics available"}
        
        recent_metrics = self.metrics[-10:]  # Last 10 validations
        
        return {
            "total_validations": len(self.metrics),
            "avg_validation_time": sum(m.validation_time for m in recent_metrics) / len(recent_metrics),
            "avg_errors_found": sum(m.errors_found for m in recent_metrics) / len(recent_metrics),
            "success_rate": sum(1 for m in recent_metrics if m.errors_found == 0) / len(recent_metrics),
            "last_validation": recent_metrics[-1] if recent_metrics else None
        }
    
    def _record_metrics(
        self, 
        validation_time: float, 
        report: ConformanceReport, 
        errors_found: int
    ):
        """Record validation metrics."""
        # Calculate total fields checked from the models defined in the conformance engine
        total_fields_checked_count = 0
        if self.engine and hasattr(self.engine, 'MODEL_TABLE_MAP'):
            for model_class in self.engine.MODEL_TABLE_MAP.keys():
                if hasattr(model_class, 'model_fields'):
                    total_fields_checked_count += len(model_class.model_fields)

        metrics = ValidationMetrics(
            validation_time=validation_time,
            tables_checked=report.total_tables,
            fields_validated=total_fields_checked_count, # Use the new calculation
            errors_found=errors_found,
            auto_fixable=sum(1 for i in report.issues if i.fix_sql),
            manual_required=sum(1 for i in report.issues if not i.fix_sql and i.severity == "error")
        )
        
        self.metrics.append(metrics)
        
        # Keep only last 100 metrics
        if len(self.metrics) > 100:
            self.metrics = self.metrics[-100:]


class ConformanceError(Exception):
    """Exception raised when conformance validation fails."""
    
    def __init__(self, message: str, report: Optional[ConformanceReport] = None):
        super().__init__(message)
        self.report = report


def validate_before_operation(operation_name: str) -> bool:
    """
    Decorator function to validate conformance before critical operations.
    
    Args:
        operation_name: Name of the operation for logging
        
    Returns:
        True if conformant, raises ConformanceError if not
    """
    try:
        validator = ConformanceValidator()
        success, report, _ = validator.validate_with_recovery(auto_fix=False)
        
        if not success:
            error_count = len([i for i in report.issues if i.severity == "error"])
            raise ConformanceError(
                f"Schema conformance failure before {operation_name}: {error_count} errors",
                report
            )
        
        logger.info(f"Conformance validated successfully before {operation_name}")
        return True
        
    except Exception as e:
        logger.error(f"Conformance validation failed before {operation_name}: {e}")
        raise ConformanceError(f"Validation error before {operation_name}: {str(e)}")


def quick_health_check() -> Dict[str, Any]:
    """
    Quick health check for critical system components.
    
    Returns:
        Dict with health status of critical components
    """
    health = {
        "timestamp": datetime.utcnow().isoformat(),
        "database_connection": False,
        "schema_conformance": False,
        "critical_tables": {},
        "overall_status": False
    }
    
    try:
        # Test database connection
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        health["database_connection"] = True
        
        # Quick conformance check for critical tables
        validator = ConformanceValidator()
        critical_tables = ["source_documents", "document_chunks", "entity_mentions"]
        
        critical_status = validator.validate_critical_tables(critical_tables)
        health["critical_tables"] = critical_status
        health["schema_conformance"] = all(critical_status.values())
        
        # Overall status
        health["overall_status"] = (
            health["database_connection"] and 
            health["schema_conformance"]
        )
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        health["error"] = str(e)
    
    return health


if __name__ == "__main__":
    import sys
    
    if "--health" in sys.argv:
        health = quick_health_check()
        print(f"Health Status: {'✅ HEALTHY' if health['overall_status'] else '❌ UNHEALTHY'}")
        for key, value in health.items():
            if key != "overall_status":
                print(f"  {key}: {value}")
    
    elif "--validate" in sys.argv:
        validator = ConformanceValidator()
        auto_fix = "--fix" in sys.argv
        
        success, report, actions = validator.validate_with_recovery(auto_fix=auto_fix)
        
        print(f"Validation Result: {'✅ SUCCESS' if success else '❌ FAILED'}")
        print(f"Issues Found: {len(report.issues)}")
        
        if actions:
            print("Recovery Actions:")
            for action in actions:
                print(f"  - {action}")
        
        if not success and report.issues:
            print("\\nTop Issues:")
            for issue in report.issues[:5]:
                print(f"  - {issue.table_name}.{issue.field_name}: {issue.issue_type.value}")
    
    else:
        print("Usage: python conformance_validator.py [--health|--validate] [--fix]")