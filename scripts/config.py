# config.py
import os
from pathlib import Path
from dotenv import load_dotenv
import logging

# Load environment variables from .env file in the current script's directory
load_dotenv(Path(__file__).resolve().parent / '.env')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# SQLAlchemy imports
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Project Identification
PROJECT_ID_GLOBAL = os.getenv("PROJECT_ID", "legal-docs-processing")

# Stage Definitions
STAGE_CLOUD_ONLY = "1"      # OpenAI-first, no local models
STAGE_HYBRID = "2"          # Docker with local models + cloud fallback
STAGE_LOCAL_PROD = "3"      # EC2 production with full local models

VALID_STAGES = [STAGE_CLOUD_ONLY, STAGE_HYBRID, STAGE_LOCAL_PROD]
STAGE_DESCRIPTIONS = {
    STAGE_CLOUD_ONLY: "Cloud-only (OpenAI/Textract)",
    STAGE_HYBRID: "Hybrid (Local + Cloud fallback)",
    STAGE_LOCAL_PROD: "Production (Local models primary)"
}


class StageConfig:
    """Centralized stage-specific configuration management."""
    
    def __init__(self, stage: str):
        self.stage = stage
        self._config = self._build_stage_config()
    
    def _build_stage_config(self) -> dict:
        """Build configuration based on deployment stage."""
        base_config = {
            "force_cloud_llms": False,
            "bypass_local_models": False,
            "use_openai_structured": False,
            "use_openai_entities": False,
            "use_openai_audio": False,
            "require_openai_key": False,
            "require_mistral_key": False,
            "allow_local_fallback": True
        }
        
        if self.stage == STAGE_CLOUD_ONLY:
            return {
                "force_cloud_llms": True,
                "bypass_local_models": True,
                "use_openai_structured": True,
                "use_openai_entities": True,
                "use_openai_audio": True,
                "require_openai_key": True,
                "require_mistral_key": False,  # No longer required
                "allow_local_fallback": False
            }
        elif self.stage == STAGE_HYBRID:
            return {
                "force_cloud_llms": False,
                "bypass_local_models": False,
                "use_openai_structured": False,
                "use_openai_entities": False,
                "use_openai_audio": False,
                "require_openai_key": True,
                "require_mistral_key": False,  # No longer required
                "allow_local_fallback": True
            }
        else:  # STAGE_LOCAL_PROD
            return base_config
    
    def get(self, key: str, default=None):
        """Get configuration value."""
        return self._config.get(key, default)
    
    def validate_requirements(self):
        """Validate stage-specific requirements."""
        errors = []
        
        if self._config["require_openai_key"] and not (os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_API_KEY")):
            errors.append(f"OPENAI_API_KEY required for Stage {self.stage}")
        
        if errors:
            raise ValueError("\n".join(errors))
        
        return True


def validate_deployment_stage():
    """Validate and return the deployment stage with detailed logging."""
    stage = os.getenv("DEPLOYMENT_STAGE", STAGE_CLOUD_ONLY)
    
    if stage not in VALID_STAGES:
        raise ValueError(
            f"Invalid DEPLOYMENT_STAGE '{stage}'. "
            f"Must be one of: {', '.join(VALID_STAGES)}"
        )
    
    # Log stage information
    print(f"Deployment Stage: {stage} - {STAGE_DESCRIPTIONS[stage]}")
    return stage


# Directories
# Base directory for the project (use the parent of the current script directory)
BASE_DIR = Path(__file__).resolve().parent.parent

# Source document directory (where local files for processing are stored)
SOURCE_DOCUMENT_DIR = os.getenv("SOURCE_DOCUMENT_DIR", str(BASE_DIR / "input_docs"))

# S3 Configuration
USE_S3_FOR_INPUT = os.getenv("USE_S3_FOR_INPUT", "false").lower() in ("true", "1", "yes")
S3_PRIMARY_DOCUMENT_BUCKET = os.getenv("S3_PRIMARY_DOCUMENT_BUCKET", "samu-docs-private-upload")  # Primary private bucket
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", S3_PRIMARY_DOCUMENT_BUCKET)  # For backwards compatibility
S3_TEMP_DOWNLOAD_DIR = os.getenv("S3_TEMP_DOWNLOAD_DIR", str(BASE_DIR / "s3_downloads"))

# AWS Configuration (ensure these are present)
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
AWS_DEFAULT_REGION = os.getenv('AWS_DEFAULT_REGION', 'us-east-1')  # Use your target region

# S3 Bucket Region Configuration
# The S3 bucket is in us-east-2, so Textract must use the same region
S3_BUCKET_REGION = os.getenv('S3_BUCKET_REGION', 'us-east-2')  # Specific region for S3 bucket operations

# S3 Buckets - simplified to single private bucket
S3_BUCKET_PRIVATE = S3_PRIMARY_DOCUMENT_BUCKET  # For backwards compatibility

# File naming
USE_UUID_FILE_NAMING = os.getenv('USE_UUID_FILE_NAMING', 'true').lower() in ('true', '1', 'yes')

# Database Configuration (RDS PostgreSQL)
DATABASE_URL = os.getenv("DATABASE_URL")  # Primary connection (uses SSH tunnel for local dev)
DATABASE_URL_DIRECT = os.getenv("DATABASE_URL_DIRECT")  # Direct connection for production
RDS_MASTER_USER = os.getenv("RDS_MASTER_USER", "postgres")
RDS_MASTER_PASSWORD = os.getenv("RDS_MASTER_PASSWORD")

# SSH Tunnel Configuration for RDS
RDS_TUNNEL_LOCAL_PORT = int(os.getenv("RDS_TUNNEL_LOCAL_PORT", "5433"))
RDS_BASTION_HOST = os.getenv("RDS_BASTION_HOST", "54.162.223.205")
RDS_BASTION_USER = os.getenv("RDS_BASTION_USER", "ubuntu")
RDS_BASTION_KEY = os.getenv("RDS_BASTION_KEY", "resources/aws/legal-doc-processor-bastion.pem")

# Database Connection Pool Settings
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "20"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "40"))
DB_POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "30"))
DB_POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "3600"))
DB_SSL_MODE = os.getenv("DB_SSL_MODE", "require")

