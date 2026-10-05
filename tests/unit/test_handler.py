"""
Unit tests for the lambda_handler function and top-level handler behaviors.

Tests integration-level scenarios: intent routing, error handling,
environment variable resolution, and session attribute management.

Validates: Requirements 1.1, 1.4, 1.7, 2.4, 6.4, 7.2, 7.4, 2.6
"""

import io
import json
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    """Set required environment variables before importing handler."""
    monkeypatch.setenv("BEDROCK_MODEL_ID", "us.amazon.nova-pro-v1:0")
    monkeypatch.setenv("BEDROCK_REGION", "us-east-1")


@pytest.fixture
def mock_bedrock():
    """Mock the bedrock_runtime client at module level."""
    with patch("src.handler.bedrock_runtime") as mock_client:
        yield mock_client


def _make_bedrock_response(text="This is the AI response."):
    """Helper to create a mock Bedrock Converse API response."""
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"text": text}],
            }
        },
        "stopReason": "end_turn",
    }


def _make_lex_event(
    intent_name="FallbackIntent",
    input_transcript="Tell me about Amazon",
    session_attributes=None,
):
    """Helper to create a Lex V2 event payload."""
    if session_attributes is None:
        session_attributes = {
            "ConversationContext": json.dumps(
                {"chat_history": "Human: hi\nAI: Hello!"}
            )
        }
    return {
        "sessionId": "test-session",
        "inputTranscript": input_transcript,
        "bot": {"id": "test", "name": "test-bot", "localeId": "en_US", "version": "DRAFT"},
        "sessionState": {
            "intent": {"name": intent_name, "state": "InProgress"},
            "sessionAttributes": session_attributes,
        },
        "requestAttributes": {},
    }


# ---------------------------------------------------------------------------
# Test 1: FallbackIntent triggers Bedrock call
# Validates: Requirement 1.1
# ---------------------------------------------------------------------------

class TestFallbackIntentTriggersBedrock:
    """FallbackIntent events should invoke Bedrock and return the response."""

    def test_invoke_model_called(self, mock_bedrock):
        """Bedrock Converse is called when FallbackIntent is received."""
        from src.handler import lambda_handler

        mock_bedrock.converse.return_value = _make_bedrock_response("Amazon is a company.")
        event = _make_lex_event()

        lambda_handler(event, None)

        mock_bedrock.converse.assert_called_once()

    def test_response_contains_bedrock_text(self, mock_bedrock):
        """Response message contains the text from Bedrock."""
        from src.handler import lambda_handler

        mock_bedrock.converse.return_value = _make_bedrock_response(
            "Amazon is a multinational technology company."
        )
        event = _make_lex_event()

        result = lambda_handler(event, None)

        assert result["messages"][0]["content"] == "Amazon is a multinational technology company."
        assert result["messages"][0]["contentType"] == "PlainText"


# ---------------------------------------------------------------------------
# Test 2: Missing environment variables raise RuntimeError at cold start
# Validates: Requirement 20.1, 20.2, 20.3, 20.4
# ---------------------------------------------------------------------------

class TestEnvironmentValidation:
    """When required env vars are missing, _validate_environment raises RuntimeError."""

    def test_raises_runtime_error_missing_model_id(self, monkeypatch):
        """RuntimeError raised when BEDROCK_MODEL_ID is missing."""
        import importlib

        import src.handler as handler_module

        monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
        monkeypatch.setenv("BEDROCK_REGION", "eu-north-1")

        with pytest.raises(RuntimeError, match="BEDROCK_MODEL_ID"):
            importlib.reload(handler_module)

        # Restore env for subsequent tests
        monkeypatch.setenv("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")
        importlib.reload(handler_module)

    def test_raises_runtime_error_missing_region(self, monkeypatch):
        """RuntimeError raised when BEDROCK_REGION is missing."""
        import importlib

        import src.handler as handler_module

        monkeypatch.setenv("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")
        monkeypatch.delenv("BEDROCK_REGION", raising=False)

        with pytest.raises(RuntimeError, match="BEDROCK_REGION"):
            importlib.reload(handler_module)

        # Restore env for subsequent tests
        monkeypatch.setenv("BEDROCK_REGION", "eu-north-1")
        importlib.reload(handler_module)

    def test_raises_runtime_error_lists_all_missing(self, monkeypatch):
        """RuntimeError message lists ALL missing variables."""
        import importlib

        import src.handler as handler_module

        monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
        monkeypatch.delenv("BEDROCK_REGION", raising=False)

        with pytest.raises(RuntimeError, match="BEDROCK_MODEL_ID") as exc_info:
            importlib.reload(handler_module)

        # Both variables should be listed
        assert "BEDROCK_MODEL_ID" in str(exc_info.value)
        assert "BEDROCK_REGION" in str(exc_info.value)

        # Restore env for subsequent tests
        monkeypatch.setenv("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")
        monkeypatch.setenv("BEDROCK_REGION", "eu-north-1")
        importlib.reload(handler_module)

    def test_logs_critical_structured_entry(self, monkeypatch, capsys):
        """A structured CRITICAL log entry is emitted before raising."""
        import importlib

        import src.handler as handler_module

        monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
        monkeypatch.setenv("BEDROCK_REGION", "eu-north-1")

        with pytest.raises(RuntimeError):
            importlib.reload(handler_module)

        captured = capsys.readouterr()
        log_entry = json.loads(captured.out)
        assert log_entry["level"] == "CRITICAL"
        assert log_entry["event_type"] == "env_validation_failure"
        assert "BEDROCK_MODEL_ID" in log_entry["missing_vars"]

        # Restore env for subsequent tests
        monkeypatch.setenv("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")
        importlib.reload(handler_module)


