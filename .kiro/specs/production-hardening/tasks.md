# Implementation Plan: Production Hardening

## Overview

This plan transforms the staging Lex V2 Bedrock Chatbot into a production-grade deployment across five pillars: Security, Reliability & Performance, Observability, Operations & CI/CD, and Code Hardening. All infrastructure changes target `template.yaml`, all application logic changes target `src/handler.py`, and CI/CD is a new GitHub Actions workflow.

## Tasks

- [x] 1. Security: S3 Private Access + CloudFront OAC
  - [x] 1.1 Convert WebUI S3 bucket to private with OAC
    - Remove `WebsiteConfiguration` from `WebUIBucket`
    - Set all four `PublicAccessBlockConfiguration` properties to `true`
    - Add `BucketEncryption` with `SSEAlgorithm: AES256`
    - Add `VersioningConfiguration` with `Status: Enabled`
    - Define `AWS::CloudFront::OriginAccessControl` resource with `OriginAccessControlOriginType: s3`, `SigningBehavior: always`, `SigningProtocol: sigv4`
    - Update CloudFront origin to use S3 regional domain name (not website endpoint) and reference the OAC
    - Replace bucket policy to grant `s3:GetObject` only to `cloudfront.amazonaws.com` conditioned on the distribution ARN
    - Remove the `WebUIUrl` output (no longer valid without website hosting)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 5.1, 5.2_

  - [x] 1.2 Add CloudFront cache policy
    - Define a `AWS::CloudFront::CachePolicy` with MinTTL=0, DefaultTTL=60, MaxTTL=300
    - Update CloudFront default cache behavior to reference the custom cache policy
    - Remove legacy `ForwardedValues` from the distribution
    - _Requirements: 10.1, 10.2_

  - [x] 1.3 Add WAF WebACL to CloudFront
    - Define `AWS::WAFv2::WebACL` with `Scope: CLOUDFRONT` and default action Allow
    - Add `AWSManagedRulesCommonRuleSet` managed rule group (priority 1)
    - Add IP rate-based rule limiting to 1000 requests per 5 minutes (priority 2)
    - Associate WAF with CloudFront distribution via `WebACLId` property
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

- [x] 2. Security: Cognito Authentication + IAM Scoping
  - [x] 2.1 Replace Cognito unauthenticated access with User Pool authentication
    - Define `AWS::Cognito::UserPool` with password policy (min 8, uppercase, lowercase, number, symbol)
    - Define `AWS::Cognito::UserPoolClient` with authorization code grant flow and OAuth scopes (openid, email, profile)
    - Set `AllowUnauthenticatedIdentities: false` on the Identity Pool
    - Link Identity Pool to User Pool via `CognitoIdentityProviders`
    - Define authenticated IAM role with same Lex permissions scoped to bot alias ARN
    - Remove `CognitoUnauthRole` resource and unauthenticated role attachment
    - Update `CognitoIdentityPoolRoleAttachment` to map only the authenticated role
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [x] 2.2 Scope down IAM policies
    - Restrict Bedrock `InvokeModel` resource ARN to `eu-north-1` region only (replace wildcard)
    - Scope Lex bot role `polly:SynthesizeSpeech` to `arn:aws:polly:${AWS::Region}:${AWS::AccountId}:lexicon/*`
    - Add `sqs:SendMessage` for DLQ ARN to Lambda role
    - Add `xray:PutTraceSegments` and `xray:PutTelemetryRecords` to Lambda role
    - Add `cloudwatch:PutMetricData` to Lambda role (conditioned on `ProductionChatbot` namespace)
    - Verify no broader permissions exist on the Lambda execution role
    - _Requirements: 3.1, 3.2, 3.3_

- [x] 3. Reliability: Lambda Configuration + DLQ
  - [x] 3.1 Configure Lambda concurrency, timeout, tracing, and DLQ
    - Define `AWS::SQS::Queue` (DLQ) with `MessageRetentionPeriod: 1209600` (14 days)
    - Add `Conditions` for stage-based concurrency: `IsProduction: !Equals [!Ref Stage, production]`
    - Set `ReservedConcurrentExecutions` to 10 (staging) / 50 (production) using `!If`
    - Configure provisioned concurrency of 2 for production only (via `AWS::Lambda::Alias` + `ProvisionedConcurrencyConfig`)
    - Set Lambda `Timeout` to 60 seconds
    - Set `Tracing: Active` on the Lambda function
    - Set `DeadLetterQueue` property referencing the SQS DLQ ARN with type `SQS`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 7.1, 7.2, 7.3, 8.1, 13.1, 13.2_

  - [x] 3.2 Configure Lex code hook timeout to match Lambda
    - Update Lex bot alias `CodeHookSpecification` timeout to 60 seconds to match Lambda timeout
    - _Requirements: 8.2_

