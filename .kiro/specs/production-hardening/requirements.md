# Requirements Document

## Introduction

This feature hardens the existing staging Lex V2 Bedrock Chatbot into a production-grade deployment. It addresses five pillars: security (removing public S3 access, enforcing authentication, scoping IAM, adding WAF, enabling encryption), reliability and performance (concurrency controls, dead-letter queues, timeouts, retry logic, caching), observability (structured logging, CloudWatch alarms, X-Ray tracing, Bedrock latency metrics), operations and CI/CD (automated pipeline, integration tests, termination protection), and code-level hardening (input validation, graceful degradation, environment validation at cold start).

## Glossary

- **SAM_Template**: The AWS SAM template.yaml file defining all infrastructure resources for this project
- **Lambda_Function**: The AWS Lambda function (`handler.lambda_handler`) that processes Lex FallbackIntent events via Bedrock
- **CloudFront_Distribution**: The Amazon CloudFront distribution serving the Web UI over HTTPS
- **WebUI_Bucket**: The S3 bucket hosting the static Web UI files
- **Origin_Access_Control**: A CloudFront mechanism (OAC) that restricts S3 bucket access exclusively to the associated CloudFront distribution
- **WAF_WebACL**: An AWS WAF Web Access Control List attached to the CloudFront distribution to filter malicious traffic
- **Cognito_Identity_Pool**: The Amazon Cognito Identity Pool providing browser credentials for Lex API access
- **Cognito_User_Pool**: An Amazon Cognito User Pool providing authentication (sign-up, sign-in) for chatbot users
- **Dead_Letter_Queue**: An Amazon SQS queue that receives Lambda invocation payloads that failed all retry attempts
- **CI_CD_Pipeline**: An automated pipeline that builds, tests, and deploys the application through staging and production stages
- **Bedrock_Client**: The boto3 bedrock-runtime client used to invoke Claude Haiku 4.5 in eu-north-1
- **Input_Transcript**: The `inputTranscript` field from the Lex event containing the user's text input

## Requirements

### Requirement 1: Remove Public S3 Access and Use CloudFront Origin Access Control

**User Story:** As a security engineer, I want the Web UI S3 bucket to be private with access restricted to CloudFront via OAC, so that users cannot bypass CloudFront protections by accessing S3 directly.

#### Acceptance Criteria

1. THE SAM_Template SHALL set all four `PublicAccessBlockConfiguration` properties (`BlockPublicAcls`, `BlockPublicPolicy`, `IgnorePublicAcls`, `RestrictPublicBuckets`) to `true` on the WebUI_Bucket
2. THE SAM_Template SHALL remove the `WebsiteConfiguration` property from the WebUI_Bucket since S3 static website hosting is no longer required
3. THE SAM_Template SHALL define a CloudFront Origin_Access_Control resource with `OriginAccessControlOriginType` set to "s3" and `SigningBehavior` set to "always"
4. THE SAM_Template SHALL configure the CloudFront_Distribution origin to use the S3 bucket's regional domain name (not the website endpoint) and reference the Origin_Access_Control resource
5. THE SAM_Template SHALL replace the existing public-access bucket policy with a policy that grants `s3:GetObject` only to the CloudFront service principal (`cloudfront.amazonaws.com`) conditioned on the distribution's ARN
6. IF a request is made directly to the S3 bucket URL (bypassing CloudFront), THEN THE WebUI_Bucket SHALL deny the request with an HTTP 403 Forbidden response

### Requirement 2: Disable Unauthenticated Cognito Access

**User Story:** As a security engineer, I want all chatbot users to authenticate before accessing Lex, so that anonymous users cannot consume resources or abuse the bot.

#### Acceptance Criteria

1. THE SAM_Template SHALL set `AllowUnauthenticatedIdentities` to `false` on the Cognito_Identity_Pool
2. THE SAM_Template SHALL define a Cognito_User_Pool resource with password policy requiring minimum 8 characters, at least one uppercase letter, one lowercase letter, one number, and one symbol
3. THE SAM_Template SHALL define a Cognito User Pool Client resource configured for the Web UI with authorization code grant flow
4. THE SAM_Template SHALL define an authenticated IAM role for the Cognito_Identity_Pool with the same Lex permissions (`lex:RecognizeText`, `lex:RecognizeUtterance`, `lex:DeleteSession`, `lex:PutSession`) currently granted to the unauthenticated role, scoped to the bot alias ARN
5. THE SAM_Template SHALL remove the unauthenticated IAM role and its role attachment from the Cognito_Identity_Pool configuration
6. IF an unauthenticated request is made to the Lex API using credentials from the Identity Pool, THEN THE Cognito_Identity_Pool SHALL deny credential issuance

### Requirement 3: Scope Down IAM Policies