# ---------------------------------------------------------------------------
# Test 3: Bedrock API error returns graceful failure message
# Validates: Requirement 1.7, 9.3
# ---------------------------------------------------------------------------

class TestBedrockApiError:
    """When Bedrock raises ClientError, handler returns a graceful message."""

    def test_returns_error_message_on_non_retryable_error(self, mock_bedrock):
        """Handler returns error message for non-retryable ClientError."""
        from src.handler import lambda_handler

        error_response = {
            "Error": {"Code": "AccessDeniedException", "Message": "Not authorized"}
        }
        mock_bedrock.converse.side_effect = ClientError(
            error_response, "InvokeModel"
        )

        event = _make_lex_event()
        result = lambda_handler(event, None)

        assert result["messages"][0]["content"] == (
            "I'm sorry, I couldn't process your request. Please try again."
        )

    @patch("src.handler.time.sleep")
    def test_returns_graceful_message_on_retryable_error_exhausted(self, mock_sleep, mock_bedrock):
        """Handler returns graceful busy message when retries exhausted for ThrottlingException."""
        from src.handler import lambda_handler

        error_response = {
            "Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}
        }
        mock_bedrock.converse.side_effect = ClientError(
            error_response, "InvokeModel"
        )

        event = _make_lex_event()
        result = lambda_handler(event, None)

        assert result["messages"][0]["content"] == (
            "I'm sorry, the service is temporarily busy. Please try again in a moment."
        )


# ---------------------------------------------------------------------------
# Test 4: Empty session attributes initializes default ConversationContext
# Validates: Requirement 2.4
# ---------------------------------------------------------------------------

class TestEmptySessionAttributesInitDefault:
    """Empty session attributes should initialize default ConversationContext."""

    def test_initializes_default_context(self, mock_bedrock):
        """When sessionAttributes is empty, ConversationContext gets default value."""
        from src.handler import lambda_handler

        mock_bedrock.converse.return_value = _make_bedrock_response("Sure!")
        event = _make_lex_event(session_attributes={})

        result = lambda_handler(event, None)

        # The response should contain updated session attributes with ConversationContext
        session_attrs = result["sessionState"]["sessionAttributes"]
        assert "ConversationContext" in session_attrs

        context = json.loads(session_attrs["ConversationContext"])
        # Should contain the default greeting plus the new exchange
        assert "chat_history" in context
        # Default starts with "Human: hi\nAI: Hello! How can I help you?"
        assert "Human: hi" in context["chat_history"]
        assert "AI: Hello! How can I help you?" in context["chat_history"]


# ---------------------------------------------------------------------------
# Test 5: Non-FallbackIntent returns Close without Bedrock invocation
# Validates: Requirement 6.4
# ---------------------------------------------------------------------------

class TestNonFallbackIntent:
    """Non-FallbackIntent events should return Close without calling Bedrock."""

    def test_returns_close_dialog_action(self, mock_bedrock):
        """Response has dialogAction type 'Close'."""
        from src.handler import lambda_handler

        event = _make_lex_event(intent_name="OrderPizza")
        result = lambda_handler(event, None)

        assert result["sessionState"]["dialogAction"]["type"] == "Close"

    def test_bedrock_not_invoked(self, mock_bedrock):
        """Bedrock invoke_model is NOT called for non-FallbackIntent."""
        from src.handler import lambda_handler

        event = _make_lex_event(intent_name="OrderPizza")
        lambda_handler(event, None)

        mock_bedrock.converse.assert_not_called()

    def test_intent_state_fulfilled(self, mock_bedrock):
        """Response intent state is 'Fulfilled'."""
        from src.handler import lambda_handler

        event = _make_lex_event(intent_name="OrderPizza")
        result = lambda_handler(event, None)

        assert result["sessionState"]["intent"]["state"] == "Fulfilled"
        assert result["sessionState"]["intent"]["name"] == "OrderPizza"


