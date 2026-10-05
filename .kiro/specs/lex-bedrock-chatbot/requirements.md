# Requirements Document

## Introduction

This feature rebuilds an existing AWS Lex V2 chatbot to replace SageMaker/LangChain-based LLM integration with Amazon Bedrock. The system provisions all infrastructure as code (SAM) for a staging environment that can be promoted to production. The core flow remains: Lex V2 bot receives user input → FallbackIntent triggers Lambda → Lambda calls Bedrock with conversation history → response returned to user. All legacy workshop artifacts, SageMaker dependencies, and LangChain code are removed in favor of a clean, minimal implementation.

## Glossary

- **Chatbot_Lambda**: The AWS Lambda function that handles Lex FallbackIntent events and invokes Bedrock for LLM responses
- **Lex_Bot**: The Amazon Lex V2 bot that receives user utterances and routes unmatched input to the FallbackIntent
- **Bedrock_Client**: The component within Chatbot_Lambda that calls the Amazon Bedrock InvokeModel API
- **Conversation_Context**: The conversation history stored in Lex V2 session attributes, passed to Bedrock as part of the prompt
- **IaC_Template**: The AWS SAM template defining all infrastructure resources for the chatbot system
- **Staging_Environment**: A parameterized deployment of the chatbot stack used for testing before production promotion

## Requirements

### Requirement 1: Bedrock LLM Integration

**User Story:** As a chatbot operator, I want the Lambda function to use Amazon Bedrock as the LLM provider, so that I eliminate the SageMaker endpoint dependency and reduce operational cost and complexity.

#### Acceptance Criteria

1. WHEN the FallbackIntent is triggered, THE Chatbot_Lambda SHALL invoke the Amazon Bedrock InvokeModel API with the user's input text and the Conversation_Context retrieved from the Lex session attributes
2. WHEN Bedrock returns a response, THE Chatbot_Lambda SHALL extract the generated text from the model response body and return it to Lex_Bot as a PlainText message
3. THE Chatbot_Lambda SHALL read the Bedrock model ID from an environment variable named BEDROCK_MODEL_ID
4. IF the BEDROCK_MODEL_ID environment variable is not set or is empty, THEN THE Chatbot_Lambda SHALL return an error message indicating the service is unavailable to the user regardless of whether logging succeeds, and SHALL log the missing configuration on a best-effort basis
5. THE Chatbot_Lambda SHALL construct a prompt that includes the Conversation_Context (limited to the most recent 10 conversation turns) and a system instruction directing the model to provide fact-based corporate descriptions
6. WHEN Bedrock returns a response, THE Chatbot_Lambda SHALL update the Conversation_Context in the Lex session attributes with the current user input and model response
7. IF the Bedrock InvokeModel API returns an error, THEN THE Chatbot_Lambda SHALL return a message to Lex_Bot indicating the request could not be processed and log the error type and error message; logging failures SHALL NOT prevent the error message from being returned to the user

### Requirement 2: Conversation Memory via Lex Session Attributes

**User Story:** As a chatbot user, I want the bot to remember what we discussed earlier in the session, so that I can have a coherent multi-turn conversation.

#### Acceptance Criteria

1. WHEN a user message is processed, THE Chatbot_Lambda SHALL retrieve the Conversation_Context from the Lex V2 session attributes using the key "ConversationContext"
2. WHEN the LLM returns a response, THE Chatbot_Lambda SHALL append the current human input prefixed with "Human:" and the AI response prefixed with "AI:" to the Conversation_Context chat_history field
3. WHEN the LLM returns a response, THE Chatbot_Lambda SHALL persist the updated Conversation_Context as a JSON-serialized string back into the Lex V2 session attributes before returning the response to Lex
4. WHEN no prior Conversation_Context key exists in the session attributes, THE Chatbot_Lambda SHALL initialize the Conversation_Context with a JSON object containing a chat_history field set to the default greeting prompt; an empty string value for the key SHALL NOT trigger re-initialization
5. IF the Conversation_Context exceeds 10,000 characters, THEN THE Chatbot_Lambda SHALL truncate by removing complete exchange pairs (one Human turn and its corresponding AI turn) starting from the oldest, until the total length is within the 10,000-character limit
6. IF the Conversation_Context retrieved from session attributes contains malformed JSON, THEN THE Chatbot_Lambda SHALL discard the corrupted context and re-initialize an empty conversation history as defined in criterion 4

### Requirement 3: Infrastructure as Code with SAM

**User Story:** As a DevOps engineer, I want all chatbot infrastructure defined in a SAM template, so that I can deploy, version, and promote environments consistently.

#### Acceptance Criteria

