Stage 1 Modifications: Prioritizing OpenAI, Bypassing/Simplifying Local Models
The goal here is to make the pipeline run end-to-end using OpenAI for all significant LLM/Vision-LLM tasks, and either skipping or simplifying the local model steps to avoid heavy local resource usage and setup headaches.
Files and Specific Sections to Modify:
config.py:
Action: Introduce a new configuration flag to explicitly manage this stage.
Add:
# config.py
# ...
# Stage Management
PROCESSING_STAGE = os.getenv("PROCESSING_STAGE", "stage1") # 'stage1', 'stage2', 'stage3'
# This flag will make it explicit to use OpenAI for heavy lifting in Stage 1
FORCE_CLOUD_LLMS_FOR_STAGE1 = os.getenv("FORCE_CLOUD_LLMS_FOR_STAGE1", "true").lower() in ("true", "1", "yes")
Use code with caution.
Python
Ensure USE_MISTRAL_FOR_OCR is true and MISTRAL_API_KEY is set for Stage 1 PDF OCR.
Ensure OPENAI_API_KEY is set.
models_init.py:
initialize_qwen2_vl_ocr_model(device: str):
Action: Modify this function to bypass loading the local Qwen2-VL model if FORCE_CLOUD_LLMS_FOR_STAGE1 is true or PROCESSING_STAGE == 'stage1'.
Change (conceptual):
# models_init.py
from config import FORCE_CLOUD_LLMS_FOR_STAGE1 # Add this import

def initialize_qwen2_vl_ocr_model(device: str) -> None:
    global QWEN2_VL_OCR_MODEL, QWEN2_VL_OCR_PROCESSOR, QWEN2_VL_OCR_DEVICE, PROCESS_VISION_INFO_FN
    
    # Check if we should bypass local model loading
    if FORCE_CLOUD_LLMS_FOR_STAGE1: # Or check PROCESSING_STAGE
        logger.info("FORCE_CLOUD_LLMS_FOR_STAGE1 is true. Bypassing local Qwen2-VL-OCR model initialization.")
        QWEN2_VL_OCR_MODEL = None
        QWEN2_VL_OCR_PROCESSOR = None
        PROCESS_VISION_INFO_FN = None
        # QWEN2_VL_OCR_DEVICE can be left as is or set to None.
        return

    if QWEN2_VL_OCR_MODEL is not None:
        logger.info("Qwen2-VL-OCR model already initialized, skipping.")
        return
    
    # ... (rest of the original loading code) ...
Use code with caution.
Python
initialize_whisper_model(device: str):
Action: Modify similarly to bypass loading the local Whisper model for Stage 1.
Change (conceptual):
# models_init.py
# from config import FORCE_CLOUD_LLMS_FOR_STAGE1 (if not already imported)

def initialize_whisper_model(device: str) -> None:
    global WHISPER_MODEL
    
    if FORCE_CLOUD_LLMS_FOR_STAGE1: # Or check PROCESSING_STAGE
        logger.info("FORCE_CLOUD_LLMS_FOR_STAGE1 is true. Bypassing local Whisper model initialization.")
        WHISPER_MODEL = None
        return

    if WHISPER_MODEL is not None:
        logger.info("Whisper model already initialized, skipping.")
        return
    
    # ... (rest of the original loading code) ...
Use code with caution.
Python
initialize_ner_pipeline(...):
The default dbmdz/bert-large-cased-finetuned-conll03-english is a traditional transformer model, not a large generative LLM. It's usually manageable to run locally.
Action: For Stage 1, this can likely remain as is. If it causes issues, you could modify it to use an LLM for NER (via OpenAI) or a simpler regex-based placeholder for Stage 1. For now, assume it's okay.
ocr_extraction.py:
extract_text_from_pdf_qwen_vl_ocr(pdf_path: str):
Action: This function needs to gracefully handle the case where the Qwen2-VL model components are None (because they were bypassed in models_init.py).
Change: At the beginning of the function:
# ocr_extraction.py
# ...
def extract_text_from_pdf_qwen_vl_ocr(pdf_path: str) -> tuple[str | None, list | None]:
    qwen_model = get_qwen2_vl_ocr_model()
    qwen_processor = get_qwen2_vl_ocr_processor()
    qwen_vision_fn = get_process_vision_info()

    if not all([qwen_model, qwen_processor, qwen_vision_fn]):
        logger.info("Qwen2-VL-OCR components not available (likely bypassed for Stage 1). Cannot process PDF with local Qwen-VL.")
        return None, None
    
    # ... (rest of the original function) ...
