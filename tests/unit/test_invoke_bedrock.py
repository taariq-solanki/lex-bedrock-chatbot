"""Unit tests for invoke_bedrock function (Bedrock Converse API)."""

from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    """Set required environment variables before importing handler."""
    monkeypatch.setenv("BEDROCK_MODEL_ID", "us.amazon.nova-pro-v1:0")
    monkeypatch.setenv("BEDROCK_REGION", "us-east-1")


@pytest.fixture
def mock_bedrock_client():
    """Mock the bedrock_runtime client."""
    with patch("src.handler.bedrock_runtime") as mock_client:
        yield mock_client


def _converse_response(text):
    """Build a Bedrock Converse API response envelope with the given text."""
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"text": text}],
            }
        },
        "stopReason": "end_turn",
    }


class TestInvokeBedrockSuccess:
    """Tests for successful Bedrock invocations."""

    def test_returns_generated_text(self, mock_bedrock_client):
        """invoke_bedrock returns text from the Converse response."""
        from src.handler import invoke_bedrock

        mock_bedrock_client.converse.return_value = _converse_response(
            "Tesla is an electric vehicle company."
        )

        messages = [{"role": "user", "content": [{"type": "text", "text": "Tell me about Tesla"}]}]
        result = invoke_bedrock(messages, "You are a helpful assistant.")

        assert result == "Tesla is an electric vehicle company."

    def test_calls_converse_with_correct_payload(self, mock_bedrock_client):
        """invoke_bedrock sends a correct Converse API request."""
        from src.handler import invoke_bedrock

        mock_bedrock_client.converse.return_value = _converse_response("Response")

        messages = [{"role": "user", "content": [{"type": "text", "text": "Hello"}]}]
        system_prompt = "You are helpful."
        invoke_bedrock(messages, system_prompt)

        import src.handler as handler_module

        call_args = mock_bedrock_client.converse.call_args
        kwargs = call_args.kwargs

        # modelId reflects whatever the handler resolved at import time
        assert kwargs["modelId"] == handler_module.BEDROCK_MODEL_ID
        assert kwargs["inferenceConfig"]["maxTokens"] == 1024
        # System prompt passed in Converse format
        assert kwargs["system"] == [{"text": "You are helpful."}]
        # Messages converted to Converse content blocks (no "type" field)
        assert kwargs["messages"] == [{"role": "user", "content": [{"text": "Hello"}]}]


class TestInvokeBedrockErrors:
    """Tests for error handling in invoke_bedrock."""

    def test_client_error_raises(self, mock_bedrock_client):
        """invoke_bedrock raises ClientError so retry wrapper can handle it."""
        from src.handler import invoke_bedrock

        error_response = {
            "Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}
        }
        mock_bedrock_client.converse.side_effect = ClientError(
            error_response, "Converse"
        )

        messages = [{"role": "user", "content": [{"type": "text", "text": "Hello"}]}]

        with pytest.raises(ClientError):
            invoke_bedrock(messages, "System prompt")

    def test_empty_content_returns_fallback_message(self, mock_bedrock_client):
        """invoke_bedrock returns fallback when the response has no text."""
        from src.handler import invoke_bedrock

        mock_bedrock_client.converse.return_value = {
            "output": {"message": {"role": "assistant", "content": []}}
        }

        messages = [{"role": "user", "content": [{"type": "text", "text": "Hello"}]}]
        result = invoke_bedrock(messages, "System prompt")

        assert result == "I'm sorry, I didn't get a valid response. Please try again."

    def test_missing_output_key_returns_fallback_message(self, mock_bedrock_client):
        """invoke_bedrock returns fallback when the output structure is missing."""
        from src.handler import invoke_bedrock

        mock_bedrock_client.converse.return_value = {}

        messages = [{"role": "user", "content": [{"type": "text", "text": "Hello"}]}]
        result = invoke_bedrock(messages, "System prompt")

        assert result == "I'm sorry, I didn't get a valid response. Please try again."

    def test_non_retryable_error_handled_by_retry_wrapper(self, mock_bedrock_client):
        """invoke_bedrock_with_retry returns error message for non-retryable ClientError."""
        from src.handler import invoke_bedrock_with_retry

        error_response = {
            "Error": {"Code": "AccessDeniedException", "Message": "Not authorized"}
        }
        mock_bedrock_client.converse.side_effect = ClientError(
            error_response, "Converse"
        )

        messages = [{"role": "user", "content": [{"type": "text", "text": "Hello"}]}]

        with patch("src.handler.structured_logger") as mock_logger:
            result = invoke_bedrock_with_retry(messages, "System prompt")
            assert result == "I'm sorry, I couldn't process your request. Please try again."
            mock_logger.error.assert_called_once()
            call_kwargs = mock_logger.error.call_args
            assert call_kwargs.kwargs["error_type"] == "AccessDeniedException"
            assert call_kwargs.kwargs["error_message"] == "Not authorized"