1. THE IaC_Template SHALL define the Lex_Bot resource with a FallbackIntent whose fulfillment CodeHook is configured to specifically reference the Chatbot_Lambda resource defined in the same template
2. THE IaC_Template SHALL define the Chatbot_Lambda resource with Python 3.12 runtime, a memory size of 256 MB, a timeout of 30 seconds, and an IAM execution role granting permissions limited to bedrock:InvokeModel for the configured model ARN and logs:CreateLogGroup, logs:CreateLogStream, and logs:PutLogEvents for the Lambda's log group
3. THE IaC_Template SHALL accept a Stage parameter with allowed values of "staging" and "production" that controls resource naming prefixes and Lambda environment variables
4. THE IaC_Template SHALL define IAM roles that grant only the permissions explicitly enumerated in each resource's criterion, with no wildcard (*) actions and resource ARNs scoped to the deployed stack
5. WHEN the Stage parameter is set to "staging", THE IaC_Template SHALL prefix all resource names with "staging-" to isolate from production
6. THE IaC_Template SHALL define the Bedrock model ID as a parameter with a default value of "anthropic.claude-3-haiku-20240307-v1:0"
7. WHEN the Stage parameter is set to "production", THE IaC_Template SHALL prefix all resource names with "prod-" to isolate from staging
8. THE IaC_Template SHALL define a Lambda permission resource that grants the Lex_Bot service principal permission to invoke the Chatbot_Lambda

### Requirement 4: Lex V2 Bot Configuration

**User Story:** As a chatbot operator, I want the Lex bot configured with a FallbackIntent that routes unrecognized input to the LLM, so that users always get an intelligent response.

#### Acceptance Criteria

1. THE Lex_Bot SHALL be configured with a FallbackIntent using the AMAZON.FallbackIntent parent signature that invokes the Chatbot_Lambda via both an initial response code hook and a fulfillment code hook
2. THE Lex_Bot SHALL be configured with the en_US locale and an NLU confidence threshold of 0.40, below which user input is routed to the FallbackIntent
3. THE Lex_Bot SHALL have a child-directed setting of false
4. THE Lex_Bot SHALL have idle session timeout configured to 300 seconds
5. IF the Chatbot_Lambda invocation fails or times out during FallbackIntent fulfillment, THEN THE Lex_Bot SHALL return a fallback error message to the user before ending the conversation

### Requirement 5: Codebase Cleanup

**User Story:** As a developer, I want all legacy SageMaker, LangChain, and workshop artifacts removed, so that the repository contains only production-relevant code.

#### Acceptance Criteria

1. THE repository SHALL NOT contain any files that import or invoke SageMaker libraries, any directories named with "sagemaker" or "sm_utils", or any dependency declarations referencing SageMaker packages
2. THE repository SHALL NOT contain any files that import or invoke LangChain libraries, any filenames containing "langchain", or any dependency declarations referencing LangChain packages
3. THE repository SHALL NOT contain workshop artifacts, defined as: files with a .ipynb extension, files with a .zip extension, the file ReadersAreLeaders.txt, or files named .DS_Store
4. THE repository SHALL NOT contain the LexJson directory or any of its subdirectories and files
5. THE repository SHALL contain a .gitignore file at the repository root that includes rules to exclude .DS_Store files, __pycache__ directories, files with a .zip extension, and .env files

### Requirement 6: Lambda Function Structure

**User Story:** As a developer, I want a clean, minimal Lambda function that is easy to understand and maintain, so that future modifications are straightforward.

#### Acceptance Criteria

1. THE Chatbot_Lambda SHALL be implemented as a single Python module with no external dependencies beyond boto3 and the AWS SDK
2. THE Chatbot_Lambda SHALL use structured logging for all operational messages
3. THE Chatbot_Lambda SHALL validate that required environment variables are present at initialization
4. WHEN the incoming event does not contain a FallbackIntent, THE Chatbot_Lambda SHALL return a close response; LLM invocation for non-response purposes such as logging or monitoring is permitted but no LLM-generated content SHALL be returned to the user

### Requirement 7: Prompt Engineering

**User Story:** As a chatbot operator, I want the system prompt to be configurable and well-structured, so that I can tune the bot's behavior without code changes.

#### Acceptance Criteria

1. THE Chatbot_Lambda SHALL use a prompt template that includes a system instruction, conversation history, and the current user input formatted as separate sections
2. THE Chatbot_Lambda SHALL support overriding the default system prompt via an environment variable named SYSTEM_PROMPT
3. THE default system prompt SHALL instruct the model to provide fact-based descriptions of corporations using reliable sources
4. IF the SYSTEM_PROMPT environment variable is set but empty or if no valid prompt is available from any source, THEN THE Chatbot_Lambda SHALL always fall back to the default system prompt
