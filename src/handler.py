"""
AWS Lambda handler for Lex V2 Bedrock chatbot.

Routes FallbackIntent events to Amazon Bedrock for LLM-powered responses,
managing conversation context via Lex session attributes.
"""

import json
import os
import random
import time
from datetime import UTC, datetime

import boto3
from botocore.exceptions import ClientError

# X-Ray SDK — available in Lambda Python 3.12 runtime but may not be present in test environments
try:
    from aws_xray_sdk.core import xray_recorder
    XRAY_AVAILABLE = True
except ImportError:
    XRAY_AVAILABLE = False


class StructuredLogger:
    """Structured JSON logger for Lambda function.

    Emits single-line JSON log entries to stdout with standard fields:
    timestamp, level, message, request_id, and optional context fields.
    """

    def __init__(self):
        self._request_id = None
        self._intent_name = None
        self._session_id = None

    def set_context(self, request_id=None, intent_name=None, session_id=None):
        """Set context fields for the current invocation."""
        if request_id is not None:
            self._request_id = request_id
        if intent_name is not None:
            self._intent_name = intent_name
        if session_id is not None:
            self._session_id = session_id

    def log(self, level, message, **extra):
        """Emit a single-line JSON log entry."""
        entry = {
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level": level,
            "message": message,
            "request_id": self._request_id or "unknown",
        }
        # Add context fields if set
        if self._intent_name:
            entry["intent_name"] = self._intent_name
        if self._session_id:
            entry["session_id"] = self._session_id
        # Add any extra fields
        entry.update(extra)
        print(json.dumps(entry, default=str))

    def info(self, message, **extra):
        self.log("INFO", message, **extra)

    def warning(self, message, **extra):
        self.log("WARNING", message, **extra)

    def error(self, message, **extra):
        self.log("ERROR", message, **extra)

    def critical(self, message, **extra):
        self.log("CRITICAL", message, **extra)


# Create module-level structured logger instance
structured_logger = StructuredLogger()

# Environment variable validation
REQUIRED_ENV_VARS = ["BEDROCK_MODEL_ID", "BEDROCK_REGION"]


def _validate_environment():
    """Validate that all required environment variables are set and non-empty.

    Raises RuntimeError listing ALL missing variables if any are absent or empty.
    Logs a CRITICAL structured JSON entry before raising.
    """
    missing = [var for var in REQUIRED_ENV_VARS if not os.environ.get(var)]
    if missing:
        entry = {
            "level": "CRITICAL",
            "message": f"Missing required environment variables: {missing}",
            "event_type": "env_validation_failure",
            "missing_vars": missing,
        }
        print(json.dumps(entry))
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}"
        )


_validate_environment()

BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "")

# Default system prompt for corporate research assistant
DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful corporate research assistant. Provide fact-based "
    "descriptions of corporations using reliable sources such as Wikipedia "
    "and official company reports. Be concise and accurate."
)

# System prompt resolution: use env var if set and non-empty, otherwise default
SYSTEM_PROMPT = os.environ.get("SYSTEM_PROMPT", "") or DEFAULT_SYSTEM_PROMPT

# Bedrock client initialization (may target a different region than the stack)
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "")
bedrock_runtime = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION) if BEDROCK_REGION else boto3.client("bedrock-runtime")

# CloudWatch client for custom metrics
cloudwatch_client = boto3.client("cloudwatch")


def publish_metric(metric_name, value, unit="Count", dimensions=None):
    """Publish a custom metric to the ProductionChatbot namespace.

    Errors are caught and logged — metric failures must never affect user response.
    """
    try:
        metric_data = {
            "MetricName": metric_name,
            "Value": value,
            "Unit": unit,
        }
        if dimensions:
            metric_data["Dimensions"] = dimensions
        cloudwatch_client.put_metric_data(
            Namespace="ProductionChatbot",
            MetricData=[metric_data]
        )
    except Exception as e:
        structured_logger.warning(
            "Failed to publish metric",
            event_type="metric_publish_error",
            metric_name=metric_name,
            error_message=str(e)
        )