# Optimized connection pool configuration for SSH tunnel operations
DB_POOL_CONFIG = {
    'pool_size': 5,  # Reduced from 20 for better per-process handling
    'max_overflow': 10,  # Reduced from 40
    'pool_timeout': DB_POOL_TIMEOUT,
    'pool_recycle': 300,  # Recycle every 5 minutes instead of 3600 (1 hour)
    'pool_pre_ping': True,  # Verify connections before use
    'isolation_level': 'READ COMMITTED',  # Ensure fresh reads
    'connect_args': {
        'connect_timeout': 10,
        'options': '-c statement_timeout=300000',  # 5 min timeout
        'keepalives': 1,
        'keepalives_idle': 30,
        'keepalives_interval': 10,
        'keepalives_count': 5,
        'sslmode': DB_SSL_MODE  # Ensure SSL mode is used
    }
}

# Legacy Supabase Configuration (kept for backwards compatibility)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

# Processing Options
FORCE_REPROCESS_OCR = os.getenv("FORCE_REPROCESS_OCR", "false").lower() in ("true", "1", "yes")
USE_STRUCTURED_EXTRACTION = os.getenv("USE_STRUCTURED_EXTRACTION", "true").lower() in ("true", "1", "yes")

# AWS Textract Configuration
TEXTRACT_FEATURE_TYPES = os.getenv('TEXTRACT_FEATURE_TYPES', 'TABLES,FORMS').split(',')  # For AnalyzeDocument
TEXTRACT_CONFIDENCE_THRESHOLD = float(os.getenv('TEXTRACT_CONFIDENCE_THRESHOLD', '80.0'))
TEXTRACT_MAX_RESULTS_PER_PAGE = int(os.getenv('TEXTRACT_MAX_RESULTS_PER_PAGE', '1000'))
TEXTRACT_USE_ASYNC_FOR_PDF = os.getenv('TEXTRACT_USE_ASYNC_FOR_PDF', 'true').lower() in ('true', '1', 'yes')
TEXTRACT_ASYNC_MAX_POLLING_TIME_SECONDS = int(os.getenv('TEXTRACT_ASYNC_MAX_POLLING_TIME_SECONDS', '600'))
TEXTRACT_ASYNC_POLLING_INTERVAL_SECONDS = int(os.getenv('TEXTRACT_ASYNC_POLLING_INTERVAL_SECONDS', '5'))
TEXTRACT_ASYNC_INITIAL_DELAY_SECONDS = int(os.getenv('TEXTRACT_ASYNC_INITIAL_DELAY_SECONDS', '5'))
TEXTRACT_SNS_TOPIC_ARN = os.getenv('TEXTRACT_SNS_TOPIC_ARN')
TEXTRACT_SNS_ROLE_ARN = os.getenv('TEXTRACT_SNS_ROLE_ARN')
TEXTRACT_OUTPUT_S3_BUCKET = os.getenv('TEXTRACT_OUTPUT_S3_BUCKET', S3_PRIMARY_DOCUMENT_BUCKET)  # Can be same or dedicated
TEXTRACT_OUTPUT_S3_PREFIX = os.getenv('TEXTRACT_OUTPUT_S3_PREFIX', 'textract-output/')
TEXTRACT_KMS_KEY_ID = os.getenv('TEXTRACT_KMS_KEY_ID')

