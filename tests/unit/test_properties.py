"""
Property-based tests for the Lex Bedrock Chatbot Lambda handler.

Uses hypothesis to verify universal correctness properties across generated inputs.
"""

import json
import os

# Set required env vars BEFORE importing handler
os.environ.setdefault("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")
os.environ.setdefault("BEDROCK_REGION", "eu-north-1")
os.environ.setdefault("SYSTEM_PROMPT", "")

# Fix broken pydantic hypothesis plugin: patch importlib.metadata.entry_points
# before hypothesis can load it during its __init__.py
import importlib.metadata as _md

_original_entry_points = _md.entry_points


def _filtered_entry_points(**kwargs):
    """Filter out broken pydantic hypothesis plugin from entry points."""
    result = _original_entry_points(**kwargs)
    if kwargs.get('group') == 'hypothesis' or not kwargs:

        class _FilteredEPs:
            def __init__(self, eps):
                self._eps = eps

            def select(self, **kw):
                selected = self._eps.select(**kw) if hasattr(self._eps, 'select') else self._eps
                return [e for e in selected if 'pydantic' not in str(e)]

            def get(self, key, default=None):
                if hasattr(self._eps, 'get'):
                    entries = self._eps.get(key, default)
                else:
                    entries = default
                if entries and key == 'hypothesis':
                    return [e for e in entries if 'pydantic' not in str(e)]
                return entries

            def __iter__(self):
                return iter(
                    [e for e in self._eps
                     if 'pydantic' not in str(e) or getattr(e, 'group', '') != 'hypothesis']
                )

            def __getattr__(self, name):
                return getattr(self._eps, name)

        return _FilteredEPs(result)
    return result


_md.entry_points = _filtered_entry_points

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

# Restore original after hypothesis is loaded
_md.entry_points = _original_entry_points

from unittest.mock import MagicMock, patch

# Mock boto3 client before importing handler
mock_bedrock_client = MagicMock()
with patch("boto3.client", return_value=mock_bedrock_client):
    from src.handler import (
        get_conversation_context,
        lambda_handler,
        update_conversation_context,
    )


# ---------------------------------------------------------------------------
# Property 4: Context serialization round-trip
# Validates: Requirements 2.3
# ---------------------------------------------------------------------------


class TestContextSerializationRoundTrip:
    """
    Property 4: Context serialization round-trip.

    For any valid ConversationContext object (containing a chat_history string
    field), serializing to JSON and then deserializing via
    get_conversation_context SHALL produce an object with an identical
    chat_history value.

    **Validates: Requirements 2.3**
    """

    @given(chat_history=st.text())
    @settings(max_examples=100)
    def test_round_trip_preserves_chat_history(self, chat_history):
        """
        Serializing a context dict to JSON, placing it in session attributes,
        then calling get_conversation_context produces the same chat_history.

        **Validates: Requirements 2.3**
        """
        # Construct a context dict with the random chat_history
        context = {"chat_history": chat_history}

        # Serialize to JSON (simulating what handler does before storing)
        serialized = json.dumps(context)

        # Place in session attributes (simulating Lex session state)
        session_attributes = {"ConversationContext": serialized}

        # Deserialize via the handler function
        result = get_conversation_context(session_attributes)

        # Assert: the round-trip preserves the chat_history value
        assert result["chat_history"] == chat_history


# ---------------------------------------------------------------------------
# Property 5: Truncation maintains size invariant
# Validates: Requirements 2.5
# ---------------------------------------------------------------------------


