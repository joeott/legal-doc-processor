# models_init.py
"""
Model initialization and accessor module for various AI/ML models
used throughout the processing pipeline.

This module handles the loading, initialization, and access to:
1. Qwen2-VL-OCR model for OCR processing
2. Whisper model for audio transcription
3. Other models as needed

Models are initialized on-demand and stored as module-level variables
to avoid reloading models for each file being processed.
"""

import os
import logging
import torch
from typing import Tuple, Any, Optional, Dict, List, Union

# Configure logging
logger = logging.getLogger(__name__)

# Import stage management configuration
from scripts.config import DEPLOYMENT_STAGE, BYPASS_LOCAL_MODELS, FORCE_CLOUD_LLMS, STAGE_CLOUD_ONLY

# Global model instances - initialized on first use
QWEN2_VL_OCR_MODEL = None
QWEN2_VL_OCR_PROCESSOR = None
QWEN2_VL_OCR_DEVICE = None
WHISPER_MODEL = None
PROCESS_VISION_INFO_FN = None
NER_PIPELINE = None

# ------------------ Model Configuration Constants ------------------
# Qwen2-VL OCR settings
QWEN2_VL_OCR_MODEL_ID = os.getenv("QWEN2_VL_OCR_MODEL_ID", "Qwen/Qwen2-VL-7B")
QWEN2_VL_OCR_PROMPT = os.getenv("QWEN2_VL_OCR_PROMPT", "Extract all text visible in this image. Maintain paragraph structure and layout. Include all text.")
QWEN2_VL_OCR_MAX_NEW_TOKENS = int(os.getenv("QWEN2_VL_OCR_MAX_NEW_TOKENS", "1024"))
QWEN2_VL_USE_HALF_PRECISION = os.getenv("QWEN2_VL_USE_HALF_PRECISION", "true").lower() in ("true", "1", "yes")

# Whisper settings
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")
WHISPER_USE_HALF_PRECISION = os.getenv("WHISPER_USE_HALF_PRECISION", "true").lower() in ("true", "1", "yes")

# ------------------ Stage Management Functions ------------------

def should_load_local_models() -> bool:
    """Determine if local models should be loaded based on deployment stage."""
    if DEPLOYMENT_STAGE == STAGE_CLOUD_ONLY:
        logger.debug(f"Stage {DEPLOYMENT_STAGE}: Cloud-only mode, bypassing local models")
        return False
    return not BYPASS_LOCAL_MODELS

def validate_cloud_api_keys():
    """Validate required API keys for cloud services."""
    from scripts.config import OPENAI_API_KEY, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY required for cloud deployment")
    if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
        raise ValueError("AWS credentials required for Textract OCR")
    logger.info("Cloud API keys validated successfully")

# ------------------ Model Initialization Functions ------------------

def initialize_all_models() -> None:
    """
    Stage-aware model initialization function.
    This function is called once at the start of the processing pipeline.
    """
    logger.info(f"Initializing models for Stage {DEPLOYMENT_STAGE}...")
    
    if DEPLOYMENT_STAGE == STAGE_CLOUD_ONLY:
        logger.info("Stage 1: Cloud-only deployment - skipping all local model initialization")
        # Initialize only cloud service configurations
        validate_cloud_api_keys()
        return
    
    # For stages 2 and 3, initialize local models
    logger.info(f"Stage {DEPLOYMENT_STAGE}: Initializing local models")
    
    # Check for GPU availability
    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info(f"Using device: {device} for model inference")
    
    # Initialize Qwen2-VL OCR model
    initialize_qwen2_vl_ocr_model(device)
    
    # Initialize Whisper model
    initialize_whisper_model(device)
    
    # Initialize NER pipeline
    from scripts.config import NER_GENERAL_MODEL
    initialize_ner_pipeline(NER_GENERAL_MODEL, device)
    
    logger.info("All models initialized successfully")


def initialize_qwen2_vl_ocr_model(device: str) -> None:
    """
    Initialize the Qwen2-VL-OCR model and processor.
    
    Args:
        device: The device to place the model on ('cuda' or 'cpu')
    """
    global QWEN2_VL_OCR_MODEL, QWEN2_VL_OCR_PROCESSOR, QWEN2_VL_OCR_DEVICE, PROCESS_VISION_INFO_FN
    
    if not should_load_local_models():
        logger.info(f"Stage {DEPLOYMENT_STAGE}: Bypassing local Qwen2-VL-OCR model initialization.")
        QWEN2_VL_OCR_MODEL = None
        QWEN2_VL_OCR_PROCESSOR = None
        PROCESS_VISION_INFO_FN = None
        QWEN2_VL_OCR_DEVICE = None
        return
    
    if QWEN2_VL_OCR_MODEL is not None:
        logger.info("Qwen2-VL-OCR model already initialized, skipping.")
        return
    
    try:
        logger.info(f"Initializing Qwen2-VL-OCR model: {QWEN2_VL_OCR_MODEL_ID}")
        
        # Import transformers and other required libraries
        from transformers import AutoModelForCausalLM, AutoProcessor
        
        # Set device
        QWEN2_VL_OCR_DEVICE = device
        
        # Load processor first
        logger.info("Loading Qwen2-VL-OCR processor...")
        QWEN2_VL_OCR_PROCESSOR = AutoProcessor.from_pretrained(QWEN2_VL_OCR_MODEL_ID)
        
        # Load model with appropriate settings
        logger.info(f"Loading Qwen2-VL-OCR model on {device}...")
        model_kwargs = {
            "device_map": "auto" if device == "cuda" else None,
            "torch_dtype": torch.float16 if QWEN2_VL_USE_HALF_PRECISION and device == "cuda" else torch.float32,
            "trust_remote_code": True,  # Required for Qwen models
        }
        
        QWEN2_VL_OCR_MODEL = AutoModelForCausalLM.from_pretrained(
            QWEN2_VL_OCR_MODEL_ID,
            **model_kwargs
        )
        
        # Import and set up vision processing function
        try:
            # Try to import the relevant image processing function
            # This is model-specific and might be in different locations
            logger.info("Setting up vision processing function...")
            
            # First attempt - try from transformers
            try:
                from transformers.models.qwen2_vl.processing_qwen2_vl import process_vision_info
                PROCESS_VISION_INFO_FN = process_vision_info
                logger.info("Using process_vision_info from transformers")
            except ImportError:
                # Second attempt - try from model's specific module
                try:
                    from qwen_vl_utils import process_vision_info
                    PROCESS_VISION_INFO_FN = process_vision_info
                    logger.info("Using process_vision_info from qwen_vl_utils")
                except ImportError:
                    logger.warning("Could not import process_vision_info function. Vision processing may fail.")
        except Exception as e:
            logger.error(f"Error setting up vision processing function: {e}")
        
        logger.info("Qwen2-VL-OCR model initialized successfully")
        
    except Exception as e:
        logger.error(f"Error initializing Qwen2-VL-OCR model: {e}", exc_info=True)
        QWEN2_VL_OCR_MODEL = None
        QWEN2_VL_OCR_PROCESSOR = None