# Qwen2-VL OCR Configuration (fallback)
QWEN2_VL_OCR_PROMPT = os.getenv("QWEN2_VL_OCR_PROMPT", "Please carefully examine this document and extract all visible text, preserving the original formatting and structure as much as possible.")
QWEN2_VL_OCR_MAX_NEW_TOKENS = int(os.getenv("QWEN2_VL_OCR_MAX_NEW_TOKENS", "2048"))
QWEN2_VL_OCR_MODEL_NAME = os.getenv("QWEN2_VL_OCR_MODEL_NAME", "Qwen/Qwen2-VL-2B-Instruct")

# OpenAI Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
LLM_MODEL_FOR_RESOLUTION = os.getenv("LLM_MODEL_FOR_RESOLUTION", OPENAI_MODEL)
LLM_API_KEY = OPENAI_API_KEY  # Alias for entity resolution

# OpenAI o4-mini Vision Configuration
O4_MINI_MODEL = "o4-mini-2025-04-16"
O4_MINI_VISION_PRICING = {
    'input_tokens_per_1k': 0.00015,  # $0.00015 per 1K input tokens
    'output_tokens_per_1k': 0.0006,  # $0.0006 per 1K output tokens  
    'image_base_cost': 0.00765,   # Base cost per image (standard vision pricing)
    'image_detail_high_cost': 0.01275,  # Additional cost for high detail
}

# File Type Configuration
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif', '.webp', '.heic', '.heif'}
DOCUMENT_EXTENSIONS = {'.pdf', '.docx', '.doc', '.txt', '.rtf', '.eml'}
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.aac', '.flac'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.wmv', '.flv', '.webm', '.m4v'}  # Reserved for future deployment

# Image processing defaults
DEFAULT_IMAGE_CONFIDENCE_THRESHOLD = 0.7  # Minimum confidence for accepting results
IMAGE_RETRY_MAX_ATTEMPTS = 3  # Maximum retry attempts for image processing
IMAGE_PROCESSING_TIMEOUT_SECONDS = 120  # Timeout for image processing operations

# Stage Management Configuration
DEPLOYMENT_STAGE = validate_deployment_stage()

# Model Configuration
USE_MINIMAL_MODELS = os.getenv('USE_MINIMAL_MODELS', 'false').lower() == 'true'
SKIP_CONFORMANCE_CHECK = os.getenv('SKIP_CONFORMANCE_CHECK', 'false').lower() == 'true'

if SKIP_CONFORMANCE_CHECK:
    logger.warning("CONFORMANCE VALIDATION BYPASSED - FOR TESTING ONLY")
if USE_MINIMAL_MODELS:
    logger.info("Using minimal models for reduced conformance requirements")

# Initialize stage configuration
stage_config = StageConfig(DEPLOYMENT_STAGE)
stage_config.validate_requirements()

# Database URL selection based on deployment stage
def get_database_url():
    """Get appropriate database URL based on deployment stage and environment."""
    # Allow explicit override via environment variable
    if os.getenv("USE_DIRECT_DATABASE_CONNECTION", "false").lower() in ("true", "1", "yes"):
        return DATABASE_URL_DIRECT or DATABASE_URL
    
    # For production stage (Stage 3), use direct connection
    if DEPLOYMENT_STAGE == STAGE_LOCAL_PROD:
        return DATABASE_URL_DIRECT or DATABASE_URL
    
    # For development/staging, use tunnel connection
    return DATABASE_URL

