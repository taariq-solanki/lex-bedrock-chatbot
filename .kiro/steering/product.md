# Product Overview

A conversational AI chatbot built on Amazon Lex V2 and Amazon Bedrock. The Lex bot routes unrecognized user input (NLU confidence < 0.40) through a FallbackIntent to an AWS Lambda function, which invokes Bedrock's Claude model to generate intelligent responses.

## Key Capabilities

- Corporate research assistant that provides fact-based company information
- Conversation memory maintained via Lex session attributes (no external database)
- Chat history bounded to 10,000 characters with FIFO truncation
- Browser-based Web UI using Cognito for unauthenticated access directly to Lex
- Multi-stage deployment support (staging / production) with isolated resource naming

## Domain Context

- The bot's default persona is a "corporate research assistant" providing fact-based descriptions of corporations
- System prompt is configurable via environment variable or SAM parameter
- The Lambda only activates on FallbackIntent — other intents (e.g. WelcomeIntent) are handled natively by Lex