**User Story:** As a security engineer, I want IAM policies to follow least-privilege by restricting Bedrock access to eu-north-1 and scoping Polly to the specific bot resource, so that permissions are minimized to only what the application requires.

#### Acceptance Criteria

1. THE SAM_Template SHALL restrict the Bedrock `InvokeModel` permission resource ARN to use only the `eu-north-1` region (replacing any wildcard region in the ARN)
2. THE SAM_Template SHALL scope the Lex bot role's `polly:SynthesizeSpeech` permission to the specific lexicon resource ARN pattern `arn:aws:polly:${AWS::Region}:${AWS::AccountId}:lexicon/*` instead of using a wildcard resource ("*")
3. THE SAM_Template SHALL ensure the Lambda execution role has no broader permissions than: `bedrock:InvokeModel` (eu-north-1 only), `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents`, and SQS permissions for the Dead_Letter_Queue

### Requirement 4: Add WAF to CloudFront

**User Story:** As a security engineer, I want a WAF Web ACL attached to the CloudFront distribution, so that the Web UI is protected against common web exploits and volumetric attacks.

#### Acceptance Criteria

1. THE SAM_Template SHALL define a WAF_WebACL resource in the `us-east-1` region (required for CloudFront-associated WAFs) with a default action of Allow
2. THE WAF_WebACL SHALL include the AWS Managed Rules Common Rule Set (`AWSManagedRulesCommonRuleSet`) to block common attack patterns including SQL injection and cross-site scripting
3. THE WAF_WebACL SHALL include an IP-rate-based rule that limits requests to 1000 per 5-minute window per IP address
4. THE SAM_Template SHALL associate the WAF_WebACL with the CloudFront_Distribution via the `WebACLId` property
5. IF a request matches a rule in the WAF_WebACL configured to block, THEN THE CloudFront_Distribution SHALL return an HTTP 403 Forbidden response to the client

### Requirement 5: Enable S3 Encryption at Rest

**User Story:** As a security engineer, I want S3 bucket data encrypted at rest, so that stored Web UI assets are protected against unauthorized physical access to storage media.

#### Acceptance Criteria

1. THE SAM_Template SHALL configure `BucketEncryption` on the WebUI_Bucket with `ServerSideEncryptionByDefault` using `SSEAlgorithm` set to "AES256" (SSE-S3)
2. THE SAM_Template SHALL enable `VersioningConfiguration` with `Status` set to "Enabled" on the WebUI_Bucket to support object recovery

### Requirement 6: Lambda Reserved Concurrency and Provisioned Concurrency

**User Story:** As an operations engineer, I want Lambda concurrency controls configured, so that the function has guaranteed capacity and does not exhaust account-level concurrency during traffic spikes.

#### Acceptance Criteria

1. THE SAM_Template SHALL set `ReservedConcurrentExecutions` on the Lambda_Function to 10 for the staging stage and 50 for the production stage
2. THE SAM_Template SHALL configure provisioned concurrency of 2 on the production stage Lambda_Function to eliminate cold starts for baseline traffic
3. WHILE the Lambda_Function is operating at its reserved concurrency limit, THE Lambda service SHALL throttle additional invocations rather than consuming unreserved account concurrency
4. WHERE the Stage parameter is "staging", THE SAM_Template SHALL not configure provisioned concurrency (to reduce cost)

### Requirement 7: Dead Letter Queue for Failed Invocations

**User Story:** As an operations engineer, I want failed Lambda invocations captured in a Dead Letter Queue, so that I can inspect and replay failed events without data loss.

#### Acceptance Criteria

1. THE SAM_Template SHALL define an SQS Dead_Letter_Queue resource with a message retention period of 14 days
2. THE SAM_Template SHALL configure the Lambda_Function's `DeadLetterQueue` property to reference the SQS Dead_Letter_Queue ARN
3. THE SAM_Template SHALL grant the Lambda execution role `sqs:SendMessage` permission scoped to the Dead_Letter_Queue ARN
4. WHEN the Lambda_Function invocation fails after all retry attempts, THE Lambda service SHALL send the event payload to the Dead_Letter_Queue

### Requirement 8: Increase Lambda Timeout for Bedrock Calls

**User Story:** As a reliability engineer, I want the Lambda timeout increased to accommodate Bedrock's variable response latency, so that valid responses are not lost to premature timeouts.

#### Acceptance Criteria

1. THE SAM_Template SHALL set the Lambda_Function `Timeout` to 60 seconds (increased from 30 seconds) to accommodate Bedrock cross-region inference latency
2. THE Lambda_Function timeout SHALL remain below the Lex integration timeout (default 30 seconds for code hooks) — IF the Lex code hook timeout is lower, THEN THE SAM_Template SHALL configure the Lex alias `CodeHookSpecification` timeout to 60 seconds to match

### Requirement 9: Retry Logic with Exponential Backoff for Bedrock