class TestTruncationMaintainsSizeInvariant:
    """
    Property 5: For any conversation context that exceeds 10,000 characters
    after an update, the truncation function SHALL produce a result that:
    - Has total length <= 10,000 characters
    - Contains only complete exchange pairs (no partial Human/AI turns)
    - Retains the most recent exchanges (oldest are removed first)

    **Validates: Requirements 2.5**
    """

    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.data_too_large, HealthCheck.too_slow],
    )
    @given(
        num_pairs=st.integers(min_value=12, max_value=20),
        pair_size=st.integers(min_value=300, max_value=500),
        new_user_input=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz ",
            min_size=10,
            max_size=50,
        ),
        new_ai_response=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz ",
            min_size=10,
            max_size=50,
        ),
    )
    def test_truncation_size_invariant(self, num_pairs, pair_size, new_user_input, new_ai_response):
        """After truncation, chat_history is always <= 10,000 characters."""
        # Build exchange pairs with fixed-length text to guarantee exceeding 10k
        pairs = []
        for i in range(num_pairs):
            user_text = "a" * pair_size + f" msg{i}"
            ai_text = "b" * pair_size + f" reply{i}"
            pairs.append((user_text, ai_text))

        chat_history = "\n".join(f"Human: {u}\nAI: {a}" for u, a in pairs)

        # Ensure the generated data actually exceeds 10,000 chars
        full_history = chat_history + f"\nHuman: {new_user_input}\nAI: {new_ai_response}"
        assume(len(full_history) > 10000)

        context = {"chat_history": chat_history}
        result = update_conversation_context(context, new_user_input, new_ai_response)

        # Assert: Size invariant - result must be <= 10,000 chars
        assert len(result["chat_history"]) <= 10000, (
            f"chat_history length {len(result['chat_history'])} exceeds 10,000 char limit"
        )

    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.data_too_large, HealthCheck.too_slow],
    )
    @given(
        num_pairs=st.integers(min_value=12, max_value=20),
        pair_size=st.integers(min_value=300, max_value=500),
        new_user_input=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz ",
            min_size=10,
            max_size=50,
        ),
        new_ai_response=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz ",
            min_size=10,
            max_size=50,
        ),
    )
    def test_truncation_complete_exchange_pairs(self, num_pairs, pair_size, new_user_input, new_ai_response):
        """After truncation, result contains only complete exchange pairs."""
        pairs = []
        for i in range(num_pairs):
            user_text = "a" * pair_size + f" msg{i}"
            ai_text = "b" * pair_size + f" reply{i}"
            pairs.append((user_text, ai_text))

        chat_history = "\n".join(f"Human: {u}\nAI: {a}" for u, a in pairs)
        full_history = chat_history + f"\nHuman: {new_user_input}\nAI: {new_ai_response}"
        assume(len(full_history) > 10000)

        context = {"chat_history": chat_history}
        result = update_conversation_context(context, new_user_input, new_ai_response)

        result_history = result["chat_history"]

        # Assert: Every "Human: " has a corresponding "AI: " response
        human_count = result_history.count("Human: ")
        ai_count = result_history.count("AI: ")
        assert human_count == ai_count, (
            f"Mismatch: {human_count} Human turns but {ai_count} AI turns. "
            f"Exchange pairs are incomplete."
        )

        # Additionally verify no orphaned "Human: " at the end without "AI: "
        # by checking the structure: each "Human: ..." segment contains "AI: "
        parts = result_history.split("\nHuman: ")
        for part in parts:
            if part and part.strip():
                if not part.startswith("Human: "):
                    assert "AI: " in part, (
                        f"Found orphaned Human turn without AI response in: {part[:100]}..."
                    )

    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.data_too_large, HealthCheck.too_slow],
    )
    @given(
        num_pairs=st.integers(min_value=12, max_value=20),
        pair_size=st.integers(min_value=300, max_value=500),
        new_user_input=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz ",
            min_size=10,
            max_size=50,
        ),
        new_ai_response=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz ",
            min_size=10,
            max_size=50,
        ),
    )
    def test_truncation_retains_most_recent_exchange(self, num_pairs, pair_size, new_user_input, new_ai_response):
        """After truncation, the most recent exchange (new input/response) is always retained."""
        pairs = []
        for i in range(num_pairs):
            user_text = "a" * pair_size + f" msg{i}"
            ai_text = "b" * pair_size + f" reply{i}"
            pairs.append((user_text, ai_text))

        chat_history = "\n".join(f"Human: {u}\nAI: {a}" for u, a in pairs)
        full_history = chat_history + f"\nHuman: {new_user_input}\nAI: {new_ai_response}"
        assume(len(full_history) > 10000)

        context = {"chat_history": chat_history}
        result = update_conversation_context(context, new_user_input, new_ai_response)

        result_history = result["chat_history"]

        # Assert: The most recent exchange is present in the result
        assert f"Human: {new_user_input}" in result_history, (
            "Most recent user input not found in truncated result"
        )
        assert f"AI: {new_ai_response}" in result_history, (
            "Most recent AI response not found in truncated result"
        )

        # Verify the new exchange is at the end
        assert result_history.endswith(f"AI: {new_ai_response}"), (
            "Most recent AI response should be at the end of chat_history"
        )