# PDF Processing Configuration
PDF_CONVERSION_DPI = int(os.getenv('PDF_CONVERSION_DPI', '300'))
PDF_CONVERSION_FORMAT = os.getenv('PDF_CONVERSION_FORMAT', 'PNG')
ENABLE_SCANNED_PDF_DETECTION = os.getenv('ENABLE_SCANNED_PDF_DETECTION', 'true').lower() == 'true'
PDF_PAGE_PROCESSING_PARALLEL = os.getenv('PDF_PAGE_PROCESSING_PARALLEL', 'false').lower() == 'true'
SCANNED_PDF_IMAGE_PREFIX = os.getenv('SCANNED_PDF_IMAGE_PREFIX', 'converted-images/')

# Document Processing Limits
DOCUMENT_SIZE_LIMIT_MB = int(os.getenv('DOCUMENT_SIZE_LIMIT_MB', '100'))
MAX_DOCUMENTS_PER_BATCH = int(os.getenv('MAX_DOCUMENTS_PER_BATCH', '25'))
DEFAULT_BATCH_PRIORITY = os.getenv('DEFAULT_BATCH_PRIORITY', 'normal')

EFFECTIVE_DATABASE_URL = get_database_url()

# Log the effective database URL
logger.info(f"EFFECTIVE_DATABASE_URL: {EFFECTIVE_DATABASE_URL}")

# Global SQLAlchemy engine
db_engine = create_engine(EFFECTIVE_DATABASE_URL, **DB_POOL_CONFIG)

# Global session factory
DBSessionLocal = sessionmaker(bind=db_engine)

# Apply stage-specific overrides
FORCE_CLOUD_LLMS = stage_config.get("force_cloud_llms")
BYPASS_LOCAL_MODELS = stage_config.get("bypass_local_models")
USE_OPENAI_FOR_STRUCTURED_EXTRACTION = stage_config.get("use_openai_structured")
USE_OPENAI_FOR_ENTITY_EXTRACTION = stage_config.get("use_openai_entities")
USE_OPENAI_FOR_AUDIO_TRANSCRIPTION = stage_config.get("use_openai_audio")

# Allow environment overrides for non-Stage 1 deployments
if DEPLOYMENT_STAGE != STAGE_CLOUD_ONLY:
    FORCE_CLOUD_LLMS = os.getenv("FORCE_CLOUD_LLMS", str(FORCE_CLOUD_LLMS)).lower() in ("true", "1", "yes")
    BYPASS_LOCAL_MODELS = os.getenv("BYPASS_LOCAL_MODELS", str(BYPASS_LOCAL_MODELS)).lower() in ("true", "1", "yes")
    USE_OPENAI_FOR_STRUCTURED_EXTRACTION = os.getenv("USE_OPENAI_FOR_STRUCTURED_EXTRACTION", 
                                                      str(USE_OPENAI_FOR_STRUCTURED_EXTRACTION)).lower() in ("true", "1", "yes")
    USE_OPENAI_FOR_ENTITY_EXTRACTION = os.getenv("USE_OPENAI_FOR_ENTITY_EXTRACTION", 
                                                  str(USE_OPENAI_FOR_ENTITY_EXTRACTION)).lower() in ("true", "1", "yes")
    USE_OPENAI_FOR_AUDIO_TRANSCRIPTION = os.getenv("USE_OPENAI_FOR_AUDIO_TRANSCRIPTION", 
                                                    str(USE_OPENAI_FOR_AUDIO_TRANSCRIPTION)).lower() in ("true", "1", "yes")

# NER Configuration
NER_GENERAL_MODEL = os.getenv("NER_GENERAL_MODEL", "dbmdz/bert-large-cased-finetuned-conll03-english")
ENTITY_TYPE_SCHEMA_MAP = {
    "PERSON": "person",
    "ORG": "organization", 
    "LOC": "location",
    "DATE": "date",
    "PHONE": "phone",
    "EMAIL": "email"
}

# Queue Processing - DEPRECATED (Using Celery now)
# QUEUE_BATCH_SIZE = int(os.getenv("QUEUE_BATCH_SIZE", "5"))
# MAX_PROCESSING_TIME_MINUTES = int(os.getenv("MAX_PROCESSING_TIME_MINUTES", "60"))
# MAX_QUEUE_ATTEMPTS = int(os.getenv("MAX_QUEUE_ATTEMPTS", "3"))

# Document Intake Configuration (New for Celery-based processing)
DOCUMENT_INTAKE_DIR = os.getenv('DOCUMENT_INTAKE_DIR', str(BASE_DIR / 'document_intake'))
os.makedirs(DOCUMENT_INTAKE_DIR, exist_ok=True)