def lambda_handler(event, context):
    """
    Entry point for the Lambda function.

    Routes FallbackIntent to the LLM flow. For non-FallbackIntent events,
    returns a Close response without LLM-generated content.
    """
    # Set request_id from Lambda context at handler entry
    request_id = getattr(context, "aws_request_id", None) if context else None
    structured_logger.set_context(request_id=request_id)

    # Extract intent name from the Lex event
    intent_name = event["sessionState"]["intent"]["name"]
    session_attributes = event.get("sessionState", {}).get("sessionAttributes", {}) or {}
    session_id = event.get("sessionId", "")

    # Update logger context with intent and session info
    structured_logger.set_context(intent_name=intent_name, session_id=session_id)

    structured_logger.info("Lambda handler invoked", event_type="handler_entry")

    # Route non-FallbackIntent events to Close response
    if intent_name != "FallbackIntent":
        structured_logger.info("Non-FallbackIntent received, returning Close", event_type="intent_routing")
        return build_lex_response(
            session_attributes=session_attributes,
            intent_request=event,
            message="Intent handled."
        )

    # FallbackIntent flow — invoke Bedrock
    # LLM flow: get context, build messages, invoke Bedrock, update context
    user_input = event.get("inputTranscript", "")

    # Validate and sanitize input
    user_input, should_proceed = validate_input(user_input)
    if not should_proceed:
        structured_logger.info("Empty/whitespace input, returning guidance", event_type="empty_input")
        return build_lex_response(
            session_attributes=session_attributes,
            intent_request=event,
            message="I didn't catch that. Could you please rephrase?"
        )

    structured_logger.info("Processing FallbackIntent", event_type="fallback_processing")

    # Retrieve conversation context from session attributes
    conversation_context = get_conversation_context(session_attributes)

    # Build messages for Bedrock Claude Messages API
    messages = build_messages(conversation_context, user_input)

    # Invoke Bedrock
    ai_response = invoke_bedrock_with_retry(messages, SYSTEM_PROMPT)

    # Update conversation context with new exchange
    updated_context = update_conversation_context(conversation_context, user_input, ai_response)

    # Persist updated context in session attributes
    session_attributes["ConversationContext"] = json.dumps(updated_context)

    structured_logger.info("Bedrock response received", event_type="bedrock_response")

    return build_lex_response(
        session_attributes=session_attributes,
        intent_request=event,
        message=ai_response
    )


def _to_converse_messages(messages):
    """Convert internal Claude-style messages to Bedrock Converse API format.

    Internal format:  {"role": r, "content": [{"type": "text", "text": t}, ...]}
    Converse format:  {"role": r, "content": [{"text": t}, ...]}

    The Converse API is provider-agnostic (works for Amazon Nova, Anthropic
    Claude, etc.), so the model can be swapped via BEDROCK_MODEL_ID without
    changing this handler.
    """
    converse_messages = []
    for msg in messages:
        blocks = []
        for block in msg.get("content", []):
            text = block.get("text", "") if isinstance(block, dict) else str(block)
            blocks.append({"text": text})
        converse_messages.append({"role": msg["role"], "content": blocks})
    return converse_messages


def invoke_bedrock(messages, system_prompt):
    """
    Calls Bedrock via the Converse API.

    Uses the provider-agnostic Converse API so the underlying model
    (Amazon Nova, Anthropic Claude, etc.) can be changed through the
    BEDROCK_MODEL_ID environment variable with no code change.

    Returns the generated text string. Raises on API failures so the retry
    wrapper can handle retries. Wraps the call in an X-Ray subsegment named
    "BedrockInvokeModel" when aws_xray_sdk is available.
    """
    subsegment = None
    if XRAY_AVAILABLE:
        try:
            subsegment = xray_recorder.begin_subsegment("BedrockInvokeModel")
        except Exception:
            pass

    try:
        converse_kwargs = {
            "modelId": BEDROCK_MODEL_ID,
            "messages": _to_converse_messages(messages),
            "inferenceConfig": {"maxTokens": 1024},
        }
        if system_prompt:
            converse_kwargs["system"] = [{"text": system_prompt}]

        response = bedrock_runtime.converse(**converse_kwargs)

        # Extract text from Converse response:
        # output.message.content is a list of blocks; concatenate text blocks.
        content_blocks = (
            response.get("output", {})
            .get("message", {})
            .get("content", [])
        )
        text_parts = [b["text"] for b in content_blocks if isinstance(b, dict) and "text" in b]
        combined = "".join(text_parts).strip()

        # Handle missing or empty content in response
        if not combined:
            structured_logger.warning(
                "Bedrock response missing or empty content",
                event_type="bedrock_empty_response"
            )
            return "I'm sorry, I didn't get a valid response. Please try again."

        return combined
    except Exception as e:
        if subsegment:
            try:
                subsegment.add_exception(e)
            except Exception:
                pass
        raise
    finally:
        if XRAY_AVAILABLE and subsegment:
            try:
                xray_recorder.end_subsegment()
            except Exception:
                pass


