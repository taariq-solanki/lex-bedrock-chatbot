# Implementation Plan: Lex Bedrock Chatbot

## Overview

This plan implements a clean Amazon Lex V2 + Bedrock chatbot by first removing all legacy artifacts, then building the project structure, Lambda handler, SAM template, tests, and deployment configuration incrementally. Each task builds on the previous, ending with full integration.

## Tasks

- [x] 1. Codebase cleanup and project structure
  - [x] 1.1 Delete legacy files and directories
    - Delete `lambda3.9/` directory and all contents (SageMaker/LangChain dispatchers, sm_utils, lambda_function.py)
    - Delete `lambda3.9.zip`
    - Delete `langchain_layer_3.9.zip`
    - Delete `LexJson/` directory and all contents
    - Delete `LexJson.zip`
    - Delete `chatbot_llm.ipynb`
    - Delete `ReadersAreLeaders.txt`
    - Delete all `.DS_Store` files
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x] 1.2 Create project directory structure and .gitignore
    - Create `src/` directory
    - Create `tests/unit/` directory
    - Create `tests/events/` directory
    - Create `.gitignore` at repository root with rules for: `.DS_Store`, `__pycache__/`, `*.zip`, `.env`, `.aws-sam/`, `*.pyc`
    - _Requirements: 5.5_

- [x] 2. Implement Lambda handler
  - [x] 2.1 Create the core Lambda handler module (`src/handler.py`)
    - Implement module-level initialization: imports (json, logging, os, boto3), structured logger setup, environment variable validation for BEDROCK_MODEL_ID
    - Implement `DEFAULT_SYSTEM_PROMPT` constant with corporate research assistant instruction
    - Implement `SYSTEM_PROMPT` resolution: use env var if set and non-empty, otherwise default
    - Implement `lambda_handler(event, context)` entry point that checks intent name and routes FallbackIntent to LLM flow, returns Close for non-FallbackIntent
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 7.2, 7.3, 7.4_

  - [x] 2.2 Implement Bedrock integration functions
    - Implement `invoke_bedrock(messages, system_prompt)` that calls `bedrock-runtime` client `invoke_model` with Claude Messages API format (`anthropic_version: bedrock-2023-05-31`, `max_tokens: 1024`)
    - Handle Bedrock API errors: catch `ClientError`, log error type and message, return error message string
    - Handle missing/empty content in Bedrock response: log warning, return fallback message
    - Extract generated text from `response["content"][0]["text"]`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.7_

  - [x] 2.3 Implement conversation memory management functions
    - Implement `get_conversation_context(session_attributes)` that retrieves "ConversationContext" key, deserializes JSON, handles missing key (initialize default), handles malformed JSON (log warning, re-initialize default)
    - Implement `update_conversation_context(context, user_input, ai_response)` that appends `"Human: {input}\nAI: {response}"` to chat_history
    - Implement truncation logic: if chat_history exceeds 10,000 characters, remove oldest complete `Human: ...\nAI: ...` pairs until within limit
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [x] 2.4 Implement prompt construction and Lex response builder
    - Implement `build_messages(conversation_context, user_input)` that converts stored history string into Claude Messages API format (alternating user/assistant roles), limits to 10 most recent turns, appends current user input as final user message
    - Implement `build_lex_response(session_attributes, intent_request, message)` that constructs Lex V2 Close response with dialogAction type "Close", intent state "Fulfilled", updated sessionAttributes, and PlainText message
    - _Requirements: 1.5, 1.6, 7.1_

- [x] 3. Checkpoint - Verify Lambda handler
  - Ensure all handler functions are implemented and internally consistent, ask the user if questions arise.

- [x] 4. Create SAM template and deployment config
  - [x] 4.1 Create the SAM template (`template.yaml`)
    - Define `AWSTemplateFormatVersion`, `Transform: AWS::Serverless-2016-10-31`, Description
    - Define Parameters: `Stage` (AllowedValues: staging, production; Default: staging), `BedrockModelId` (Default: anthropic.claude-3-haiku-20240307-v1:0), `SystemPrompt` (Default: empty string)
    - Define `ChatbotLambda` resource (AWS::Serverless::Function): Python 3.12 runtime, 256 MB memory, 30s timeout, `src/handler.lambda_handler` handler, environment variables (BEDROCK_MODEL_ID, SYSTEM_PROMPT), function name using `!Sub "${Stage}-bedrock-chatbot-fn"`
    - Define `ChatbotLambdaRole` (AWS::IAM::Role): assume role policy for lambda.amazonaws.com, policy with bedrock:InvokeModel scoped to model ARN, CloudWatch Logs permissions scoped to the function's log group
    - _Requirements: 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

  - [x] 4.2 Add Lex Bot resources to SAM template
    - Define `LexBot` (AWS::Lex::Bot): name using `!Sub "${Stage}-bedrock-chatbot-bot"`, en_US locale, NLU confidence threshold 0.40, idle session TTL 300s, child-directed false, FallbackIntent with AMAZON.FallbackIntent parent signature
    - Define `LexBotVersion` (AWS::Lex::BotVersion) linked to LexBot
    - Define `LexBotAlias` (AWS::Lex::BotAlias) with CodeHookSpecification pointing to ChatbotLambda for FallbackIntent fulfillment
    - Define `LexInvokeLambdaPermission` (AWS::Lambda::Permission) granting lex.amazonaws.com invoke permission on ChatbotLambda
    - _Requirements: 3.1, 3.8, 4.1, 4.2, 4.3, 4.4, 4.5_

  - [x] 4.3 Create SAM deployment config and sample event
    - Create `samconfig.toml` with default deployment configuration (stack name referencing stage, region, confirm_changeset, capabilities)
    - Create `tests/events/fallback_event.json` with a sample Lex V2 FallbackIntent event payload matching the data model in the design document
    - _Requirements: 3.3_