**User Story:** As a reliability engineer, I want the Lambda function to retry transient Bedrock errors with exponential backoff, so that intermittent service issues do not result in user-facing failures.

#### Acceptance Criteria

1. WHEN the Bedrock_Client returns a `ThrottlingException` or `ServiceUnavailableException`, THE Lambda_Function SHALL retry the request up to 3 times with exponential backoff (base delay 1 second, multiplied by 2 on each retry)
2. WHEN the Bedrock_Client returns a `ModelTimeoutException`, THE Lambda_Function SHALL retry the request up to 2 times with exponential backoff (base delay 2 seconds)
3. IF all retry attempts are exhausted, THEN THE Lambda_Function SHALL return a graceful error message to the user: "I'm sorry, the service is temporarily busy. Please try again in a moment."
4. THE Lambda_Function SHALL add jitter (random 0-500ms) to each backoff delay to prevent thundering-herd effects
5. WHEN a retry occurs, THE Lambda_Function SHALL log the retry attempt number, exception type, and delay duration as a structured JSON log entry

### Requirement 10: CloudFront Caching Policy

**User Story:** As a performance engineer, I want a short-TTL caching policy on CloudFront, so that the dynamic Web UI HTML is served quickly without serving stale content after deployments.

#### Acceptance Criteria

1. THE SAM_Template SHALL define a CloudFront Cache Policy with a minimum TTL of 0 seconds, a default TTL of 60 seconds, and a maximum TTL of 300 seconds
2. THE CloudFront_Distribution default cache behavior SHALL reference the custom cache policy instead of using legacy `ForwardedValues`
3. WHEN a new deployment uploads updated files to S3, THE deploy-webui.sh script SHALL continue to invalidate the CloudFront cache so users receive updated content within seconds

### Requirement 11: Structured JSON Logging

**User Story:** As an observability engineer, I want all Lambda log output in structured JSON format, so that logs are searchable and parseable by CloudWatch Logs Insights and monitoring tools.

#### Acceptance Criteria

1. THE Lambda_Function SHALL emit all log entries as single-line JSON objects containing at minimum: `timestamp`, `level`, `message`, and `request_id` fields
2. WHEN a Bedrock API call is made, THE Lambda_Function SHALL log the call duration in milliseconds as a `bedrock_latency_ms` field in the structured log entry
3. WHEN an error occurs, THE Lambda_Function SHALL include `error_type` and `error_message` fields in the structured log entry
4. THE Lambda_Function SHALL include `intent_name` and `session_id` fields in log entries related to request processing for correlation

### Requirement 12: CloudWatch Alarms

**User Story:** As an operations engineer, I want CloudWatch alarms for key error and performance metrics, so that I am alerted when the system degrades before users are significantly impacted.

#### Acceptance Criteria

1. THE SAM_Template SHALL define a CloudWatch Alarm that triggers when the Lambda_Function error rate exceeds 5% over a 5-minute period (using the `Errors` metric divided by `Invocations`)
2. THE SAM_Template SHALL define a CloudWatch Alarm that triggers when the Lambda_Function p99 duration exceeds 45 seconds over a 5-minute period
3. THE SAM_Template SHALL define a CloudWatch Alarm that triggers when the Lex bot `MissedUtteranceCount` exceeds 20 in a 5-minute period
4. WHEN any alarm transitions to the ALARM state, THE alarm SHALL publish a notification to an SNS topic defined in the SAM_Template
5. THE SAM_Template SHALL expose the SNS topic ARN as a stack output so operators can subscribe alerting endpoints (email, PagerDuty, Slack)

### Requirement 13: X-Ray Tracing

**User Story:** As an observability engineer, I want distributed tracing enabled on the Lambda function, so that I can visualize end-to-end request latency and identify bottlenecks in the Bedrock call chain.

#### Acceptance Criteria

1. THE SAM_Template SHALL set `Tracing: Active` on the Lambda_Function to enable AWS X-Ray active tracing
2. THE SAM_Template SHALL grant the Lambda execution role `xray:PutTraceSegments` and `xray:PutTelemetryRecords` permissions
3. THE Lambda_Function SHALL create a subsegment named "BedrockInvokeModel" around each Bedrock API call to isolate Bedrock latency in traces

### Requirement 14: Bedrock Latency Metrics

**User Story:** As an observability engineer, I want custom CloudWatch metrics for Bedrock call latency, so that I can dashboard and alarm on LLM response times independently of overall Lambda duration.

#### Acceptance Criteria

1. WHEN a Bedrock API call completes successfully, THE Lambda_Function SHALL publish a custom CloudWatch metric named `BedrockLatency` in the namespace `ProductionChatbot` with the call duration in milliseconds
2. WHEN a Bedrock API call fails, THE Lambda_Function SHALL publish a custom CloudWatch metric named `BedrockError` in the namespace `ProductionChatbot` with a value of 1, including a `ErrorType` dimension with the exception class name
3. THE SAM_Template SHALL grant the Lambda execution role `cloudwatch:PutMetricData` permission scoped to the `ProductionChatbot` namespace

