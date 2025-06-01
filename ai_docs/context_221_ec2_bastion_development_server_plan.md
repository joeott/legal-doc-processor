# Context 221: EC2 Bastion & Development Server Implementation Plan

## Executive Summary

This plan outlines the implementation of an EC2 instance that serves dual purposes:
1. **Immediate**: Bastion host for secure RDS PostgreSQL access
2. **Stage 2**: Development server for local open-source AI/ML services to replace OpenAI dependencies

## Architecture Overview

```
Internet → EC2 Instance (Public Subnet) → RDS PostgreSQL (Private Subnet)
                    ↓
            Stage 2: Local AI Services
            - Mistral/LLaMA for text generation
            - Sentence Transformers for embeddings
            - Tesseract/EasyOCR for OCR
            - spaCy/Hugging Face for NER
```

## Phase 1: Bastion Host Requirements

### Instance Specifications (Initial)
```yaml
Instance Type: t3.medium (2 vCPU, 4GB RAM)
Storage: 30GB gp3 SSD
OS: Ubuntu 22.04 LTS or Amazon Linux 2023
Network: Same VPC as RDS (vpc-53107829)
Subnet: Public subnet with internet gateway
Security Group: 
  - SSH (22) from your IP
  - PostgreSQL (5432) to RDS security group
  - HTTPS (443) outbound for package downloads
```

### Why These Specs for Bastion
- **t3.medium**: Sufficient for PostgreSQL client tools and development
- **30GB storage**: Room for logs, tools, and temporary files
- **Ubuntu/AL2023**: Modern OS with good package support

## Phase 2: Stage 2 Development Server Requirements

### Upgraded Instance Specifications
```yaml
Instance Type: g4dn.xlarge or p3.2xlarge
  - g4dn.xlarge: 4 vCPU, 16GB RAM, 1x NVIDIA T4 GPU (16GB)
  - p3.2xlarge: 8 vCPU, 61GB RAM, 1x NVIDIA V100 GPU (16GB)
  
Storage: 200GB gp3 SSD (expandable)
OS: Ubuntu 22.04 LTS (better ML/AI support)
Additional Storage: Optional EFS for model storage
```

### Why These Specs for AI/ML
- **GPU Required**: For efficient model inference
- **T4 vs V100**: T4 is more cost-effective for inference, V100 for training
- **16GB+ RAM**: Required for loading large language models
- **200GB storage**: Space for multiple AI models (can be 10-50GB each)

## Instance Setup Plan

### Step 1: Launch EC2 Instance

```bash
# Create key pair
aws ec2 create-key-pair \
    --key-name legal-doc-processor \
    --query 'KeyMaterial' \
    --output text > legal-doc-processor.pem

chmod 400 legal-doc-processor.pem

# Get subnet ID from RDS VPC
aws ec2 describe-subnets \
    --filters "Name=vpc-id,Values=vpc-53107829" \
    --query 'Subnets[?MapPublicIpOnLaunch==`true`].SubnetId' \
    --output table

# Launch instance
aws ec2 run-instances \
    --image-id ami-0c02fb55956c7d316 \  # Ubuntu 22.04 LTS in us-east-1
    --instance-type t3.medium \
    --key-name legal-doc-processor \
    --subnet-id subnet-xxxxx \
    --security-group-ids sg-new \
    --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=legal-doc-bastion}]' \
    --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":30,"VolumeType":"gp3"}}]'
```

### Step 2: Security Group Configuration

```yaml
Bastion Security Group:
  Inbound:
    - SSH (22) from your IP: 108.210.14.204/32
    - Custom TCP (8501) from your IP  # Streamlit UI (Stage 2)
    - Custom TCP (8888) from your IP  # Jupyter (Stage 2)
  
  Outbound:
    - All traffic (for package installations)

RDS Security Group Update:
  Add Inbound:
    - PostgreSQL (5432) from Bastion Security Group
```

### Step 3: Initial Bastion Setup Script