# Retry configuration per exception type
RETRY_CONFIG = {
    "ThrottlingException": {"max_retries": 3, "base_delay": 1.0},
    "ServiceUnavailableException": {"max_retries": 3, "base_delay": 1.0},
    "ModelTimeoutException": {"max_retries": 2, "base_delay": 2.0},
}

GRACEFUL_ERROR_MESSAGE = "I'm sorry, the service is temporarily busy. Please try again in a moment."


def invoke_bedrock_with_retry(messages, system_prompt):
    """Invoke Bedrock with retry logic and exponential backoff for transient errors.

    Publishes BedrockLatency metric on success and BedrockError metric when
    all retries are exhausted or a non-retryable error occurs.

    Returns:
        str: AI response text or graceful error message if all retries exhausted.
    """
    last_exception = None
    max_possible_retries = max(cfg["max_retries"] for cfg in RETRY_CONFIG.values())

    for attempt in range(max_possible_retries + 1):
        try:
            start = time.time()
            result = invoke_bedrock(messages, system_prompt)
            latency_ms = (time.time() - start) * 1000
            try:
                publish_metric("BedrockLatency", latency_ms, unit="Milliseconds")
            except Exception:
                pass
            structured_logger.info(
                "Bedrock call succeeded",
                bedrock_latency_ms=round(latency_ms, 2),
                event_type="bedrock_success"
            )
            return result
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            config = RETRY_CONFIG.get(error_code)

            if config is None:
                # Non-retryable error — publish BedrockError metric
                try:
                    publish_metric("BedrockError", 1, unit="Count", dimensions=[
                        {"Name": "ErrorType", "Value": error_code}
                    ])
                except Exception:
                    pass
                structured_logger.error(
                    "Bedrock API error (non-retryable)",
                    error_type=error_code,
                    error_message=e.response["Error"]["Message"],
                    event_type="bedrock_api_error"
                )
                return "I'm sorry, I couldn't process your request. Please try again."

            if attempt >= config["max_retries"]:
                # Exhausted retries for this error type
                last_exception = e
                break

            # Calculate delay with exponential backoff + jitter
            delay = config["base_delay"] * (2 ** attempt) + random.uniform(0, 0.5)
            delay_ms = int(delay * 1000)

            structured_logger.warning(
                "Retrying Bedrock invocation",
                event_type="retry_attempt",
                retry_attempt=attempt + 1,
                error_type=error_code,
                retry_delay_ms=delay_ms
            )

            time.sleep(delay)
            last_exception = e

    # All retries exhausted — publish BedrockError metric
    if last_exception:
        error_code = last_exception.response["Error"]["Code"]
        try:
            publish_metric("BedrockError", 1, unit="Count", dimensions=[
                {"Name": "ErrorType", "Value": error_code}
            ])
        except Exception:
            pass
        structured_logger.error(
            "All retries exhausted for Bedrock invocation",
            event_type="retries_exhausted",
            error_type=error_code,
            error_message=last_exception.response["Error"]["Message"]
        )
    return GRACEFUL_ERROR_MESSAGE


def validate_input(input_transcript):
    """Validate and sanitize user input.

    Returns:
        tuple: (cleaned_input, should_proceed) - cleaned input and whether to continue processing.
               Returns (None, False) for empty/whitespace-only input.
               Truncates to 1000 characters if input exceeds that limit.
    """
    if not input_transcript or not input_transcript.strip():
        return None, False
    if len(input_transcript) > 1000:
        structured_logger.warning(
            "Input exceeds 1000 characters, truncating",
            event_type="input_truncated",
            original_length=len(input_transcript)
        )
        input_transcript = input_transcript[:1000]
    return input_transcript, True


def get_conversation_context(session_attributes):
    """
    Retrieves and deserializes ConversationContext from Lex session attributes.

    Initializes default context when the key is absent. Handles malformed JSON
    by discarding and re-initializing.

    Args:
        session_attributes: Dict of Lex session attributes.

    Returns:
        Dict with "chat_history" key containing the conversation string.
    """
    default_context = {"chat_history": "Human: hi\nAI: Hello! How can I help you?"}

    # If the key is completely absent, initialize with default
    if "ConversationContext" not in session_attributes:
        structured_logger.info(
            "No ConversationContext found, initializing default",
            event_type="context_init"
        )
        return default_context

    raw_value = session_attributes["ConversationContext"]

    # An empty string value does NOT trigger re-initialization (per Requirement 2.4)
    if raw_value == "":
        return {"chat_history": ""}

    # Attempt to deserialize the JSON value
    try:
        context = json.loads(raw_value)
        return context
    except (json.JSONDecodeError, TypeError):
        structured_logger.warning(
            "Malformed ConversationContext JSON detected, discarding and re-initializing",
            event_type="context_corruption",
            raw_value=raw_value
        )
        publish_metric("ContextCorruption", 1)
        return default_context