### Requirement 15: CI/CD Pipeline

**User Story:** As a DevOps engineer, I want an automated CI/CD pipeline, so that every code change is validated through lint, test, build, and multi-stage deployment without manual intervention.

#### Acceptance Criteria

1. THE project SHALL include a pipeline definition (e.g., GitHub Actions workflow or AWS CodePipeline) that executes the following stages in order: lint → unit test → build → deploy-staging → integration-test → deploy-production
2. THE pipeline SHALL fail and halt deployment if any stage fails (lint errors, test failures, build errors, or integration test failures)
3. THE pipeline deploy-staging stage SHALL deploy to the `staging-bedrock-chatbot` stack with `Stage=staging`
4. THE pipeline deploy-production stage SHALL deploy to the `production-bedrock-chatbot` stack with `Stage=production` only after integration tests pass against the staging deployment
5. THE pipeline SHALL run `pytest tests/` during the unit test stage and require all tests to pass with exit code 0

### Requirement 16: Integration and Smoke Tests Post-Deploy

**User Story:** As a DevOps engineer, I want automated integration tests that verify the deployed stack, so that I can confirm the system works end-to-end before promoting to production.

#### Acceptance Criteria

1. THE project SHALL include an integration test script that invokes the deployed Lex bot via the AWS SDK and verifies a successful response is returned
2. THE integration test SHALL verify that the FallbackIntent triggers a Bedrock-powered response (non-empty, non-error response text)
3. THE integration test SHALL verify that the CloudFront distribution returns HTTP 200 for the Web UI index page
4. IF any integration test fails, THEN THE CI_CD_Pipeline SHALL halt and not proceed to the production deployment stage

### Requirement 17: Stack Termination Protection

**User Story:** As an operations engineer, I want CloudFormation termination protection enabled on the production stack, so that accidental stack deletion does not destroy production resources.

#### Acceptance Criteria

1. THE CI_CD_Pipeline deploy-production stage SHALL enable termination protection on the `production-bedrock-chatbot` CloudFormation stack after successful deployment
2. IF a user attempts to delete the production stack without first disabling termination protection, THEN CloudFormation SHALL reject the deletion request

### Requirement 18: Input Validation on inputTranscript

**User Story:** As a security engineer, I want the Lambda function to validate and truncate overly long user input, so that excessively large payloads do not waste Bedrock tokens or cause unexpected behavior.

#### Acceptance Criteria

1. WHEN the Lambda_Function receives an event, THE Lambda_Function SHALL extract `inputTranscript` and validate its length does not exceed 1000 characters
2. IF the `inputTranscript` exceeds 1000 characters, THEN THE Lambda_Function SHALL truncate the input to 1000 characters and log a warning including the original length
3. IF the `inputTranscript` is empty or contains only whitespace after trimming, THEN THE Lambda_Function SHALL return a response message "I didn't catch that. Could you please rephrase?" without invoking Bedrock

### Requirement 19: Graceful Degradation for Context Corruption

**User Story:** As a reliability engineer, I want the Lambda function to recover gracefully from conversation context corruption, so that users can continue chatting even when session state is damaged.

#### Acceptance Criteria

1. WHEN the `ConversationContext` session attribute contains malformed JSON, THE Lambda_Function SHALL discard the corrupted context, initialize a fresh default context, and log a structured warning with `event_type` set to "context_corruption"
2. WHEN the `ConversationContext` is discarded due to corruption, THE Lambda_Function SHALL publish a custom CloudWatch metric named `ContextCorruption` in the namespace `ProductionChatbot` with a value of 1
3. THE Lambda_Function SHALL continue processing the user's current input using the fresh context without returning an error to the user

### Requirement 20: Environment Variable Validation at Cold Start

**User Story:** As a reliability engineer, I want the Lambda function to validate required environment variables at cold start, so that misconfigured deployments fail fast with clear error messages instead of producing cryptic runtime errors.

#### Acceptance Criteria

1. WHEN the Lambda_Function cold-starts (module load), THE Lambda_Function SHALL validate that `BEDROCK_MODEL_ID` is set and non-empty
2. WHEN the Lambda_Function cold-starts, THE Lambda_Function SHALL validate that `BEDROCK_REGION` is set and non-empty
3. IF any required environment variable is missing or empty at cold start, THEN THE Lambda_Function SHALL raise a `RuntimeError` with a message listing all missing variables, preventing the function from serving requests
4. THE Lambda_Function SHALL log the validation failure as a structured JSON entry with `level` set to "CRITICAL" and `event_type` set to "env_validation_failure" before raising the error