# Redis Configuration
USE_REDIS_CACHE = os.getenv("USE_REDIS_CACHE", "true").lower() in ("true", "1", "yes")

# Parse Redis Cloud endpoint if available
REDIS_ENDPOINT = os.getenv("REDIS_PUBLIC_ENDPOINT", "")
if REDIS_ENDPOINT and ":" in REDIS_ENDPOINT:
    REDIS_HOST, REDIS_PORT_STR = REDIS_ENDPOINT.rsplit(":", 1)
    REDIS_PORT = int(REDIS_PORT_STR)
else:
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PW") or os.getenv("REDIS_PASSWORD")
REDIS_USERNAME = os.getenv("REDIS_USERNAME")
# Redis Cloud doesn't require SSL on this port (confirmed by testing)
REDIS_SSL = os.getenv("REDIS_SSL", "false").lower() in ("true", "1", "yes")
REDIS_DECODE_RESPONSES = True  # Always decode to strings for easier handling

# Redis Memory Management Settings
REDIS_MAX_MEMORY_MB = int(os.getenv('REDIS_MAX_MEMORY_MB', '1024'))  # 1GB default
REDIS_EVICTION_POLICY = os.getenv('REDIS_EVICTION_POLICY', 'allkeys-lru')

# Redis Cache TTL Settings (in seconds) - Production optimized
# Adjust TTLs for production workloads to manage memory usage
if os.getenv('ENVIRONMENT') == 'production':
    REDIS_OCR_CACHE_TTL = int(os.getenv("REDIS_OCR_CACHE_TTL", str(3 * 24 * 3600)))  # 3 days instead of 7
    REDIS_CHUNK_CACHE_TTL = int(os.getenv("REDIS_CHUNK_CACHE_TTL", str(1 * 24 * 3600)))  # 1 day instead of 2
else:
    REDIS_OCR_CACHE_TTL = int(os.getenv("REDIS_OCR_CACHE_TTL", str(7 * 24 * 3600)))  # 7 days
    REDIS_CHUNK_CACHE_TTL = int(os.getenv("REDIS_CHUNK_CACHE_TTL", str(2 * 24 * 3600)))  # 2 days

REDIS_LLM_CACHE_TTL = int(os.getenv("REDIS_LLM_CACHE_TTL", str(24 * 3600)))  # 24 hours
REDIS_ENTITY_CACHE_TTL = int(os.getenv("REDIS_ENTITY_CACHE_TTL", str(12 * 3600)))  # 12 hours
REDIS_STRUCTURED_CACHE_TTL = int(os.getenv("REDIS_STRUCTURED_CACHE_TTL", str(24 * 3600)))  # 24 hours
REDIS_LOCK_TIMEOUT = int(os.getenv("REDIS_LOCK_TIMEOUT", "300"))  # 5 minutes
REDIS_IDEMPOTENCY_TTL = int(os.getenv("REDIS_IDEMPOTENCY_TTL", str(24 * 3600)))  # 24 hours

# Redis Connection Pool Settings
REDIS_MAX_CONNECTIONS = int(os.getenv("REDIS_MAX_CONNECTIONS", "50"))
REDIS_SOCKET_KEEPALIVE = True
REDIS_SOCKET_KEEPALIVE_OPTIONS = {}  # Platform-specific keepalive options

# Stage-specific Redis configuration
def get_redis_config_for_stage(stage: str) -> dict:
    """Get Redis configuration based on deployment stage."""
    if stage == STAGE_CLOUD_ONLY:
        # Use AWS ElastiCache or Redis Cloud
        return {
            "host": os.getenv("REDIS_CLOUD_HOST", REDIS_HOST),
            "port": int(os.getenv("REDIS_CLOUD_PORT", str(REDIS_PORT))),
            "ssl": REDIS_SSL,  # Use configured value, not hardcoded
            "ssl_cert_reqs": "none" if REDIS_SSL else None
        }
    elif stage == STAGE_HYBRID:
        # Use local Redis in Docker or cloud Redis
        return {
            "host": REDIS_HOST,
            "port": REDIS_PORT,
            "ssl": REDIS_SSL
        }
    else:  # STAGE_LOCAL_PROD
        # Use dedicated Redis instance on EC2
        return {
            "host": os.getenv("REDIS_PROD_HOST", REDIS_HOST),
            "port": int(os.getenv("REDIS_PROD_PORT", str(REDIS_PORT))),
            "ssl": False
        }