def update_conversation_context(context, user_input, ai_response):
    """
    Appends the new exchange to the conversation context and enforces
    the 10,000-character limit via FIFO truncation.

    Args:
        context: Dict with "chat_history" key.
        user_input: The user's message string.
        ai_response: The AI's response string.

    Returns:
        Updated context dict with the new exchange appended and truncated if needed.
    """
    # Append new exchange to chat_history
    new_exchange = f"\nHuman: {user_input}\nAI: {ai_response}"
    context["chat_history"] = context["chat_history"] + new_exchange

    # Enforce 10,000-character limit by removing oldest complete exchange pairs
    chat_history = context["chat_history"]
    if len(chat_history) > 10000:
        # Split into individual exchange pairs (Human: ...\nAI: ...)
        # We find all "Human:" boundaries to identify pair starts
        pairs = []
        parts = chat_history.split("\nHuman: ")

        # The first part might start with "Human: " (no leading newline)
        if parts[0].startswith("Human: "):
            parts[0] = parts[0][len("Human: "):]
        else:
            # Edge case: first segment before any "Human:" marker
            # This shouldn't happen with well-formed data, but handle gracefully
            parts[0] = parts[0]

        for part in parts:
            if part:
                pairs.append("Human: " + part)

        # Remove oldest pairs until within limit
        while len("\n".join(pairs)) > 10000 and len(pairs) > 1:
            pairs.pop(0)

        context["chat_history"] = "\n".join(pairs)

    return context


def build_messages(conversation_context, user_input):
    """
    Converts stored conversation history and current user input into
    Claude Messages API format. Limits to 10 most recent turns.

    A "turn" is one user message + one assistant message pair.
    The chat_history string uses "Human: " and "AI: " prefixes.
    Multi-line responses are grouped with their prefix until the next marker.

    Args:
        conversation_context: Dict with "chat_history" key containing formatted string.
        user_input: The current user message to append.

    Returns:
        List of message dicts in Claude Messages API format.
    """
    messages = []
    chat_history = conversation_context.get("chat_history", "")

    if chat_history:
        # Parse the chat_history string into individual messages
        # Lines starting with "Human: " or "AI: " denote new messages
        # Multi-line content belongs to the most recent prefix
        lines = chat_history.split("\n")
        current_role = None
        current_text = ""

        for line in lines:
            if line.startswith("Human: "):
                # Save previous message if exists
                if current_role is not None and current_text:
                    messages.append({
                        "role": current_role,
                        "content": [{"type": "text", "text": current_text}]
                    })
                current_role = "user"
                current_text = line[len("Human: "):]
            elif line.startswith("AI: "):
                # Save previous message if exists
                if current_role is not None and current_text:
                    messages.append({
                        "role": current_role,
                        "content": [{"type": "text", "text": current_text}]
                    })
                current_role = "assistant"
                current_text = line[len("AI: "):]
            else:
                # Continuation of the current message (multi-line)
                if current_role is not None:
                    current_text += "\n" + line

        # Don't forget the last parsed message
        if current_role is not None and current_text:
            messages.append({
                "role": current_role,
                "content": [{"type": "text", "text": current_text}]
            })

    # Limit to the 10 most recent turns (a turn = 1 user + 1 assistant message)
    # Count turns by counting pairs from the end
    if messages:
        # Each turn is 2 messages (user + assistant). Limit to 10 turns = 20 messages max.
        max_messages = 10 * 2  # 10 turns
        if len(messages) > max_messages:
            messages = messages[-max_messages:]

    # Append current user input as the final user message
    messages.append({
        "role": "user",
        "content": [{"type": "text", "text": user_input}]
    })

    return messages


def build_lex_response(session_attributes, intent_request, message):
    """
    Constructs a Lex V2 Close response with updated session attributes.

    Args:
        session_attributes: Updated session attributes dict
        intent_request: Original Lex event for extracting intent info
        message: PlainText message to return to the user

    Returns:
        Dict matching Lex V2 response format with Close dialog action.
    """
    intent_name = intent_request["sessionState"]["intent"]["name"]

    return {
        "sessionState": {
            "dialogAction": {
                "type": "Close"
            },
            "intent": {
                "name": intent_name,
                "state": "Fulfilled"
            },
            "sessionAttributes": session_attributes
        },
        "messages": [
            {
                "contentType": "PlainText",
                "content": message
            }
        ]
    }