# ---------------------------------------------------------------------------
# Property 3: Context update preserves exchange format
# Validates: Requirements 1.6, 2.2
# ---------------------------------------------------------------------------


class TestContextUpdatePreservesExchangeFormat:
    """
    Property 3: Context update preserves exchange format.

    For any existing conversation context string, any non-empty user input, and
    any non-empty AI response, updating the conversation context SHALL produce a
    string where the appended portion matches the pattern
    "Human: {input}\\nAI: {response}" and the previous history is preserved as a
    prefix.

    **Validates: Requirements 1.6, 2.2**
    """

    @given(
        existing_history=st.text(),
        user_input=st.text(min_size=1),
        ai_response=st.text(min_size=1),
    )
    @settings(max_examples=100)
    def test_appended_portion_matches_exchange_pattern(self, existing_history, user_input, ai_response):
        """
        The appended portion matches "Human: {input}\\nAI: {response}" pattern.

        **Validates: Requirements 1.6, 2.2**
        """
        # Filter out inputs containing markers to avoid false positives with
        # prefix detection (truncation splits on these markers)
        assume("Human: " not in user_input)
        assume("AI: " not in ai_response)
        assume("\nHuman: " not in existing_history)
        assume("\nAI: " not in existing_history)

        # Construct context
        context = {"chat_history": existing_history}

        # Call the function under test
        result = update_conversation_context(context, user_input, ai_response)
        result_history = result["chat_history"]

        # Assert: The result ends with the expected exchange pattern
        # (The most recent exchange is always preserved even after truncation)
        assert result_history.endswith(f"Human: {user_input}\nAI: {ai_response}"), (
            f"Result should end with the latest exchange.\n"
            f"Expected suffix: 'Human: {user_input}\\nAI: {ai_response}'\n"
            f"Actual result (last 200 chars): '{result_history[-200:]}'"
        )

    @given(
        existing_history=st.text(max_size=5000),
        user_input=st.text(min_size=1, max_size=200),
        ai_response=st.text(min_size=1, max_size=200),
    )
    @settings(max_examples=100)
    def test_previous_history_preserved_as_prefix(self, existing_history, user_input, ai_response):
        """
        When total length is within the 10,000-char limit, the original history
        is preserved as a prefix in the result.

        **Validates: Requirements 1.6, 2.2**
        """
        # Filter out inputs containing markers to avoid ambiguity
        assume("Human: " not in user_input)
        assume("AI: " not in ai_response)
        assume("\nHuman: " not in existing_history)
        assume("\nAI: " not in existing_history)

        # Construct context
        context = {"chat_history": existing_history}

        # Calculate what the full history would be before any truncation
        expected_exchange = f"\nHuman: {user_input}\nAI: {ai_response}"
        full_history = existing_history + expected_exchange

        # Only assert prefix preservation when total would be under the limit
        assume(len(full_history) <= 10000)

        # Call the function under test
        result = update_conversation_context(context, user_input, ai_response)
        result_history = result["chat_history"]

        # Assert: The original history is preserved as a prefix
        assert result_history == full_history, (
            f"When total length <= 10000, original history should be preserved.\n"
            f"Expected: '{full_history[:200]}...'\n"
            f"Actual: '{result_history[:200]}...'"
        )


# ---------------------------------------------------------------------------
# Property 6: Malformed JSON recovery
# Validates: Requirements 2.6
# ---------------------------------------------------------------------------


