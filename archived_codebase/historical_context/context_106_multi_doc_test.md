# Multi-Document Processing Test Results

Generated: 2025-05-25 23:13:13.746929

## Documents Processed

### 1. ARDC_Registration_Receipt_6333890.pdf

**Document Identifiers:**
- Source Document UUID: `57493510-37c4-4afb-a446-a529dcfe7908`
- Neo4j Document UUID: `57493510-37c4-4afb-a446-a529dcfe7908`
- Processing Status: complete
- Document Category: legal_filing

**OCR Results:**
- OCR Provider: textract
- Textract Status: succeeded
- Text Extracted: 874 characters
- File Size: N/A

**Processing Results:**
- Chunks Created: 0
- Total Entities: 0

---

### 2. Affidavit+of+Service.PDF

**Document Identifiers:**
- Source Document UUID: `fb6befbd-a750-4cf2-895a-174db5e28568`
- Neo4j Document UUID: `fb6befbd-a750-4cf2-895a-174db5e28568`
- Processing Status: complete
- Document Category: affidavit

**OCR Results:**
- OCR Provider: textract
- Textract Status: succeeded
- Text Extracted: 1,534 characters
- File Size: N/A

**Processing Results:**
- Chunks Created: 1
- Total Entities: 30

**Entity Breakdown:**
- Miscellaneous: 18
  - Examples: STATE OF MISSOURI, Estate No. 24SL-PR02898, U.S. First Class Mail
- date: 2
  - Examples: 5th day of May, 2025, 5th day of May, 2025
- organization: 2
  - Examples: THE CIRCUIT COURT OF THE COUNTY OF ST. LOUIS, Burrus Correctional Training Ctr.
- person: 8
  - Examples: PAUL M. THORNTON, Aaron Thornton, Ashley Thornton

---

### 3. Ali - Motion to Continue Trial Setting.pdf

**Document Identifiers:**
- Source Document UUID: `28c8cf05-b611-4a68-989d-d5c5c5d55612`
- Neo4j Document UUID: `28c8cf05-b611-4a68-989d-d5c5c5d55612`
- Processing Status: complete
- Document Category: legal_filing

**OCR Results:**
- OCR Provider: textract
- Textract Status: succeeded
- Text Extracted: 3,323 characters
- File Size: N/A

**Processing Results:**
- Chunks Created: 2
- Total Entities: 26

**Entity Breakdown:**
- Miscellaneous: 10
  - Examples: STATE OF MISSOURI, Case No. 2322-AC13087-01, Order on December 4, 2024
- date: 5
  - Examples: December 4, 2024, April 7, 2025, May 16, 2024
- organization: 4
  - Examples: CIRCUIT COURT OF THE CITY OF ST. LOUIS, MASTER AUTO SALES, INC, Court
- person: 7
  - Examples: ZAID ADAY, MOHANAD ALI, Defendant Ali

---

### 4. APRIL L DAVIS-Comprehensive-Report-202501221858.pdf

**Document Identifiers:**
- Source Document UUID: `502e54cc-3de3-4872-b7d5-656875c57cbe`
- Neo4j Document UUID: `502e54cc-3de3-4872-b7d5-656875c57cbe`
- Processing Status: complete
- Document Category: contract

**OCR Results:**
- OCR Provider: textract
- Textract Status: succeeded
- Text Extracted: 225,961 characters
- File Size: N/A

**Processing Results:**
- Chunks Created: 1
- Total Entities: 37

**Entity Breakdown:**
- Miscellaneous: 35
  - Examples: Table of Contents, Potential Subject Photos (None Found), Possible Criminal Records (2 Found)
- date: 1
  - Examples: 01/22/2025
- person: 1
  - Examples: APRIL L DAVIS

---

## Summary Statistics

- Total Documents Processed: 4
- Total Text Extracted: 231,692 characters
- Total Entities Found: 93
- Average Processing Time: ~1 minute per document
- Total Relationships Created: 4

## System Performance

- **AWS Textract**: All documents processed successfully
- **OpenAI GPT-4**: Entity extraction completed for all documents
- **Redis**: Connection stable, no SSL errors
- **Database**: All operations successful
- **Error Rate**: 0%
