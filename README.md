# Lex V2 Bedrock Chatbot

A conversational AI chatbot built on Amazon Lex V2 and Amazon Bedrock. The Lex bot routes unrecognized user input through a FallbackIntent to an AWS Lambda function, which invokes a Bedrock foundation model (Amazon Nova Pro) via the Converse API to generate intelligent responses. Conversation history is maintained across turns via Lex session attributes — no external database required.

All infrastructure is defined as code using AWS SAM, parameterized for staging and production environments.

## Architecture

```
User (Browser / Voice)
  │
  ▼
Lex V2 Bot (NLU confidence < 0.40)
  │
  ├── WelcomeIntent → static greeting (no Lambda)
  │
  └── FallbackIntent (CodeHook)
        │
        ▼
  Lambda Function (Python 3.12)
    ├── Reads/writes ConversationContext from Lex session attributes
    └── Invokes Amazon Bedrock (Amazon Nova Pro, us-east-1) via Converse API
          │
          ▼
  Response returned to user via Lex
```

**Key design choices:**
- Single-module Lambda — no external dependencies beyond boto3
- Session-based memory — conversation history stored in Lex session attributes (bounded to 10,000 chars, FIFO truncation)
- Bedrock Converse API — provider-agnostic, role-based conversation format with up to 10 turns of context; swap foundation models with a one-line config change
- SAM-native IaC — single `template.yaml` with Stage parameter for environment isolation
- Voice-enabled — Lex locale configured with Amazon Polly neural voice (Danielle)
- HTTPS delivery — CloudFront distribution fronts the S3-hosted Web UI

## Prerequisites