- [x] 4. Observability: CloudWatch Alarms + SNS
  - [x] 4.1 Add CloudWatch alarms and SNS alert topic
    - Define `AWS::SNS::Topic` (AlarmTopic)
    - Define Lambda error rate alarm: `Errors / Invocations > 0.05` over 5-minute period
    - Define Lambda p99 duration alarm: `Duration p99 > 45000ms` over 5-minute period
    - Define Lex missed utterance alarm: `MissedUtteranceCount > 20` over 5-minute period
    - Configure all alarms to publish to the SNS topic on ALARM state
    - Add `AlarmTopicArn` as a stack output
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

- [x] 5. Checkpoint — Verify template changes
  - Ensure `sam build` succeeds with the updated template. Ask the user if questions arise.

- [x] 6. Code Hardening: Environment Validation + Structured Logging
  - [x] 6.1 Implement environment variable validation at cold start
    - Define `REQUIRED_ENV_VARS = ["BEDROCK_MODEL_ID", "BEDROCK_REGION"]`
    - Implement `_validate_environment()` function that checks all required vars are set and non-empty
    - Log structured CRITICAL entry with `event_type: "env_validation_failure"` listing missing vars
    - Raise `RuntimeError` with message listing ALL missing variables
    - Call `_validate_environment()` at module level (cold start)
    - Remove existing inline `BEDROCK_MODEL_ID` empty-check from `lambda_handler`
    - _Requirements: 20.1, 20.2, 20.3, 20.4_

  - [x] 6.2 Implement structured JSON logging
    - Create `StructuredLogger` class that emits single-line JSON to stdout
    - Include fields: `timestamp`, `level`, `message`, `request_id`, `intent_name`, `session_id`
    - Support extra fields: `bedrock_latency_ms`, `error_type`, `error_message`, `event_type`, `retry_attempt`, `retry_delay_ms`
    - Replace all existing `logger.info/warning/error` calls with structured logger calls
    - Ensure `request_id` is set from `context.aws_request_id` at handler entry
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

  - [ ]* 6.3 Write property tests for structured logging (Property 5)
    - **Property 5: Structured log formatter produces valid single-line JSON**
    - Test that for any message string (including newlines, special chars, Unicode), output is valid JSON, single-line, and contains required fields
    - **Validates: Requirements 11.1**

  - [ ]* 6.4 Write property tests for environment validation (Property 10)
    - **Property 10: Missing environment variables raise RuntimeError listing all missing**
    - Test that for any non-empty subset of required env vars being missing/empty, RuntimeError is raised with ALL missing var names in the message, and CRITICAL log is emitted
    - **Validates: Requirements 20.3, 20.4**

- [x] 7. Code Hardening: Input Validation + Context Recovery
  - [x] 7.1 Implement input validation on inputTranscript
    - Create `validate_input()` function that checks length and whitespace
    - Truncate input exceeding 1000 characters and log warning with original length
    - Return early with "I didn't catch that. Could you please rephrase?" for empty/whitespace input
    - Integrate validation into `lambda_handler` before Bedrock invocation
    - _Requirements: 18.1, 18.2, 18.3_

  - [ ]* 7.2 Write property tests for input validation (Properties 5, 6)
    - **Property 6: Input exceeding 1000 characters is truncated**
    - **Property 7: Whitespace-only input is rejected without Bedrock invocation**
    - Test truncation preserves first 1000 chars; test whitespace-only strings never invoke Bedrock
    - **Validates: Requirements 18.1, 18.2, 18.3**

  - [x] 7.3 Enhance context corruption recovery with metrics
    - Update `get_conversation_context()` to log structured warning with `event_type: "context_corruption"`
    - Publish `ContextCorruption` metric (value=1) to `ProductionChatbot` namespace on corruption
    - Ensure fresh default context is returned and processing continues normally
    - _Requirements: 19.1, 19.2, 19.3_

  - [ ]* 7.4 Write property tests for context corruption recovery (Property 8)
    - **Property 8: Malformed context triggers recovery with metric**
    - Test that for any non-JSON string in ConversationContext, fresh context is initialized, metric published, warning logged, and valid Lex response returned
    - **Validates: Requirements 19.1, 19.2, 19.3**