def _is_valid_json(s):
    """Helper to check if a string is valid JSON."""
    try:
        json.loads(s)
        return True
    except (json.JSONDecodeError, TypeError, ValueError):
        return False


class TestMalformedJsonRecovery:
    """
    Property 6: Malformed JSON recovery.

    For any string that is not valid JSON, attempting to retrieve the
    conversation context SHALL produce the default initialized context
    (a JSON object with chat_history set to the default greeting prompt),
    rather than raising an exception.

    **Validates: Requirements 2.6**
    """

    @given(malformed=st.text(min_size=1).filter(lambda s: not _is_valid_json(s)))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_malformed_json_returns_default_context(self, malformed):
        """
        Any string that fails json.loads() placed in ConversationContext should
        result in get_conversation_context returning the default context with
        the greeting prompt, without raising an exception.

        **Validates: Requirements 2.6**
        """
        # Place malformed string in session attributes
        session_attributes = {"ConversationContext": malformed}

        # Call get_conversation_context — must not raise
        result = get_conversation_context(session_attributes)

        # Assert: returns the default initialized context
        expected_default = {"chat_history": "Human: hi\nAI: Hello! How can I help you?"}
        assert result == expected_default, (
            f"Expected default context {expected_default}, got {result} "
            f"for malformed input: {malformed!r}"
        )

    @given(
        malformed=st.sampled_from([
            "{",
            "[",
            '"unclosed',
            "{'single': 'quotes'}",
            "{key: value}",
            "null bytes \x00\x01\x02",
            "random text that is not json",
            '{"incomplete": ',
            "[1, 2, 3",
            '{"nested": {"broken": }',
        ])
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_known_malformed_patterns_return_default(self, malformed):
        """
        Specific patterns known to fail json.loads() (partial JSON, plain text,
        binary-like data) should return the default context.

        **Validates: Requirements 2.6**
        """
        # Verify our test data is actually invalid JSON
        assume(not _is_valid_json(malformed))

        session_attributes = {"ConversationContext": malformed}

        # Must not raise
        result = get_conversation_context(session_attributes)

        # Assert: returns the default initialized context
        expected_default = {"chat_history": "Human: hi\nAI: Hello! How can I help you?"}
        assert result == expected_default, (
            f"Expected default context for malformed input: {malformed!r}"
        )


# ---------------------------------------------------------------------------
# Property 7: Non-FallbackIntent routing
# Validates: Requirements 6.4
# ---------------------------------------------------------------------------


class TestNonFallbackIntentRouting:
    """
    Property 7: Non-FallbackIntent routing.

    For any Lex V2 event whose intent name is NOT "FallbackIntent", the
    lambda_handler SHALL return a Close dialog action and SHALL NOT invoke the
    Bedrock client.

    **Validates: Requirements 6.4**
    """

    @given(
        intent_name=st.text(min_size=1, max_size=50).filter(lambda s: s != "FallbackIntent")
    )
    @settings(max_examples=100)
    def test_non_fallback_intent_returns_close_without_bedrock(self, intent_name):
        """
        Any intent name other than "FallbackIntent" should result in a Close
        dialog action response, and the Bedrock client's invoke_model should
        NOT be called.

        **Validates: Requirements 6.4**
        """
        # Construct a Lex V2 event with the generated intent name
        event = {
            "sessionId": "test-session",
            "inputTranscript": "some text",
            "bot": {"id": "test", "name": "test-bot", "localeId": "en_US", "version": "DRAFT"},
            "sessionState": {
                "intent": {"name": intent_name, "state": "InProgress"},
                "sessionAttributes": {}
            },
            "requestAttributes": {}
        }

        # Patch the bedrock_runtime client at module level
        with patch("src.handler.bedrock_runtime") as mock_bedrock:
            result = lambda_handler(event, None)

            # Assert 1: Response contains Close dialog action
            assert result["sessionState"]["dialogAction"]["type"] == "Close", (
                f"Expected dialogAction type 'Close' for intent '{intent_name}', "
                f"got '{result['sessionState']['dialogAction']['type']}'"
            )

            # Assert 2: Bedrock invoke_model was NOT called
            mock_bedrock.converse.assert_not_called()