# ---------------------------------------------------------------------------
# Test 6: SYSTEM_PROMPT env var overrides default
# Validates: Requirement 7.2
# ---------------------------------------------------------------------------

class TestSystemPromptOverride:
    """When SYSTEM_PROMPT env var is set non-empty, it overrides the default."""

    def test_custom_system_prompt_used(self, mock_bedrock, monkeypatch):
        """The custom SYSTEM_PROMPT is passed to invoke_bedrock."""
        # We need to reload the handler module with the new env var
        import importlib

        import src.handler as handler_module

        monkeypatch.setenv("SYSTEM_PROMPT", "You are a pirate assistant.")
        monkeypatch.setenv("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")

        # Reload the module to pick up new env vars
        importlib.reload(handler_module)

        mock_bedrock_reloaded = MagicMock()
        mock_bedrock_reloaded.converse.return_value = _make_bedrock_response("Arrr!")

        with patch.object(handler_module, "bedrock_runtime", mock_bedrock_reloaded):
            event = _make_lex_event()
            handler_module.lambda_handler(event, None)

            # Verify the Converse request carries the custom system prompt
            call_args = mock_bedrock_reloaded.converse.call_args
            assert call_args.kwargs["system"] == [{"text": "You are a pirate assistant."}]

        # Reload again to restore defaults for other tests
        monkeypatch.setenv("SYSTEM_PROMPT", "")
        importlib.reload(handler_module)


# ---------------------------------------------------------------------------
# Test 7: Empty SYSTEM_PROMPT env var uses default
# Validates: Requirement 7.4
# ---------------------------------------------------------------------------

class TestEmptySystemPromptUsesDefault:
    """When SYSTEM_PROMPT env var is empty, the default system prompt is used."""

    def test_default_prompt_used_when_empty(self, mock_bedrock, monkeypatch):
        """Default system prompt is used when SYSTEM_PROMPT env var is empty."""
        import importlib

        import src.handler as handler_module

        monkeypatch.setenv("SYSTEM_PROMPT", "")
        monkeypatch.setenv("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")

        importlib.reload(handler_module)

        mock_bedrock_reloaded = MagicMock()
        mock_bedrock_reloaded.converse.return_value = _make_bedrock_response("Response")

        with patch.object(handler_module, "bedrock_runtime", mock_bedrock_reloaded):
            event = _make_lex_event()
            handler_module.lambda_handler(event, None)

            call_args = mock_bedrock_reloaded.converse.call_args
            system_blocks = call_args.kwargs["system"]

            # Should use the DEFAULT_SYSTEM_PROMPT
            assert system_blocks == [{"text": handler_module.DEFAULT_SYSTEM_PROMPT}]
            assert "corporate research assistant" in system_blocks[0]["text"]

        # Reload to restore
        importlib.reload(handler_module)


# ---------------------------------------------------------------------------
# Test 8: Malformed ConversationContext JSON re-initializes context
# Validates: Requirement 2.6
# ---------------------------------------------------------------------------

class TestMalformedConversationContext:
    """Malformed JSON in ConversationContext should be handled gracefully."""

    def test_continues_without_error(self, mock_bedrock):
        """Handler processes request normally despite malformed context."""
        from src.handler import lambda_handler

        mock_bedrock.converse.return_value = _make_bedrock_response("Hello there!")
        event = _make_lex_event(
            session_attributes={"ConversationContext": "not valid json {{{"}
        )

        result = lambda_handler(event, None)

        # Should not raise, and should return a valid response
        assert result["messages"][0]["content"] == "Hello there!"
        assert result["messages"][0]["contentType"] == "PlainText"

    def test_context_reinitialized_after_malformed(self, mock_bedrock):
        """Session attributes contain re-initialized context after malformed input."""
        from src.handler import lambda_handler

        mock_bedrock.converse.return_value = _make_bedrock_response("Hi!")
        event = _make_lex_event(
            session_attributes={"ConversationContext": "{{invalid"}
        )

        result = lambda_handler(event, None)

        session_attrs = result["sessionState"]["sessionAttributes"]
        context = json.loads(session_attrs["ConversationContext"])

        # Should contain chat_history with the default greeting + new exchange
        assert "chat_history" in context
        assert "Human: hi" in context["chat_history"]
        assert "AI: Hello! How can I help you?" in context["chat_history"]