Use code with caution.
Python
transcribe_audio_whisper(audio_path: str):
Action: Handle the case where the local Whisper model is None. Consider adding an OpenAI Whisper API call here for Stage 1 functionality.
Change:
# ocr_extraction.py
from models_init import get_whisper_model # Ensure using accessor
from config import OPENAI_API_KEY, FORCE_CLOUD_LLMS_FOR_STAGE1 # Add imports
import openai # Add import

def transcribe_audio_whisper(audio_path: str) -> str | None:
    local_whisper_model = get_whisper_model() # Use accessor

    if FORCE_CLOUD_LLMS_FOR_STAGE1 or not local_whisper_model:
        logger.info("Bypassing local Whisper model. Attempting OpenAI Whisper API.")
        if not OPENAI_API_KEY:
            logger.warning("OPENAI_API_KEY not set. Cannot use OpenAI Whisper API.")
            return None
        try:
            openai.api_key = OPENAI_API_KEY
            with open(audio_path, "rb") as audio_file_obj:
                transcript = openai.Audio.transcribe("whisper-1", audio_file_obj)
            return transcript['text'].strip()
        except Exception as e_openai:
            logger.error(f"OpenAI Whisper API transcription failed for {audio_path}: {e_openai}")
            return None
    
    # Original local Whisper model logic (if local_whisper_model is available and FORCE_CLOUD_LLMS_FOR_STAGE1 is false)
    logger.info(f"Using local Whisper model for {audio_path}")
    try:
        # Ensure fp16 is False if on CPU
        use_fp16 = False
        if hasattr(local_whisper_model, 'device') and local_whisper_model.device.type == 'cuda':
            use_fp16 = True

        result = local_whisper_model.transcribe(audio_path, fp16=use_fp16)
        return result["text"].strip()
    except Exception as e:
        logger.error(f"Error transcribing audio {audio_path} with local Whisper: {e}")
        return None
Use code with caution.
Python
main_pipeline.py (process_single_document):
Action: The existing logic for OCR (Mistral primary, Qwen fallback) should work well. If extract_text_from_pdf_qwen_vl_ocr returns None (because the model was bypassed), raw_text will remain None (if Mistral also failed or was skipped), and the pipeline will correctly handle this as an extraction failure.
The audio transcription part will now use the modified transcribe_audio_whisper, which falls back to OpenAI API in Stage 1.
structured_extraction.py (StructuredExtractor):
Action: This class already defaults to using OpenAI if use_qwen=False is passed during instantiation or if the Qwen local model fails to load.
In text_processing.py, process_document_with_semantic_chunking instantiates StructuredExtractor() without arguments, so it correctly defaults to OpenAI.
No change needed for Stage 1 here, as it's already OpenAI-first by default. If you wanted to use a local Qwen-Instruct model here later, you'd pass use_qwen=True and ensure that model is loaded.
entity_extraction.py (extract_entities_from_chunk):
Action: This uses NER_PIPELINE (BERT-based). As discussed, this is likely fine for Stage 1.
If you wanted to use OpenAI for NER in Stage 1, you'd modify this function to call the OpenAI Completions API with a suitable NER prompt instead of NER_PIPELINE(chunk_text). This is a more significant change and might not be necessary if the BERT model is acceptable.
entity_resolution.py (resolve_document_entities):
Action: This function is already designed to use LLM_MODEL_FOR_RESOLUTION (OpenAI).
No change needed for Stage 1.
Summary of Stage 1 State:
PDF OCR primarily uses Mistral API. If it fails, Qwen-VL local model path is skipped gracefully.
Audio Transcription uses OpenAI Whisper API. Local Whisper model path is skipped.
NER uses local BERT model (likely acceptable).
Structured Extraction and Entity Resolution use OpenAI.