# Apply stage-specific Redis configuration
REDIS_CONFIG = get_redis_config_for_stage(DEPLOYMENT_STAGE)

# Redis Optimization Settings
REDIS_ENABLE_OPTIMIZATION = os.getenv("REDIS_ENABLE_OPTIMIZATION", "true").lower() in ("true", "1", "yes")
REDIS_CACHE_WARMING_ENABLED = os.getenv("REDIS_CACHE_WARMING_ENABLED", "true").lower() in ("true", "1", "yes")
REDIS_CACHE_WARMING_HOURS = int(os.getenv("REDIS_CACHE_WARMING_HOURS", "24"))
REDIS_CACHE_WARMING_LIMIT = int(os.getenv("REDIS_CACHE_WARMING_LIMIT", "100"))
REDIS_MONITOR_ENABLED = os.getenv("REDIS_MONITOR_ENABLED", "false").lower() in ("true", "1", "yes")
REDIS_MONITOR_PORT = int(os.getenv("REDIS_MONITOR_PORT", "8090"))

# Redis Stream Configuration (for future implementation)
STREAM_PREFIX = os.getenv("STREAM_PREFIX", "docpipe")
MAX_STREAM_RETRIES = int(os.getenv("MAX_STREAM_RETRIES", "3"))
STREAM_MSG_IDLE_TIMEOUT_MS = int(os.getenv("STREAM_MSG_IDLE_TIMEOUT_MS", "300000"))  # 5 minutes

# Redis Cluster Support (future)
REDIS_CLUSTER_ENABLED = os.getenv("REDIS_CLUSTER_ENABLED", "false").lower() in ("true", "1", "yes")
REDIS_CLUSTER_NODES = os.getenv("REDIS_CLUSTER_NODES", "").split(",") if os.getenv("REDIS_CLUSTER_NODES") else []

# Make sure required directories exist
os.makedirs(SOURCE_DOCUMENT_DIR, exist_ok=True)
if USE_S3_FOR_INPUT:
    os.makedirs(S3_TEMP_DOWNLOAD_DIR, exist_ok=True)

# Validate required environment variables
if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    print("WARNING: SUPABASE_URL or SUPABASE_ANON_KEY environment variables are not set.")
    print("The application will likely fail when trying to connect to the database.")
    print("Please set these environment variables before running the application.")

# Warn if AWS credentials are not set (required for Textract)
if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
    print("WARNING: AWS credentials (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY) are not set.")
    print("Text extraction from PDFs using AWS Textract will fail. Please set these environment variables.")

# Add region validation
import boto3
from botocore.exceptions import ClientError

def validate_aws_regions():
    """Validate AWS region configuration"""
    
    # Check S3 bucket region
    try:
        s3_client = boto3.client('s3')
        response = s3_client.get_bucket_location(Bucket=S3_PRIMARY_DOCUMENT_BUCKET)
        actual_region = response.get('LocationConstraint') or 'us-east-1'
        
        if actual_region != S3_BUCKET_REGION:
            logger.warning(f"S3 bucket region mismatch: actual={actual_region}, config={S3_BUCKET_REGION}")
            # Update the config
            os.environ['S3_BUCKET_REGION'] = actual_region
            globals()['S3_BUCKET_REGION'] = actual_region
            
        logger.info(f"S3 bucket {S3_PRIMARY_DOCUMENT_BUCKET} is in region {actual_region}")
        
    except ClientError as e:
        logger.error(f"Error checking S3 bucket region: {e}")
    
    # Ensure Textract uses same region
    if AWS_DEFAULT_REGION != S3_BUCKET_REGION:
        logger.warning(f"Region mismatch: AWS_DEFAULT_REGION={AWS_DEFAULT_REGION}, S3_BUCKET_REGION={S3_BUCKET_REGION}")
        logger.info("Textract will use S3_BUCKET_REGION for consistency")
    
    return S3_BUCKET_REGION

# Run validation on import
VALIDATED_REGION = validate_aws_regions()

# Validation helper functions
def validate_cloud_services():
    """Validate cloud service configurations."""
    validations = []
    
    # OpenAI validation
    if USE_OPENAI_FOR_ENTITY_EXTRACTION or USE_OPENAI_FOR_STRUCTURED_EXTRACTION:
        if not OPENAI_API_KEY:
            validations.append("OpenAI API key missing but OpenAI services enabled")
        else:
            validations.append("✓ OpenAI API key configured")
    
    # AWS Credentials Validation (New - for Textract)
    if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY or not AWS_DEFAULT_REGION:
        validations.append("AWS credentials (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION) are required for Textract OCR.")
    else:
        validations.append("✓ AWS credentials configured for Textract.")
    
    return validations