```bash
#!/bin/bash
# setup_bastion.sh - Run after connecting to EC2

# Update system
sudo apt update && sudo apt upgrade -y

# Install PostgreSQL client
sudo apt install -y postgresql-client-15 \
    python3-pip python3-venv git htop ncdu

# Install AWS CLI
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install

# Create project directory
mkdir -p ~/legal-doc-processing
cd ~/legal-doc-processing

# Clone repository (adjust as needed)
git clone <your-repo-url> .

# Setup Python environment
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install psycopg2-binary sqlalchemy boto3

# Create SSH tunnel script
cat > ~/tunnel-to-rds.sh << 'EOF'
#!/bin/bash
# Creates local tunnel to RDS
ssh -N -L 5432:database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432 localhost
EOF
chmod +x ~/tunnel-to-rds.sh

echo "✅ Bastion setup complete!"
```

## Stage 2: AI/ML Services Setup

### Local Open-Source Replacements

| OpenAI Service | Open-Source Alternative | Resource Requirements |
|----------------|------------------------|---------------------|
| GPT-4 Text Generation | Mistral 7B, LLaMA 2 13B | 8-16GB GPU RAM |
| Embeddings (ada-002) | sentence-transformers/all-MiniLM-L6-v2 | 2GB RAM |
| OCR | Tesseract + EasyOCR | 4GB RAM |
| Entity Extraction | spaCy + Hugging Face NER | 4GB RAM |
| Document Understanding | LayoutLM, Donut | 8GB GPU RAM |

### Stage 2 Setup Script

```bash
#!/bin/bash
# setup_ml_services.sh - For Stage 2 AI/ML setup

# Install NVIDIA drivers (for GPU instances)
sudo apt install -y nvidia-driver-525 nvidia-cuda-toolkit

# Install ML dependencies
sudo apt install -y tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    libgl1-mesa-glx

# Python ML packages
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
pip install transformers sentence-transformers
pip install spacy && python -m spacy download en_core_web_lg
pip install easyocr pytesseract
pip install layoutlm-inferencer
pip install gradio streamlit  # For UI

# Download models (runs in background)
python << EOF
from sentence_transformers import SentenceTransformer
from transformers import AutoModelForCausalLM, AutoTokenizer

# Download embedding model
model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')

# Download Mistral 7B (optional, large download)
# tokenizer = AutoTokenizer.from_pretrained("mistralai/Mistral-7B-Instruct-v0.1")
# model = AutoModelForCausalLM.from_pretrained("mistralai/Mistral-7B-Instruct-v0.1")
EOF

echo "✅ ML services setup complete!"
```

### Service Architecture for Stage 2

```python
# services/local_ai_services.py
from typing import List, Dict
import torch
from sentence_transformers import SentenceTransformer
from transformers import pipeline
import spacy
import easyocr
import pytesseract

class LocalAIServices:
    def __init__(self):
        # Initialize models
        self.embedder = SentenceTransformer('all-MiniLM-L6-v2')
        self.ner = spacy.load("en_core_web_lg")
        self.ocr_reader = easyocr.Reader(['en'])
        
        # Text generation (lazy load due to size)
        self._text_generator = None
    
    @property
    def text_generator(self):
        if self._text_generator is None:
            self._text_generator = pipeline(
                "text-generation",
                model="mistralai/Mistral-7B-Instruct-v0.1",
                device=0 if torch.cuda.is_available() else -1
            )
        return self._text_generator
    
    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Replace OpenAI embeddings"""
        return self.embedder.encode(texts).tolist()
    
    def extract_entities(self, text: str) -> List[Dict]:
        """Replace OpenAI NER"""
        doc = self.ner(text)
        return [
            {
                "text": ent.text,
                "type": ent.label_,
                "start": ent.start_char,
                "end": ent.end_char
            }
            for ent in doc.ents
        ]
    
    def ocr_document(self, image_path: str) -> str:
        """Replace Textract/OpenAI Vision"""
        # Try EasyOCR first (better for complex layouts)
        try:
            results = self.ocr_reader.readtext(image_path)
            return " ".join([text for _, text, _ in results])
        except:
            # Fallback to Tesseract
            return pytesseract.image_to_string(image_path)
    
    def generate_text(self, prompt: str, max_length: int = 200) -> str:
        """Replace OpenAI text generation"""
        results = self.text_generator(
            prompt,
            max_length=max_length,
            num_return_sequences=1,
            temperature=0.7
        )
        return results[0]['generated_text']
```

