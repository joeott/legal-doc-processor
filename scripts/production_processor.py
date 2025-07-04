#!/usr/bin/env python3
"""
Production Processor - Main orchestrator for processing entire input directories.

This script implements the production processing execution from context_397:
- Document discovery and intake
- Batch creation and submission
- Progress monitoring and validation
- Results analysis and reporting
"""

import click
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
import logging

from scripts.intake_service import DocumentIntakeService
from scripts.batch_tasks import submit_batch, create_document_records, get_batch_status
from scripts.status_manager import StatusManager
from scripts.audit_logger import AuditLogger
from scripts.validation import OCRValidator, EntityValidator, PipelineValidator
from scripts.db import DatabaseManager
from scripts.logging_config import get_logger
from sqlalchemy import text

logger = get_logger(__name__)


class ProductionProcessor:
    """Main production processing orchestrator."""
    
    def __init__(self):
        self.intake_service = DocumentIntakeService()
        # Note: Using batch_tasks functions instead of deprecated BatchProcessor
        self.status_manager = StatusManager()
        self.audit_logger = AuditLogger()
        self.db_manager = DatabaseManager(validate_conformance=False)
        
        # Validators
        self.ocr_validator = OCRValidator(self.db_manager)
        self.entity_validator = EntityValidator(self.db_manager)
        self.pipeline_validator = PipelineValidator(self.db_manager)
        
        # Campaign tracking
        self.active_campaigns = {}
    
    def ensure_project_exists(self, project_id: int, project_name: str) -> str:
        """Ensure the specified project exists, create if not. Returns project UUID."""
        for session in self.db_manager.get_session():
            # Check if project exists
            project = session.execute(text(
                "SELECT id, project_id, name FROM projects WHERE id = :id"
            ), {'id': project_id}).fetchone()
            
            if not project:
                # Generate UUID for new project (will be auto-generated by default)
                session.execute(text("""
                    INSERT INTO projects (id, name, created_at, updated_at)
                    VALUES (:id, :name, NOW(), NOW())
                """), {
                    'id': project_id,
                    'name': project_name
                })
                session.commit()
                
                # Get the generated project_id (UUID)
                project_uuid = session.execute(text(
                    "SELECT project_id FROM projects WHERE id = :id"
                ), {'id': project_id}).scalar()
                
                logger.info(f"Created project {project_id}: {project_name} with UUID {project_uuid}")
                return str(project_uuid)
            else:
                # Return existing project_id (UUID)
                project_uuid = project[1]
                logger.info(f"Using existing project {project_id}: {project[2]} with UUID {project_uuid}")
                return str(project_uuid)
    
    def execute_full_input_processing(self, input_dir: str, 
                                    batch_strategy: str = "balanced",
                                    max_concurrent_batches: int = 3,
                                    project_id: int = 1,
                                    project_uuid: str = None) -> str:
        """
        Execute full processing of an input directory.
        
        Args:
            input_dir: Directory containing documents to process
            batch_strategy: Strategy for creating batches
            max_concurrent_batches: Maximum concurrent batches
            project_id: Project ID to associate documents with
            
        Returns:
            Campaign ID for tracking
        """
        campaign_id = f"campaign_{uuid.uuid4().hex[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        logger.info(f"Starting production processing campaign {campaign_id}")
        logger.info(f"Input directory: {input_dir}")
        logger.info(f"Batch strategy: {batch_strategy}")
        
        try:
            # Phase 1: Document Discovery
            logger.info("Phase 1: Discovering documents...")
            documents = self.intake_service.discover_documents(input_dir, recursive=True)
            
            if not documents:
                logger.warning(f"No documents found in {input_dir}")
                return campaign_id
            
            logger.info(f"Discovered {len(documents)} documents")
            
            # Phase 2: Document Validation
            logger.info("Phase 2: Validating documents...")
            valid_documents = []
            invalid_count = 0
            
            for doc in documents:
                validation = self.intake_service.validate_document_integrity(doc.local_path)
                if validation.is_valid:
                    valid_documents.append(doc)
                else:
                    invalid_count += 1
                    logger.warning(f"Invalid document: {doc.filename} - {validation.error_message}")
            
            logger.info(f"Valid documents: {len(valid_documents)}, Invalid: {invalid_count}")
            
            if not valid_documents:
                logger.error("No valid documents found to process")
                return campaign_id
            
            # Phase 3: S3 Upload
            logger.info("Phase 3: Uploading documents to S3...")
            uploaded_documents = []
            
            for doc in valid_documents:
                try:
                    s3_location = self.intake_service.upload_to_s3_with_metadata(
                        doc.local_path, doc.to_dict()
                    )
                    
                    if s3_location:
                        # Update document with S3 information
                        doc.s3_bucket = s3_location.bucket
                        doc.s3_key = s3_location.key
                        uploaded_documents.append(doc)
                        logger.debug(f"Uploaded: {doc.filename}")
                    else:
                        logger.error(f"Failed to upload: {doc.filename}")
                        
                except Exception as e:
                    logger.error(f"Error uploading {doc.filename}: {e}")
            
            logger.info(f"Successfully uploaded {len(uploaded_documents)} documents")
            
            # Phase 4: Batch Creation
            logger.info("Phase 4: Creating processing batches...")
            batches = self.intake_service.create_processing_batches(uploaded_documents, batch_strategy)
            
            logger.info(f"Created {len(batches)} processing batches")
            
            # Phase 5: Batch Submission
            logger.info("Phase 5: Submitting batches for processing...")
            submitted_batches = []
            
            for batch_config in batches:
                try:
                    # Convert documents to format expected by batch_tasks
                    documents = []
                    for doc in batch_config['documents']:
                        documents.append({
                            'filename': doc.filename,
                            's3_bucket': doc.s3_bucket,
                            's3_key': doc.s3_key,
                            'file_size_mb': doc.file_size_mb,
                            'mime_type': doc.mime_type
                        })
                    
                    # Create database records for documents
                    documents_with_uuids = create_document_records(documents, project_uuid, project_id)
                    
                    # Determine priority based on batch config
                    priority = batch_config.get('priority', 'normal')
                    
                    # Submit batch for processing
                    result = submit_batch(
                        documents_with_uuids,
                        project_uuid,
                        priority=priority,
                        options=batch_config.get('options', {})
                    )
                    
                    submitted_batches.append({
                        'batch_id': result['batch_id'],
                        'job_group_id': result['task_id'],
                        'task_count': result['document_count'],
                        'submitted_at': datetime.now().isoformat()
                    })
                    
                    logger.info(f"Submitted batch {result['batch_id']} with {result['document_count']} tasks")
                    
                except Exception as e:
                    logger.error(f"Error submitting batch: {e}")
            
            # Store campaign information
            campaign_info = {
                'campaign_id': campaign_id,
                'started_at': datetime.now().isoformat(),
                'input_directory': input_dir,
                'batch_strategy': batch_strategy,
                'total_documents_discovered': len(documents),
                'valid_documents': len(valid_documents),
                'uploaded_documents': len(uploaded_documents),
                'total_batches': len(batches),
                'submitted_batches': len(submitted_batches),
                'batch_details': submitted_batches,
                'status': 'submitted'
            }
            
            self.active_campaigns[campaign_id] = campaign_info
            
            # Log campaign start
            self.audit_logger.log_processing_event(
                campaign_id,
                {
                    'timestamp': datetime.now().isoformat(),
                    'event_type': 'campaign_start',
                    'level': 'info',
                    'document_uuid': None,
                    'batch_id': None,
                    'stage': 'campaign',
                    'status': 'started',
                    'message': f"Started processing campaign with {len(uploaded_documents)} documents in {len(submitted_batches)} batches",
                    'metadata': campaign_info,
                    'elapsed_seconds': 0.0
                }
            )
            
            logger.info(f"Campaign {campaign_id} successfully started")
            logger.info(f"Processing {len(uploaded_documents)} documents in {len(submitted_batches)} batches")
            
            return campaign_id
            
        except Exception as e:
            logger.error(f"Error in production processing campaign {campaign_id}: {e}")
            raise
    
    def monitor_processing_campaign(self, campaign_id: str) -> Dict[str, Any]:
        """
        Monitor the progress of a processing campaign.
        
        Args:
            campaign_id: Campaign ID to monitor
            
        Returns:
            Campaign status information
        """
        try:
            campaign_info = self.active_campaigns.get(campaign_id)
            if not campaign_info:
                return {'error': f'Campaign {campaign_id} not found'}
            
            # Get progress for each batch
            batch_progresses = []
            total_docs = 0
            completed_docs = 0
            failed_docs = 0
            in_progress_docs = 0
            
            for batch_detail in campaign_info['batch_details']:
                batch_id = batch_detail['batch_id']
                progress = get_batch_status.apply_async(args=[batch_id]).get()
                
                if progress:
                    batch_progresses.append(progress)
                    total_docs += progress.get('total', 0)
                    completed_docs += progress.get('completed', 0)
                    failed_docs += progress.get('failed', 0)
                    in_progress_docs += progress.get('in_progress', 0)
            
            # Calculate overall campaign progress
            overall_completion = (completed_docs / total_docs * 100) if total_docs > 0 else 0
            
            # Determine campaign status
            if completed_docs + failed_docs == total_docs:
                campaign_status = 'completed'
            elif in_progress_docs > 0 or completed_docs > 0:
                campaign_status = 'in_progress'
            else:
                campaign_status = 'pending'
            
            # Calculate elapsed time
            started_at = datetime.fromisoformat(campaign_info['started_at'])
            elapsed_minutes = (datetime.now() - started_at).total_seconds() / 60
            
            return {
                'campaign_id': campaign_id,
                'status': campaign_status,
                'overall_completion_percentage': round(overall_completion, 1),
                'total_documents': total_docs,
                'completed_documents': completed_docs,
                'failed_documents': failed_docs,
                'in_progress_documents': in_progress_docs,
                'total_batches': len(campaign_info['batch_details']),
                'elapsed_minutes': round(elapsed_minutes, 1),
                'batch_progresses': batch_progresses,
                'campaign_info': campaign_info
            }
            
        except Exception as e:
            logger.error(f"Error monitoring campaign {campaign_id}: {e}")
            return {'error': str(e)}
    
    def generate_final_processing_report(self, campaign_id: str) -> Dict[str, Any]:
        """
        Generate final processing report for a completed campaign.
        
        Args:
            campaign_id: Campaign ID to report on
            
        Returns:
            Comprehensive processing report
        """
        try:
            campaign_status = self.monitor_processing_campaign(campaign_id)
            
            if 'error' in campaign_status:
                return campaign_status
            
            # Generate validation reports
            validation_results = {}
            
            # Get completed document IDs for validation
            completed_doc_ids = self._get_completed_document_ids(campaign_id)
            
            if completed_doc_ids:
                # OCR Validation
                ocr_results = []
                for doc_id in completed_doc_ids[:20]:  # Sample first 20
                    try:
                        result = self.ocr_validator.validate_text_extraction(doc_id)
                        ocr_results.append(result)
                    except Exception as e:
                        logger.error(f"OCR validation error for {doc_id}: {e}")
                
                if ocr_results:
                    validation_results['ocr'] = {
                        'total_validated': len(ocr_results),
                        'passed': sum(1 for r in ocr_results if r.validation_passed),
                        'average_quality': sum(r.quality_score for r in ocr_results) / len(ocr_results),
                        'average_confidence': sum(r.confidence_score for r in ocr_results) / len(ocr_results)
                    }
                
                # Pipeline Validation
                if len(completed_doc_ids) <= 10:  # Only for small campaigns
                    pipeline_reports = self.pipeline_validator.validate_end_to_end_flow(completed_doc_ids)
                    if pipeline_reports:
                        validation_results['pipeline'] = {
                            'total_validated': len(pipeline_reports),
                            'passed': sum(1 for r in pipeline_reports if r.validation_passed),
                            'average_processing_time': sum(r.total_processing_time_minutes for r in pipeline_reports) / len(pipeline_reports),
                            'average_consistency': sum(r.data_consistency_score for r in pipeline_reports) / len(pipeline_reports)
                        }
            
            # Generate processing summaries for each batch
            batch_summaries = []
            for batch_detail in campaign_status['campaign_info']['batch_details']:
                try:
                    summary = self.audit_logger.create_processing_summary(batch_detail['batch_id'])
                    batch_summaries.append(summary.__dict__ if hasattr(summary, '__dict__') else summary)
                except Exception as e:
                    logger.error(f"Error creating batch summary: {e}")
            
            # Calculate overall metrics
            total_processing_time = sum(
                s.get('performance_metrics', {}).get('total_processing_time_seconds', 0) 
                for s in batch_summaries
            )
            
            overall_success_rate = (
                campaign_status['completed_documents'] / 
                campaign_status['total_documents'] * 100
            ) if campaign_status['total_documents'] > 0 else 0
            
            # Create comprehensive report
            final_report = {
                'campaign_summary': campaign_status,
                'validation_results': validation_results,
                'batch_summaries': batch_summaries,
                'overall_metrics': {
                    'total_processing_time_hours': total_processing_time / 3600,
                    'average_processing_time_per_document_minutes': (
                        total_processing_time / campaign_status['total_documents'] / 60
                    ) if campaign_status['total_documents'] > 0 else 0,
                    'overall_success_rate_percentage': round(overall_success_rate, 2),
                    'throughput_documents_per_hour': (
                        campaign_status['total_documents'] / campaign_status['elapsed_minutes'] * 60
                    ) if campaign_status['elapsed_minutes'] > 0 else 0
                },
                'report_generated_at': datetime.now().isoformat(),
                'report_type': 'final_campaign_report'
            }
            
            # Save report
            report_path = self._save_final_report(campaign_id, final_report)
            final_report['report_path'] = report_path
            
            return final_report
            
        except Exception as e:
            logger.error(f"Error generating final report for campaign {campaign_id}: {e}")
            return {'error': str(e)}
    
    def _get_completed_document_ids(self, campaign_id: str) -> List[str]:
        """Get list of completed document IDs for a campaign."""
        completed_ids = []
        
        try:
            campaign_info = self.active_campaigns.get(campaign_id)
            if not campaign_info:
                return completed_ids
            
            # Get document IDs from batch progresses
            for batch_detail in campaign_info['batch_details']:
                batch_id = batch_detail['batch_id']
                
                # Get batch manifest to find document IDs
                try:
                    batch_summary = self.batch_processor.get_batch_summary(batch_id)
                    if batch_summary and 'batch_info' in batch_summary:
                        documents = batch_summary['batch_info'].get('documents', [])
                        for doc in documents:
                            doc_uuid = doc.get('document_uuid') or doc.get('filename')
                            if doc_uuid:
                                # Check if document is completed
                                doc_status = self.status_manager.get_document_status(doc_uuid)
                                if doc_status and doc_status.overall_status == 'completed':
                                    completed_ids.append(doc_uuid)
                except Exception as e:
                    logger.error(f"Error checking batch {batch_id}: {e}")
            
        except Exception as e:
            logger.error(f"Error getting completed document IDs for campaign {campaign_id}: {e}")
        
        return completed_ids
    
    def _save_final_report(self, campaign_id: str, report: Dict[str, Any]) -> str:
        """Save final report to file."""
        try:
            reports_dir = Path("/opt/legal-doc-processor/monitoring/reports")
            reports_dir.mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"final_report_{campaign_id}_{timestamp}.json"
            filepath = reports_dir / filename
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, default=str, ensure_ascii=False)
            
            logger.info(f"Final report saved to: {filepath}")
            return str(filepath)
            
        except Exception as e:
            logger.error(f"Error saving final report: {e}")
            return ""


