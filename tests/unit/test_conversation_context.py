"""
Unit tests for conversation memory management functions (Task 2.3).

Tests get_conversation_context and update_conversation_context.
"""

import json
import os
import sys

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

# Set required env vars before importing handler
os.environ.setdefault("BEDROCK_MODEL_ID", "test-model")
os.environ.setdefault("BEDROCK_REGION", "eu-north-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from unittest.mock import patch

# Patch boto3 client before importing handler
with patch("boto3.client"):
    from handler import get_conversation_context, update_conversation_context


class TestGetConversationContext:
    """Tests for get_conversation_context."""

    def test_missing_key_initializes_default(self):
        """When ConversationContext key is absent, returns default context."""
        session_attributes = {}
        result = get_conversation_context(session_attributes)
        assert result == {"chat_history": "Human: hi\nAI: Hello! How can I help you?"}

    def test_valid_json_returns_deserialized(self):
        """When key has valid JSON, returns the deserialized dict."""
        context_data = {"chat_history": "Human: hello\nAI: Hi there!"}
        session_attributes = {"ConversationContext": json.dumps(context_data)}
        result = get_conversation_context(session_attributes)
        assert result == context_data

    def test_malformed_json_reinitializes_default(self):
        """When key has malformed JSON, logs warning and returns default."""
        session_attributes = {"ConversationContext": "not valid json {{{"}
        result = get_conversation_context(session_attributes)
        assert result == {"chat_history": "Human: hi\nAI: Hello! How can I help you?"}

    def test_empty_string_does_not_reinitialize(self):
        """An empty string value does NOT trigger re-initialization."""
        session_attributes = {"ConversationContext": ""}
        result = get_conversation_context(session_attributes)
        # Should NOT return the default context (that would be re-initialization)
        assert result != {"chat_history": "Human: hi\nAI: Hello! How can I help you?"}
        # Should return a context with empty chat_history
        assert result == {"chat_history": ""}

    def test_valid_complex_context(self):
        """When key has valid JSON with multiple turns, returns correctly."""
        context_data = {
            "chat_history": "Human: Tell me about Tesla\nAI: Tesla is a company.\nHuman: Who founded it?\nAI: Elon Musk co-founded it."
        }
        session_attributes = {"ConversationContext": json.dumps(context_data)}
        result = get_conversation_context(session_attributes)
        assert result == context_data


class TestUpdateConversationContext:
    """Tests for update_conversation_context."""

    def test_appends_new_exchange(self):
        """Appends Human/AI exchange to chat_history."""
        context = {"chat_history": "Human: hi\nAI: Hello! How can I help you?"}
        result = update_conversation_context(context, "Tell me about Google", "Google is a tech company.")
        expected = "Human: hi\nAI: Hello! How can I help you?\nHuman: Tell me about Google\nAI: Google is a tech company."
        assert result["chat_history"] == expected

    def test_returns_same_context_dict(self):
        """Returns the updated context dict (mutated in-place)."""
        context = {"chat_history": "Human: hi\nAI: Hello!"}
        result = update_conversation_context(context, "test", "response")
        assert result is context

    def test_truncation_when_exceeds_limit(self):
        """When chat_history exceeds 10,000 chars, removes oldest pairs."""
        # Create a context that will exceed 10,000 chars after update
        # Each pair is roughly "Human: X\nAI: Y" where X and Y are long strings
        long_response = "A" * 500
        pairs = []
        for i in range(25):
            pairs.append(f"Human: question {i}\nAI: {long_response}")
        
        context = {"chat_history": "\n".join(pairs)}
        
        # This should already be over 10k, and after update it'll be even longer
        result = update_conversation_context(context, "new question", "new answer " + "B" * 500)
        
        # Result should be within 10,000 chars
        assert len(result["chat_history"]) <= 10000

    def test_truncation_preserves_complete_pairs(self):
        """Truncation only removes complete Human/AI pairs."""
        long_response = "A" * 500
        pairs = []
        for i in range(25):
            pairs.append(f"Human: question {i}\nAI: {long_response}")
        
        context = {"chat_history": "\n".join(pairs)}
        result = update_conversation_context(context, "new q", "new a " + "B" * 500)
        
        # Verify all remaining content is complete pairs
        history = result["chat_history"]
        # Each segment should start with "Human:" and contain "AI:"
        segments = history.split("\nHuman: ")
        # First segment starts with "Human: "
        segments[0] = segments[0].removeprefix("Human: ")
        
        for segment in segments:
            if segment:
                assert "AI: " in segment, f"Incomplete pair found: {segment[:50]}..."

    def test_truncation_retains_newest(self):
        """After truncation, the most recent exchange is preserved."""
        long_response = "A" * 500
        pairs = []
        for i in range(25):
            pairs.append(f"Human: question {i}\nAI: {long_response}")
        
        context = {"chat_history": "\n".join(pairs)}
        result = update_conversation_context(context, "final question", "final answer")
        
        # The newest exchange should be present
        assert "Human: final question" in result["chat_history"]
        assert "AI: final answer" in result["chat_history"]

    def test_no_truncation_when_within_limit(self):
        """When under 10,000 chars, no truncation occurs."""
        context = {"chat_history": "Human: hi\nAI: Hello!"}
        result = update_conversation_context(context, "test", "response")
        expected = "Human: hi\nAI: Hello!\nHuman: test\nAI: response"
        assert result["chat_history"] == expected