- [x] 8. Code Hardening: Retry Logic + Custom Metrics
  - [x] 8.1 Implement retry engine with exponential backoff
    - Create `invoke_bedrock_with_retry()` function with retry config per exception type
    - ThrottlingException / ServiceUnavailableException: max 3 retries, base delay 1s
    - ModelTimeoutException: max 2 retries, base delay 2s
    - Add jitter (random 0–500ms) to each backoff delay
    - Log each retry attempt as structured JSON with `retry_attempt`, `error_type`, `retry_delay_ms`
    - Return graceful error message when all retries exhausted: "I'm sorry, the service is temporarily busy. Please try again in a moment."
    - Integrate into `lambda_handler` replacing direct `invoke_bedrock()` call
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

  - [ ]* 8.2 Write property tests for retry logic (Properties 1, 2, 3, 4)
    - **Property 1: Retry logic respects exception-specific configuration**
    - **Property 2: Exhausted retries return graceful error message**
    - **Property 3: Retry backoff delay is bounded**
    - **Property 4: Retry attempts emit structured log entries**
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5**

  - [x] 8.3 Implement custom CloudWatch metrics publisher
    - Create CloudWatch client and `publish_metric()` helper function
    - Publish `BedrockLatency` metric (ms) on successful Bedrock calls
    - Publish `BedrockError` metric (count=1, dimension `ErrorType`) on failed Bedrock calls
    - Add X-Ray subsegment `BedrockInvokeModel` around each Bedrock call using `aws_xray_sdk`
    - Wrap metric/X-Ray errors in try/except to never affect user response
    - _Requirements: 13.3, 14.1, 14.2_

  - [ ]* 8.4 Write property tests for Bedrock metrics (Properties 9, 10)
    - **Property 9: BedrockError metric includes correct ErrorType dimension**
    - **Property 10: BedrockLatency metric published on successful call** (covered by Property 8 in design)
    - **Validates: Requirements 14.1, 14.2**

- [x] 9. Checkpoint — Verify all handler changes
  - Ensure all unit and property tests pass (`pytest tests/unit/`). Ask the user if questions arise.

- [x] 10. Operations: CI/CD Pipeline
  - [x] 10.1 Create GitHub Actions deployment workflow
    - Create `.github/workflows/deploy.yml` with stages: lint → unit-test → build → deploy-staging → integration-test → deploy-production → post-deploy
    - Lint stage: run `ruff check src/ tests/`
    - Unit test stage: run `pytest tests/unit/` and fail pipeline on non-zero exit
    - Build stage: run `sam build`
    - Deploy-staging: `sam deploy` to `staging-bedrock-chatbot` stack with `Stage=staging`
    - Deploy-production: `sam deploy` to `production-bedrock-chatbot` stack with `Stage=production` (only after integration tests pass)
    - Post-deploy: enable termination protection on production stack via `aws cloudformation update-termination-protection`
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 17.1_

  - [x] 10.2 Create integration test script
    - Create `tests/integration/test_deployed.py`
    - Test 1: Invoke deployed Lex bot via `lexv2-runtime` SDK, verify non-empty non-error response (FallbackIntent triggers Bedrock)
    - Test 2: GET CloudFront distribution URL, assert HTTP 200 for Web UI index page
    - Accept stack name and region as pytest parameters
    - _Requirements: 16.1, 16.2, 16.3, 16.4_

- [x] 11. Final Checkpoint — Full validation
  - Ensure all tests pass (`pytest tests/unit/`), `sam build` succeeds, and `sam validate` passes. Ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Infrastructure tasks (1–4) modify `template.yaml` only; code tasks (6–8) modify `src/handler.py` only
- The CI/CD pipeline (task 10) is a new file and does not modify existing code
- All Python code uses only boto3/botocore (bundled in Lambda runtime) — no external dependencies
- The `aws_xray_sdk` is available in the Lambda Python 3.12 runtime without adding a layer

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1", "6.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "2.2", "6.2"] },
    { "id": 2, "tasks": ["3.1", "3.2", "4.1", "6.3", "6.4"] },
    { "id": 3, "tasks": ["7.1", "7.3", "8.1"] },
    { "id": 4, "tasks": ["7.2", "7.4", "8.2", "8.3"] },
    { "id": 5, "tasks": ["8.4", "10.1"] },
    { "id": 6, "tasks": ["10.2"] }
  ]
}
```