def get_stage_info() -> dict:
    """Get comprehensive stage information for logging/debugging."""
    return {
        "stage": DEPLOYMENT_STAGE,
        "description": STAGE_DESCRIPTIONS[DEPLOYMENT_STAGE],
        "cloud_only": FORCE_CLOUD_LLMS,
        "bypass_local": BYPASS_LOCAL_MODELS,
        "openai_features": {
            "structured_extraction": USE_OPENAI_FOR_STRUCTURED_EXTRACTION,
            "entity_extraction": USE_OPENAI_FOR_ENTITY_EXTRACTION,
            "audio_transcription": USE_OPENAI_FOR_AUDIO_TRANSCRIPTION
        },
        "validations": validate_cloud_services()
    }


def reset_stage_config():
    """Reset stage configuration for testing."""
    global DEPLOYMENT_STAGE, FORCE_CLOUD_LLMS, BYPASS_LOCAL_MODELS
    global USE_OPENAI_FOR_STRUCTURED_EXTRACTION, USE_OPENAI_FOR_ENTITY_EXTRACTION
    global USE_OPENAI_FOR_AUDIO_TRANSCRIPTION, stage_config
    
    # Re-initialize from environment
    DEPLOYMENT_STAGE = validate_deployment_stage()
    stage_config = StageConfig(DEPLOYMENT_STAGE)
    
    # Only validate requirements if not in testing context
    try:
        stage_config.validate_requirements()
    except ValueError:
        # Allow reset without validation for testing
        pass
    
    # Re-apply configurations
    FORCE_CLOUD_LLMS = stage_config.get("force_cloud_llms")
    BYPASS_LOCAL_MODELS = stage_config.get("bypass_local_models")
    USE_OPENAI_FOR_STRUCTURED_EXTRACTION = stage_config.get("use_openai_structured")
    USE_OPENAI_FOR_ENTITY_EXTRACTION = stage_config.get("use_openai_entities")
    USE_OPENAI_FOR_AUDIO_TRANSCRIPTION = stage_config.get("use_openai_audio")
    
    # Re-apply environment overrides for non-Stage 1
    if DEPLOYMENT_STAGE != STAGE_CLOUD_ONLY:
        FORCE_CLOUD_LLMS = os.getenv("FORCE_CLOUD_LLMS", str(FORCE_CLOUD_LLMS)).lower() in ("true", "1", "yes")
        BYPASS_LOCAL_MODELS = os.getenv("BYPASS_LOCAL_MODELS", str(BYPASS_LOCAL_MODELS)).lower() in ("true", "1", "yes")
        USE_OPENAI_FOR_STRUCTURED_EXTRACTION = os.getenv("USE_OPENAI_FOR_STRUCTURED_EXTRACTION", 
                                                          str(USE_OPENAI_FOR_STRUCTURED_EXTRACTION)).lower() in ("true", "1", "yes")
        USE_OPENAI_FOR_ENTITY_EXTRACTION = os.getenv("USE_OPENAI_FOR_ENTITY_EXTRACTION", 
                                                      str(USE_OPENAI_FOR_ENTITY_EXTRACTION)).lower() in ("true", "1", "yes")
        USE_OPENAI_FOR_AUDIO_TRANSCRIPTION = os.getenv("USE_OPENAI_FOR_AUDIO_TRANSCRIPTION", 
                                                        str(USE_OPENAI_FOR_AUDIO_TRANSCRIPTION)).lower() in ("true", "1", "yes")


def set_stage_for_testing(stage: str):
    """Temporarily set stage for testing purposes."""
    # Clear any existing overrides that might interfere
    for key in ["FORCE_CLOUD_LLMS", "BYPASS_LOCAL_MODELS", 
                "USE_OPENAI_FOR_STRUCTURED_EXTRACTION",
                "USE_OPENAI_FOR_ENTITY_EXTRACTION", 
                "USE_OPENAI_FOR_AUDIO_TRANSCRIPTION"]:
        os.environ.pop(key, None)
    
    os.environ["DEPLOYMENT_STAGE"] = stage
    reset_stage_config()