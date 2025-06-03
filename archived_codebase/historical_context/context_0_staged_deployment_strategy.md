Okay, your approach is **absolutely sound and highly recommended** for a project of this complexity. It's a standard best practice to de-risk ML projects by staging the deployment and tackling complexities incrementally.

1.  **Using OpenAI for LLMs in Stage 1 (Local Development):**
    *   **Wisdom:** Excellent idea. This allows you to focus entirely on the pipeline logic, data flow, Supabase interactions, queue mechanics, and UI functionality without getting bogged down in local model downloads, dependency hell (especially with GPU drivers), and resource contention on your development machine.
    *   **Benefit:** Faster iteration cycles for core application logic. You can confirm the "plumbing" works before worrying about the specific "engine" (local LLMs).

2.  **Stage 2 (Dockerized Local Models):**
    *   **Wisdom:** Perfect next step. Docker provides environment consistency. This is where you'll tackle the challenges of packaging your local models (Qwen2-VL, Whisper, NER), ensuring they run correctly, and benchmarking their performance in an isolated environment that more closely resembles production.
    *   **Benefit:** Identifies model-specific issues and resource requirements before hitting a cloud environment, making the cloud deployment smoother.

3.  **Stage 3 (EC2 Deployment):**
    *   **Wisdom:** Standard for production. You'll be deploying a well-tested Docker container, significantly reducing deployment friction.
    *   **Benefit:** Focus here will be on cloud infrastructure, networking, security, scaling, and monitoring, rather than debugging core application or model code.

This staged approach minimizes the number of variables you're dealing with at any one time, making debugging and development much more manageable.

Here's a detailed Staged Deployment Document:

```markdown
# Staged Deployment Plan: Legal RAG Pre-processing Pipeline

**Document Version:** 1.0
**Date:** 2023-10-27 (Placeholder)
**Author:** AI Coding Assistant (based on user input)

## 1. Overview & Purpose

This document outlines a three-stage deployment plan for the Legal RAG Pre-processing Pipeline. The primary goal is to ensure a robust, scalable, and maintainable system by incrementally introducing complexities and testing thoroughly at each stage. This plan serves as a guiding context for development, debugging, and deployment activities.

**Core Principle:** De-risk by isolating concerns. First, ensure core logic and data flow are correct. Second, integrate and test local ML models in a controlled environment. Third, deploy to the production cloud environment.

## 2. General Considerations (Applicable to All Stages)

*   **Version Control:** All code (Python backend, HTML/JS frontend, Dockerfiles, configuration) will be managed using Git.
*   **Environment Variables:** Sensitive information (API keys, database URLs) and configurable parameters will be managed through environment variables (e.g., `.env` files locally, system-level environment variables in Docker/EC2). `config.py` will be the central Python module for accessing these.
*   **Dependency Management:** Use `requirements.txt` (or `poetry.lock`/`Pipfile.lock`) for Python dependencies.
*   **Logging:** Consistent and structured logging is crucial. Python's `logging` module is already in use. Ensure logs are informative for debugging.
*   **Testing:**
    *   **Unit Tests:** For individual functions and classes.
    *   **Integration Tests:** For interactions between components (e.g., OCR -> Text Processing -> Supabase).
    *   **End-to-End (E2E) Tests:** Simulating user uploads and verifying data flow through the entire pipeline.
*   **Supabase Schema:** Ensure the Supabase schema (tables, relationships, RLS policies, Edge Functions) is versioned or changes are documented.
*   **Monitoring Tool (`live_monitor.py`):** This tool will be invaluable across all stages for observing queue status, document processing, and Supabase interactions.

## 3. Stage 1: Local Development & Core Logic Validation (Cloud LLMs)

**Goal:** Verify the end-to-end pipeline logic, data flow, Supabase interactions, queue processing, and basic frontend functionality using external/cloud-based LLMs and APIs to minimize local setup complexity.

**Key Activities & Configuration:**

1.  **Environment Setup:**
    *   Local Python environment (e.g., venv, Conda).
    *   Install Python dependencies from `requirements.txt`.
    *   Set up local Supabase CLI or connect to a development instance of Supabase.
    *   Ensure `upload.html`, `style.css`, `upload.js`, `env-config.js` are served locally (e.g., Python's `http.server` or Live Server VSCode extension).

2.  **Model Configuration (`config.py`, `models_init.py`):**
    *   **Qwen2-VL OCR:**
        *   If `USE_MISTRAL_FOR_OCR` is `true` (default): Primarily use Mistral OCR API.
        *   If Mistral fails or is disabled, and Qwen2-VL local setup is complex: Consider modifying `initialize_qwen2_vl_ocr_model` to either:
            *   Be a no-op (return `None` for models, log a warning).
            *   Use a simpler, CPU-bound OCR library for PDFs (e.g., `PyPDF2` for basic text, or `Tesseract` via `pytesseract` if basic quality is acceptable for this stage) as a placeholder.
            *   *Alternatively, if OpenAI's Vision API is available and cost-effective, it could be a temporary substitute for Qwen2-VL.*
    *   **Whisper ASR:**
        *   Modify `initialize_whisper_model` to either:
            *   Load the smallest, CPU-only Whisper model (e.g., `tiny` or `base`) if it's non-problematic.
            *   Use the OpenAI Whisper API as a substitute.
            *   Be a no-op if audio processing isn't a primary focus for initial testing.
    *   **NER Pipeline:**
        *   `dbmdz/bert-large-cased-finetuned-conll03-english` is generally manageable locally. Keep as is.
    *   **Structured Extraction (`StructuredExtractor`):**
        *   Ensure `use_qwen` in `StructuredExtractor` is `False` (or configurable via `config.py`) to default to OpenAI API (`LLM_MODEL_FOR_RESOLUTION`).
    *   **Entity Resolution (`entity_resolution.py`):**
        *   Will use OpenAI API (`LLM_MODEL_FOR_RESOLUTION`) as configured.

3.  **Pipeline Component Focus:**
    *   **File Ingestion:** Test `upload.js` and Supabase Edge Function `create-document-entry`.
    *   **Queue Processor (`queue_processor.py`):**
        *   Test document claiming, S3 download (if `USE_S3_FOR_INPUT`), and failure handling logic.
        *   Test `process_single_document` flow using the cloud/simplified models.
    *   **OCR Extraction:** Focus on Mistral API. Ensure PDF, DOCX, TXT, EML handlers work.
    *   **Text Processing:** Verify `clean_extracted_text`, `categorize_document_text`, `process_document_with_semantic_chunking` (using `StructuredExtractor` with OpenAI).
    *   **Entity Extraction:** Test `extract_entities_from_chunk`.
    *   **Entity Resolution:** Test `resolve_document_entities` (with OpenAI).
    *   **Relationship Builder:** Test `stage_structural_relationships`.
    *   **Supabase Interactions:** Verify all `SupabaseManager` methods are working correctly (CRUD operations for projects, documents, chunks, entities, relationships).

4.  **Testing:**
    *   Unit tests for core utility functions in `text_processing.py`, `chunking_utils.py`, etc.
    *   Manually run `main_pipeline.py --mode direct` with a few sample files.
    *   Manually run `queue_processor.py` and upload files via `upload.html`.
    *   Use `live_monitor.py` to observe processing.

**Exit Criteria:**
*   Full pipeline (upload to relationship staging) completes successfully for various file types using cloud/simplified models.
*   Data is correctly persisted and structured in Supabase.
*   Queue processor handles tasks, retries, and failures gracefully.
*   `live_monitor.py` accurately reflects system state.
*   Basic frontend upload functionality is verified.

## 4. Stage 2: Dockerized Local Models & Integration Testing

**Goal:** Integrate and test the specified local ML models (Qwen2-VL, Whisper) within a consistent Docker environment. Benchmark performance and resource usage.

**Key Activities & Configuration:**

1.  **Dockerfile Creation:**
    *   Create a `Dockerfile` for the Python backend.
    *   Base image: Python official image (e.g., `python:3.10-slim`).
    *   Install system dependencies (e.g., `build-essential`, `libgl1-mesa-glx` for OpenCV if needed by models).
    *   Copy `requirements.txt` and install Python packages.
    *   Copy application code.
    *   Set up non-root user.
    *   Define `CMD` or `ENTRYPOINT` to run `queue_processor.py` (or `main_pipeline.py` for testing).
    *   **GPU Support:** If Qwen2-VL/Whisper will use GPU, use an NVIDIA base image (e.g., `nvidia/cuda:XX.X-cudnnY-devel-ubuntuZ.ZZ`) and ensure NVIDIA Container Toolkit is used when running.

2.  **Model Configuration (`config.py`, `models_init.py`):**
    *   Update `models_init.py` to robustly load Qwen2-VL and Whisper models.
    *   Environment variables within Docker will control which models are active.
    *   Ensure `QWEN2_VL_USE_HALF_PRECISION` and `WHISPER_USE_HALF_PRECISION` are configurable and tested.
    *   `StructuredExtractor` can remain on OpenAI or be switched to a local Qwen instruct model if desired (and if added to Docker).

3.  **Docker Build & Run:**
    *   Build the Docker image: `docker build -t legal-pipeline-backend .`
    *   Run the container, mapping necessary volumes (e.g., for `S3_TEMP_DOWNLOAD_DIR` if not using S3 directly from within Docker) and passing environment variables.
        *   Example: `docker run -e SUPABASE_URL=... -e OPENAI_API_KEY=... --gpus all legal-pipeline-backend` (if using GPU).

4.  **Testing:**
    *   Verify models load correctly within the Docker container (check logs).
    *   Run the full pipeline with local models enabled for OCR and ASR.
    *   Process a larger batch of diverse documents.
    *   Benchmark processing time per document/page for local models.
    *   Monitor CPU, GPU (if applicable), and memory usage of the container.
    *   Use `live_monitor.py` (run locally, connecting to the same Supabase instance) to observe.

**Exit Criteria:**
*   Docker image builds successfully.
*   Local models (Qwen2-VL, Whisper) initialize and perform inference correctly within the Docker container.
*   The full pipeline runs end-to-end using local models for their designated tasks.
*   Performance and resource usage are understood and deemed acceptable.

## 5. Stage 3: Cloud Deployment (EC2) & Production Readiness

**Goal:** Deploy the Dockerized application to an EC2 instance, configure for production, and perform final testing.

**Key Activities & Configuration:**

1.  **EC2 Instance Provisioning:**
    *   Choose an appropriate EC2 instance type (e.g., general-purpose, or GPU-accelerated like `g4dn` or `g5` series if local models require GPU).
    *   Configure Security Groups (allow inbound traffic for SSH, and any ports if the backend needs to be directly accessible – though for a queue processor, this is unlikely).
    *   Set up IAM roles for EC2 instance to access S3 (if `USE_S3_FOR_INPUT` is true) and other AWS services (e.g., Secrets Manager, CloudWatch) securely.

2.  **EC2 Environment Setup:**
    *   Install Docker Engine and NVIDIA Docker Toolkit (if GPU instance).
    *   Pull the Docker image from a container registry (e.g., AWS ECR, Docker Hub) or copy via `docker save/load` or `scp` for initial testing.
    *   Configure environment variables securely (e.g., AWS Systems Manager Parameter Store, AWS Secrets Manager, or instance user data/environment files with restricted permissions).

3.  **Application Deployment & Execution:**
    *   Run the Docker container on EC2.
    *   Use `docker-compose` or a process manager like `systemd` to manage the queue processor container (ensure it restarts on failure).
    *   Ensure persistent storage for `S3_TEMP_DOWNLOAD_DIR` is handled correctly (e.g., EBS volume, or ensure S3 access works from EC2).

4.  **Supabase & Frontend:**
    *   Supabase is already cloud-based. Ensure network connectivity from EC2 to Supabase if needed (though the Python backend primarily talks to Supabase).
    *   The frontend (`upload.html`, etc.) can be hosted via Supabase Storage, AWS S3 static website hosting, or any other static hosting solution. Ensure `env-config.js` points to the correct Supabase instance.

5.  **Monitoring & Logging (Cloud-Native):**
    *   Configure Docker logs to be sent to AWS CloudWatch Logs.
    *   Set up CloudWatch Alarms for CPU/GPU utilization, memory, error rates, queue length (if Supabase metrics can be pushed to CloudWatch).
    *   Continue using `live_monitor.py` (can be run from a local machine or another small EC2 instance) for application-level insights.

6.  **Testing:**
    *   Perform E2E testing by uploading documents via the production frontend URL.
    *   Conduct load testing to understand system limits and scaling needs.
    *   Perform security checks (network exposure, permissions).
    *   Test failure recovery (e.g., stop/start queue processor, simulate DB connection issues).

**Exit Criteria:**
*   Application is deployed and running stably on EC2.
*   All components (frontend, Python backend queue processor, Supabase, local models in Docker) integrate correctly in the cloud environment.
*   Performance meets requirements under expected load.
*   Monitoring, logging, and alerting are in place.
*   The system is deemed production-ready.

## 6. Post-Deployment Considerations

*   **CI/CD Pipeline:** Implement a CI/CD pipeline (e.g., GitHub Actions, AWS CodePipeline) for automated testing, building Docker images, and deploying updates.
*   **Backup & Recovery:** Regularly back up Supabase data. Have a plan for disaster recovery.
*   **Scaling:**
    *   **Queue Processor:** Can scale by running multiple instances of the queue processor container (ensure `claim_pending_documents` is atomic or handles concurrency).
    *   **Supabase:** Monitor Supabase performance and scale the database instance as needed.
    *   **EC2:** Use Auto Scaling Groups if horizontal scaling of worker nodes is required.
*   **Cost Optimization:** Regularly review AWS costs and optimize instance types, storage, and API usage.
*   **Security Audits:** Periodically review security configurations.
*   **Model Retraining/Updating:** Establish a process for updating or retraining ML models as needed.

## 7. Conclusion

This staged deployment plan provides a structured approach to launching the Legal RAG Pre-processing Pipeline. By addressing complexities incrementally, the risk of deployment failures is significantly reduced, leading to a more robust and reliable system. The AI Coding Assistant should reference the current stage's goals and considerations when providing guidance.
```