def initialize_whisper_model(device: str) -> None:
    """
    Initialize the Whisper model for audio transcription.
    
    Args:
        device: The device to place the model on ('cuda' or 'cpu')
    """
    global WHISPER_MODEL
    
    if not should_load_local_models():
        logger.info(f"Stage {DEPLOYMENT_STAGE}: Bypassing local Whisper model initialization.")
        WHISPER_MODEL = None
        return
    
    if WHISPER_MODEL is not None:
        logger.info("Whisper model already initialized, skipping.")
        return
    
    try:
        logger.info(f"Initializing Whisper model (size: {WHISPER_MODEL_SIZE})")
        
        # Import whisper
        import whisper
        
        # Configure model loading based on device and precision
        kwargs = {}
        if device == "cuda":
            kwargs["device"] = device
            if WHISPER_USE_HALF_PRECISION:
                kwargs["fp16"] = True
        
        # Load the model
        WHISPER_MODEL = whisper.load_model(WHISPER_MODEL_SIZE, **kwargs)
        logger.info(f"Whisper model initialized successfully on {device}")
        
    except Exception as e:
        logger.error(f"Error initializing Whisper model: {e}", exc_info=True)
        WHISPER_MODEL = None


# ------------------ Model Accessor Functions ------------------

def get_qwen2_vl_ocr_model():
    """Get the Qwen2-VL-OCR model instance, initializing if necessary."""
    global QWEN2_VL_OCR_MODEL
    if QWEN2_VL_OCR_MODEL is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        initialize_qwen2_vl_ocr_model(device)
    return QWEN2_VL_OCR_MODEL


def get_qwen2_vl_ocr_processor():
    """Get the Qwen2-VL-OCR processor instance, initializing if necessary."""
    global QWEN2_VL_OCR_PROCESSOR
    if QWEN2_VL_OCR_PROCESSOR is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        initialize_qwen2_vl_ocr_model(device)
    return QWEN2_VL_OCR_PROCESSOR


def get_qwen2_vl_ocr_device():
    """Get the device used for Qwen2-VL-OCR model."""
    global QWEN2_VL_OCR_DEVICE
    if QWEN2_VL_OCR_DEVICE is None:
        QWEN2_VL_OCR_DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    return QWEN2_VL_OCR_DEVICE


def get_process_vision_info():
    """Get the process_vision_info function for image processing."""
    global PROCESS_VISION_INFO_FN
    if PROCESS_VISION_INFO_FN is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        initialize_qwen2_vl_ocr_model(device)
    return PROCESS_VISION_INFO_FN


def get_whisper_model():
    """Get the Whisper model instance, initializing if necessary."""
    global WHISPER_MODEL
    if WHISPER_MODEL is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        initialize_whisper_model(device)
    return WHISPER_MODEL

def initialize_ner_pipeline(model_name: str = "dbmdz/bert-large-cased-finetuned-conll03-english", device: str = None):
    """Initialize the NER pipeline."""
    global NER_PIPELINE
    
    if not should_load_local_models():
        logger.info(f"Stage {DEPLOYMENT_STAGE}: Bypassing local NER pipeline initialization.")
        NER_PIPELINE = None
        return
    
    try:
        from transformers import pipeline
        logger.info(f"Initializing NER pipeline with model: {model_name}")
        # Use device if provided
        device_num = 0 if device == "cuda" and torch.cuda.is_available() else -1
        NER_PIPELINE = pipeline("ner", model=model_name, tokenizer=model_name, 
                               aggregation_strategy="simple", device=device_num)
        logger.info("NER pipeline initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize NER pipeline: {e}")
        NER_PIPELINE = None

def get_ner_pipeline():
    """Get the NER pipeline instance, initializing if necessary."""
    from scripts.config import NER_GENERAL_MODEL
    global NER_PIPELINE
    if NER_PIPELINE is None:
        initialize_ner_pipeline(NER_GENERAL_MODEL)
    return NER_PIPELINE