- [x] 5. Checkpoint - Validate SAM template
  - Ensure SAM template is syntactically valid (run `sam validate` if SAM CLI is available), ask the user if questions arise.

- [x] 6. Write tests
  - [x] 6.1 Create unit tests (`tests/unit/test_handler.py`)
    - Write test for FallbackIntent event triggering Bedrock call (mock boto3 client)
    - Write test for missing BEDROCK_MODEL_ID returning error message
    - Write test for Bedrock API error returning graceful failure message
    - Write test for empty session attributes initializing default ConversationContext
    - Write test for non-FallbackIntent returning Close without Bedrock invocation
    - Write test for SYSTEM_PROMPT env var overriding default
    - Write test for empty SYSTEM_PROMPT env var using default
    - Write test for malformed ConversationContext JSON re-initializing context
    - _Requirements: 1.1, 1.4, 1.7, 2.4, 6.4, 7.2, 7.4, 2.6_

  - [x] 6.2 Write property test: Prompt construction invariant (Property 1)
    - **Property 1: Prompt construction invariant**
    - Use `hypothesis` to generate random conversation histories (0-20 turns) and random non-empty user input strings
    - Assert: result always contains system instruction, at most 10 recent turns as alternating user/assistant messages, current user input as final message
    - **Validates: Requirements 1.1, 1.5, 7.1**

  - [x] 6.3 Write property test: Response extraction produces valid Lex format (Property 2)
    - **Property 2: Response extraction produces valid Lex format**
    - Use `hypothesis` to generate random non-empty strings for Bedrock response content
    - Assert: output has `messages[0].contentType == "PlainText"` and `messages[0].content` equals input text
    - **Validates: Requirements 1.2**

  - [x] 6.4 Write property test: Context update preserves exchange format (Property 3)
    - **Property 3: Context update preserves exchange format**
    - Use `hypothesis` to generate random existing context strings, user inputs, and AI responses
    - Assert: appended portion matches `"Human: {input}\nAI: {response}"` pattern and previous history is preserved as prefix
    - **Validates: Requirements 1.6, 2.2**

  - [x] 6.5 Write property test: Context serialization round-trip (Property 4)
    - **Property 4: Context serialization round-trip**
    - Use `hypothesis` to generate random ConversationContext dicts with `chat_history` string field
    - Assert: serializing to JSON then deserializing produces identical `chat_history` value
    - **Validates: Requirements 2.3**

  - [x] 6.6 Write property test: Truncation maintains size invariant (Property 5)
    - **Property 5: Truncation maintains size invariant**
    - Use `hypothesis` to generate conversation strings exceeding 10,000 chars with valid exchange pair format
    - Assert: result ≤ 10,000 chars, contains only complete exchange pairs, retains most recent exchanges
    - **Validates: Requirements 2.5**

  - [x] 6.7 Write property test: Malformed JSON recovery (Property 6)
    - **Property 6: Malformed JSON recovery**
    - Use `hypothesis` to generate random strings that fail `json.loads()` (binary data, partial JSON, plain text)
    - Assert: returns default initialized context with greeting prompt, does not raise exception
    - **Validates: Requirements 2.6**

  - [x] 6.8 Write property test: Non-FallbackIntent routing (Property 7)
    - **Property 7: Non-FallbackIntent routing**
    - Use `hypothesis` to generate random Lex event dicts with intent names other than "FallbackIntent"
    - Assert: returns Close dialog action, does not invoke Bedrock client
    - **Validates: Requirements 6.4**

- [x] 7. Final checkpoint and documentation
  - [x] 7.1 Create README.md
    - Write project overview, prerequisites (AWS CLI, SAM CLI, Python 3.12, Bedrock model access)
    - Document deployment steps: `sam build`, `sam deploy --guided` for staging, parameter override for production
    - Document environment variables and configuration options
    - Document testing: `pytest tests/` command
    - _Requirements: 3.3, 3.5, 3.7_

  - [x] 7.2 Final checkpoint - Ensure all tests pass
    - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional property-based tests and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests use the `hypothesis` library and validate universal correctness properties from the design
- Unit tests use `pytest` with `unittest.mock` for AWS service mocking (no external test dependencies beyond pytest and hypothesis)
- The SAM template validation checkpoint (task 5) requires SAM CLI installed locally

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["2.1"] },
    { "id": 3, "tasks": ["2.2", "2.3"] },
    { "id": 4, "tasks": ["2.4"] },
    { "id": 5, "tasks": ["4.1", "4.3"] },
    { "id": 6, "tasks": ["4.2"] },
    { "id": 7, "tasks": ["6.1"] },
    { "id": 8, "tasks": ["6.2", "6.3", "6.4", "6.5", "6.6", "6.7", "6.8"] },
    { "id": 9, "tasks": ["7.1"] }
  ]
}
```