## Cost Analysis

### Phase 1 (Bastion Only)
```yaml
t3.medium: ~$30/month (on-demand)
Storage (30GB): ~$3/month
Data Transfer: ~$5/month (estimated)
Total: ~$38/month

With Reserved Instance (1-year): ~$20/month
```

### Stage 2 (AI/ML Development)
```yaml
g4dn.xlarge: ~$380/month (on-demand)
Storage (200GB): ~$20/month
Data Transfer: ~$20/month (estimated)
Total: ~$420/month

With Spot Instances: ~$120/month (70% savings)
With Reserved Instance: ~$250/month
```

### Cost Optimization Strategies
1. **Start with t3.medium**, upgrade only when needed for Stage 2
2. **Use Spot Instances** for development/testing
3. **Schedule instances** to run only during work hours
4. **Use EFS** for model storage shared across instances
5. **Consider SageMaker** for production inference

## Implementation Timeline

### Week 1: Bastion Setup
- [ ] Launch t3.medium EC2 instance
- [ ] Configure security groups
- [ ] Install PostgreSQL tools
- [ ] Test RDS connectivity
- [ ] Setup development environment

### Week 2: Database Migration
- [ ] Complete RDS schema setup
- [ ] Implement SQLAlchemy introspection
- [ ] Test document processing pipeline
- [ ] Verify all connections work

### Week 3-4: Stage 2 Preparation
- [ ] Evaluate GPU instance options
- [ ] Test ML models locally first
- [ ] Plan service architecture
- [ ] Estimate resource requirements

### Month 2: Stage 2 Implementation
- [ ] Upgrade to GPU instance (or launch separate)
- [ ] Install ML frameworks
- [ ] Implement local AI services
- [ ] Create service comparison tests
- [ ] Benchmark performance vs OpenAI

## Security Best Practices

1. **Access Control**
   - Use IAM roles for EC2-to-RDS access
   - Implement SSH key rotation
   - Use Systems Manager Session Manager when possible

2. **Network Security**
   - Keep RDS in private subnet
   - Use security groups as firewalls
   - Enable VPC Flow Logs

3. **Data Protection**
   - Encrypt EBS volumes
   - Use SSL/TLS for all connections
   - Regular security updates

4. **Monitoring**
   - CloudWatch for resource usage
   - Set up alerts for unusual activity
   - Log all database queries

## Terraform Configuration (Optional)

```hcl
# main.tf - Infrastructure as Code approach
resource "aws_instance" "bastion" {
  ami           = "ami-0c02fb55956c7d316"
  instance_type = "t3.medium"
  key_name      = "legal-doc-processor"
  
  subnet_id                   = aws_subnet.public.id
  vpc_security_group_ids      = [aws_security_group.bastion.id]
  associate_public_ip_address = true
  
  root_block_device {
    volume_type = "gp3"
    volume_size = 30
    encrypted   = true
  }
  
  tags = {
    Name        = "legal-doc-bastion"
    Environment = "development"
    Purpose     = "RDS access and AI development"
  }
  
  user_data = file("setup_bastion.sh")
}

resource "aws_security_group" "bastion" {
  name_prefix = "legal-doc-bastion-"
  vpc_id      = "vpc-53107829"
  
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["108.210.14.204/32"]
  }
  
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
```

## Next Steps

1. **Immediate Action**: Launch t3.medium bastion instance
2. **Connect to RDS**: Complete database setup through bastion
3. **Plan Stage 2**: Benchmark AI models locally first
4. **Budget Approval**: Get approval for GPU instance costs
5. **Gradual Migration**: Move services from OpenAI to local one by one

This approach provides immediate RDS access while building a foundation for Stage 2's local AI services, ensuring a smooth transition from cloud-based to self-hosted AI capabilities.