@click.group()
def cli():
    """Production processing commands."""
    pass


@cli.command()
@click.argument('input_directory', type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option('--batch-strategy', type=click.Choice(['balanced', 'priority_first', 'size_optimized']), 
              default='balanced', help='Batching strategy')
@click.option('--max-batches', default=5, help='Maximum concurrent batches')
@click.option('--project-id', type=int, default=1, 
              help='Project ID to associate documents with (default: 1)')
@click.option('--project-name', type=str, default='Default Project',
              help='Project name if creating new (default: Default Project)')
def process(input_directory, batch_strategy, max_batches, project_id, project_name):
    """Process all documents in an input directory."""
    processor = ProductionProcessor()
    
    # Ensure project exists and get UUID
    project_uuid = processor.ensure_project_exists(project_id, project_name)
    
    click.echo(f"Starting production processing of {input_directory}")
    click.echo(f"Batch strategy: {batch_strategy}")
    click.echo(f"Max concurrent batches: {max_batches}")
    click.echo(f"Project ID: {project_id}")
    click.echo(f"Project UUID: {project_uuid}")
    
    try:
        campaign_id = processor.execute_full_input_processing(
            input_directory, batch_strategy, max_batches, project_id, project_uuid
        )
        
        click.echo(f"\n✅ Processing campaign started successfully!")
        click.echo(f"Campaign ID: {campaign_id}")
        click.echo(f"\nUse 'production_processor monitor {campaign_id}' to track progress")
        
    except Exception as e:
        click.echo(f"❌ Error starting processing: {e}", err=True)
        raise click.Abort()


@cli.command()
@click.argument('campaign_id')
@click.option('--watch', is_flag=True, help='Watch progress continuously')
@click.option('--interval', default=30, help='Refresh interval in seconds')
def monitor(campaign_id, watch, interval):
    """Monitor processing campaign progress."""
    processor = ProductionProcessor()
    
    def show_status():
        status = processor.monitor_processing_campaign(campaign_id)
        
        if 'error' in status:
            click.echo(f"❌ {status['error']}", err=True)
            return False
        
        click.echo(f"\n📊 Campaign Status: {campaign_id}")
        click.echo(f"Status: {status['status']}")
        click.echo(f"Overall Progress: {status['overall_completion_percentage']:.1f}%")
        click.echo(f"Documents: {status['completed_documents']}/{status['total_documents']} completed")
        click.echo(f"Failed: {status['failed_documents']}")
        click.echo(f"In Progress: {status['in_progress_documents']}")
        click.echo(f"Elapsed Time: {status['elapsed_minutes']:.1f} minutes")
        
        if status['batch_progresses']:
            click.echo(f"\n📦 Batch Progress:")
            for batch in status['batch_progresses']:
                click.echo(f"  {batch['batch_id']}: {batch['completion_percentage']:.1f}% "
                          f"({batch['completed_documents']}/{batch['total_documents']})")
        
        return status['status'] not in ['completed', 'failed']
    
    if watch:
        click.echo(f"👀 Monitoring campaign {campaign_id} (press Ctrl+C to stop)")
        try:
            while show_status():
                time.sleep(interval)
        except KeyboardInterrupt:
            click.echo("\n⏹️  Monitoring stopped")
    else:
        show_status()


@cli.command()
@click.argument('campaign_id')
def report(campaign_id):
    """Generate final processing report for a campaign."""
    processor = ProductionProcessor()
    
    click.echo(f"📋 Generating final report for campaign {campaign_id}...")
    
    try:
        report = processor.generate_final_processing_report(campaign_id)
        
        if 'error' in report:
            click.echo(f"❌ {report['error']}", err=True)
            raise click.Abort()
        
        # Display summary
        campaign = report['campaign_summary']
        metrics = report['overall_metrics']
        
        click.echo(f"\n✅ Final Report Generated")
        click.echo(f"Report saved to: {report.get('report_path', 'Not saved')}")
        
        click.echo(f"\n📊 Campaign Summary:")
        click.echo(f"  Total Documents: {campaign['total_documents']}")
        click.echo(f"  Completed: {campaign['completed_documents']}")
        click.echo(f"  Failed: {campaign['failed_documents']}")
        click.echo(f"  Success Rate: {metrics['overall_success_rate_percentage']:.1f}%")
        click.echo(f"  Total Processing Time: {metrics['total_processing_time_hours']:.1f} hours")
        click.echo(f"  Average Time per Document: {metrics['average_processing_time_per_document_minutes']:.1f} minutes")
        click.echo(f"  Throughput: {metrics['throughput_documents_per_hour']:.1f} docs/hour")
        
        # Validation results
        validation = report.get('validation_results', {})
        if 'ocr' in validation:
            ocr = validation['ocr']
            click.echo(f"\n🔍 OCR Validation ({ocr['total_validated']} documents):")
            click.echo(f"  Passed: {ocr['passed']}/{ocr['total_validated']}")
            click.echo(f"  Average Quality: {ocr['average_quality']:.1f}/100")
            click.echo(f"  Average Confidence: {ocr['average_confidence']:.1f}%")
        
        if 'pipeline' in validation:
            pipeline = validation['pipeline']
            click.echo(f"\n🔄 Pipeline Validation ({pipeline['total_validated']} documents):")
            click.echo(f"  Passed: {pipeline['passed']}/{pipeline['total_validated']}")
            click.echo(f"  Average Processing Time: {pipeline['average_processing_time']:.1f} minutes")
            click.echo(f"  Average Consistency: {pipeline['average_consistency']:.1f}%")
        
    except Exception as e:
        click.echo(f"❌ Error generating report: {e}", err=True)
        raise click.Abort()


if __name__ == '__main__':
    cli()