- **AWS CLI** — installed and configured with credentials (`aws configure`)
- **AWS SAM CLI** — [installation guide](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
- **Python 3.12**
- **Amazon Bedrock model access** — enable access to the foundation model you intend to use (default: `us.amazon.nova-pro-v1:0`) in the **us-east-1** region via the [Bedrock console](https://console.aws.amazon.com/bedrock/)

## Project Structure

```
.
├── template.yaml              # SAM template (all infrastructure)
├── samconfig.toml             # SAM deployment defaults (eu-central-1)
├── src/
│   └── handler.py             # Lambda function (single module, all logic)
├── tests/
│   ├── unit/
│   │   ├── test_handler.py            # Unit tests (intent routing, error handling)
│   │   ├── test_properties.py         # Property-based tests (hypothesis)
│   │   ├── test_conversation_context.py  # Context management tests
│   │   ├── test_invoke_bedrock.py     # Bedrock invocation tests
│   │   └── test_voice_properties.py   # Voice/Polly property tests
│   └── events/
│       └── fallback_event.json        # Sample Lex FallbackIntent event
├── conftest.py                # Pytest configuration (hypothesis/pydantic workaround)
├── webui/
│   ├── index.html             # Chat UI template (placeholders for config)
│   └── dist/                  # Generated: configured index.html for S3
├── deploy-webui.sh            # Script to inject config + upload Web UI + invalidate CDN
├── .gitignore
└── README.md
```

## Deployment

### Build

```bash
sam build
```

### Deploy to Staging (first time)

```bash
sam deploy --guided
```

This walks you through configuration (stack name, region, capabilities). Defaults are stored in `samconfig.toml` for subsequent deployments.

### Deploy to Staging (subsequent)

```bash
sam deploy
```

Uses the saved configuration from `samconfig.toml` (stack: `staging-bedrock-chatbot`, region: `eu-central-1`).

### Deploy to Production

```bash
sam deploy --parameter-overrides Stage=production --stack-name production-bedrock-chatbot
```

This creates a separate stack with `prod-` prefixed resource names, fully isolated from staging.

## Configuration

### SAM Template Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `Stage` | `staging` | Deployment stage. Controls resource naming prefix (`staging-` or `prod-`). |
| `BedrockModelId` | `us.amazon.nova-pro-v1:0` | Bedrock model (or inference profile) to invoke via the Converse API. Any Converse-compatible model works — swap freely. |
| `BedrockRegion` | `us-east-1` | AWS region where the Bedrock model/inference profile is available (can differ from stack region). |
| `SystemPrompt` | *(empty — uses built-in default)* | Override the default system prompt. |
| `PollyVoiceId` | `Danielle` | Amazon Polly neural voice ID for the en_US locale. |

### Environment Variables (Lambda)

| Variable | Source | Description |
|----------|--------|-------------|
| `BEDROCK_MODEL_ID` | SAM `BedrockModelId` parameter | Bedrock model identifier for LLM inference. |
| `BEDROCK_REGION` | SAM `BedrockRegion` parameter | Region for the Bedrock client (cross-region call). |
| `SYSTEM_PROMPT` | SAM `SystemPrompt` parameter | Custom system prompt. If empty/unset, the built-in corporate research assistant prompt is used. |

The default system prompt instructs the model to provide fact-based corporate descriptions using reliable sources.

## Testing

### Install dev dependencies

```bash
pip install pytest hypothesis boto3 botocore
```

### Run all tests

```bash
pytest tests/
```

### Run unit tests only

```bash
pytest tests/unit/test_handler.py
```

### Run property-based tests only

```bash
pytest tests/unit/test_properties.py
```

### Run voice property tests

```bash
pytest tests/unit/test_voice_properties.py
```

Property-based tests use [Hypothesis](https://hypothesis.readthedocs.io/) to verify correctness invariants across randomly generated inputs (minimum 100 iterations per property).

## Web UI (Chat Interface)

The stack includes a hosted web chat interface served over HTTPS via CloudFront.

### Deploy the Web UI

After deploying the main stack:

```bash
./deploy-webui.sh staging-bedrock-chatbot eu-central-1
```

This script:
1. Reads your stack outputs (Bot ID, Alias ID, Cognito Identity Pool ID, S3 bucket, CloudFront domain)
2. Generates a configured `index.html` with your bot credentials
3. Uploads it to the S3 website bucket created by the stack
4. Invalidates the CloudFront cache
5. Prints the HTTPS URL to open in your browser

### Manual Setup

If you prefer to configure manually, grab the values from your CloudFormation outputs:

```bash
aws cloudformation describe-stacks \
  --stack-name staging-bedrock-chatbot \
  --region eu-central-1 \
  --query "Stacks[0].Outputs"
```

Then edit `webui/index.html` and replace the `{{PLACEHOLDER}}` values in the CONFIG object with your actual IDs.

### Web UI Architecture

- **Amazon Cognito Identity Pool** — provides temporary AWS credentials to the browser (unauthenticated access)
- **Lex V2 Runtime API** — the browser calls `recognizeText` / `recognizeUtterance` directly via the AWS SDK
- **S3 Static Website Hosting** — serves the single-page chat interface
- **CloudFront** — provides HTTPS access and caching (required for microphone/voice features)

No server-side API Gateway is needed — the browser talks directly to Lex.

## How It Works

1. **User sends a message** to the Lex V2 bot (text or voice)
2. **Lex evaluates NLU confidence** — if below 0.40, routes to the FallbackIntent
3. **FallbackIntent triggers Lambda** via the CodeHook
4. **Lambda retrieves conversation history** from Lex session attributes (`ConversationContext` key)
5. **Lambda constructs the prompt** — system instruction + up to 10 most recent turns + current user input
6. **Lambda calls Bedrock** via the Converse API (provider-agnostic) in us-east-1
7. **Lambda extracts the response**, updates session history (FIFO truncation at 10,000 chars), and returns to Lex
8. **Lex delivers the response** to the user (text or speech via Polly)

### Error Handling

- **Missing model ID** — returns "service temporarily unavailable" message
- **Bedrock API error** — returns graceful "couldn't process your request" message
- **Empty Bedrock response** — returns "didn't get a valid response" message
- **Malformed conversation history** — silently re-initializes context and continues
- **Non-FallbackIntent** — returns a Close response without invoking the LLM

All error messages are guaranteed to reach the user even if logging infrastructure is degraded.

## Regions

| Concern | Region | Reason |
|---------|--------|--------|
| Stack deployment (Lambda, Lex, Cognito, S3, CloudFront) | us-east-1 | Primary operational region (full Lex V2 support) |
| Bedrock model inference | us-east-1 | Amazon Nova Pro availability |

The Lambda targets Bedrock using the `BEDROCK_REGION` environment variable. The model layer uses the Converse API, so you can point `BedrockRegion` at any region where your chosen model/inference profile is available (cross-region calls supported).
