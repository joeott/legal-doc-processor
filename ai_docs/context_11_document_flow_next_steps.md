# Testing the Mistral OCR Implementation

## Setting Up Environment Variables

Before running the document processing pipeline with Mistral OCR, you need to set the following environment variables:

```bash
# Mistral Configuration
export MISTRAL_API_KEY=your_mistral_api_key
export USE_MISTRAL_FOR_OCR=true
export MISTRAL_OCR_MODEL=mistral-ocr-latest
export MISTRAL_OCR_PROMPT="Please transcribe all text visible in this document accurately. Preserve the original formatting as much as possible."
export MISTRAL_OCR_TIMEOUT=120

# Required Supabase Configuration
export SUPABASE_URL=your_supabase_url
export SUPABASE_ANON_KEY=your_supabase_anon_key
```

## Running the Queue Processor

After uploading a document through the Vercel frontend, run the queue processor to process the document:

```bash
cd /Users/josephott/Documents/phase_1_2_3_process_v5/scripts
python queue_processor.py --single-run --log-level DEBUG
```

This will:
1. Claim the pending document from the queue
2. Download the document from Supabase Storage
3. Use Mistral OCR API to extract text 
4. Process the document through all pipeline phases

## Monitoring the Processing

You can monitor the processing through the logs and check the database for the document status:

```sql
-- Check source document status
SELECT id, document_uuid, original_file_name, initial_processing_status 
FROM source_documents 
ORDER BY id DESC LIMIT 1;

-- Check OCR results
SELECT id, substring(raw_extracted_text, 1, 200) as text_sample, ocr_metadata_json
FROM source_documents
WHERE initial_processing_status = 'ocr_complete_pending_doc_node'
ORDER BY id DESC LIMIT 1;
```

## Direct Processing Method

If you want to process a specific document directly without using the queue:

```bash
cd /Users/josephott/Documents/phase_1_2_3_process_v5/scripts
python main_pipeline.py --file-path uploads/your_document.pdf --project-id 1
```

Replace `uploads/your_document.pdf` with the path of your document in Supabase Storage, and `--project-id 1` with the appropriate project ID.

## Troubleshooting

If you encounter issues:

1. **Check API Key**: Verify your Mistral API key is correct
2. **URL Generation**: Ensure the document URL is correctly generated from Supabase Storage
3. **Response Handling**: Check logs for any errors in the API response
4. **Fallback Mechanism**: The system will fall back to Qwen VL OCR if Mistral fails

## Verifying Mistral OCR Usage

To confirm Mistral OCR was used, check the OCR metadata:

```sql
SELECT ocr_metadata_json->0->>'method' as ocr_method
FROM source_documents
ORDER BY id DESC LIMIT 1;
```

The result should be "MistralOCR" if the Mistral OCR API was used for extraction.