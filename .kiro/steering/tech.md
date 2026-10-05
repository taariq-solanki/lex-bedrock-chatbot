# Tech Stack

## Runtime & Language

- Python 3.12 (Lambda runtime)
- Single-module Lambda with no external dependencies beyond boto3/botocore (bundled in Lambda runtime)

## Infrastructure

- **IaC**: AWS SAM (template.yaml)
- **Deployment config**: samconfig.toml
- **Region**: eu-central-1 (deploy), eu-north-1 (Bedrock model access)
- **Stack naming**: `{stage}-bedrock-chatbot` (staging / production)

## AWS Services

- Amazon Lex V2 (conversational interface, NLU)
- AWS Lambda (compute, Python 3.12)
- Amazon Bedrock (LLM inference — Claude Haiku 4.5)
- Amazon Cognito Identity Pool (unauthenticated browser credentials for Web UI)
- Amazon S3 (static website hosting for Web UI)
- IAM (least-privilege roles for Lambda, Lex, Cognito)

## Testing

- **Framework**: pytest
- **Property-based testing**: hypothesis (minimum 100 examples per property)
- **Mocking**: unittest.mock (patch boto3 clients)
- **conftest.py**: Root-level fixture patches broken pydantic hypothesis plugin

## Frontend (Web UI)

- Single-page HTML/CSS/JS (no build step)
- AWS SDK for JavaScript v2 (loaded from CDN)
- Talks directly to Lex V2 Runtime API from the browser (no API Gateway needed)

## Common Commands

```bash
# Build
sam build

# Deploy (uses samconfig.toml defaults)
sam deploy

# Deploy to production
sam deploy --parameter-overrides Stage=production --stack-name production-bedrock-chatbot

# Run all tests
pytest tests/

# Run unit tests only
pytest tests/unit/test_handler.py

# Run property-based tests only
pytest tests/unit/test_properties.py

# Deploy web UI (after main stack is deployed)
./deploy-webui.sh staging-bedrock-chatbot us-east-1
```
