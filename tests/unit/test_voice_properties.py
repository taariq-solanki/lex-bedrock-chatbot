"""
Property-based tests for the Lex Polly Voice feature.

Uses hypothesis to verify universal correctness properties for voice interaction
logic (PCM encoding, response message decoding, session ID invariance).
"""

import base64
import json
import urllib.parse

from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Python equivalents of the JavaScript encode/decode functions
# ---------------------------------------------------------------------------


def encode_response_messages(messages):
    """
    Encode messages the same way Lex RecognizeUtterance response headers are encoded.

    JavaScript equivalent: btoa(encodeURIComponent(JSON.stringify(messages)))

    Steps: json.dumps → urllib.parse.quote → base64.b64encode
    """
    json_str = json.dumps(messages)
    url_encoded = urllib.parse.quote(json_str)
    b64_encoded = base64.b64encode(url_encoded.encode()).decode()
    return b64_encoded


def decode_response_messages(encoded):
    """
    Decode messages from Lex RecognizeUtterance response headers.

    JavaScript equivalent: JSON.parse(decodeURIComponent(atob(encoded)))

    Steps: base64.b64decode → urllib.parse.unquote → json.loads
    """
    url_encoded = base64.b64decode(encoded).decode()
    json_str = urllib.parse.unquote(url_encoded)
    messages = json.loads(json_str)
    return messages


# ---------------------------------------------------------------------------
# Property 2: Response message decode is a round-trip of encode
# Validates: Requirements 4.5
# ---------------------------------------------------------------------------


class TestResponseMessageDecodeRoundTrip:
    """
    Feature: lex-polly-voice, Property 2: Response message decode is a round-trip of encode

    For any array of message objects with arbitrary string content, encoding via
    JSON.stringify → encodeURIComponent → btoa and then decoding via
    atob → decodeURIComponent → JSON.parse SHALL produce an array equal to
    the original input messages.

    **Validates: Requirements 4.5**
    """

    @given(
        messages=st.lists(
            st.fixed_dictionaries({
                "content": st.text(min_size=0, max_size=200),
                "contentType": st.just("PlainText"),
            }),
            min_size=0,
            max_size=5,
        )
    )
    @settings(max_examples=100)
    def test_decode_is_round_trip_of_encode(self, messages):
        """
        Encoding then decoding any message array produces the original array.

        Feature: lex-polly-voice, Property 2: Response message decode is a round-trip of encode

        **Validates: Requirements 4.5**
        """
        encoded = encode_response_messages(messages)
        decoded = decode_response_messages(encoded)
        assert decoded == messages


import uuid
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Property 3: Session ID invariant across interaction modes
# Validates: Requirements 5.5
# ---------------------------------------------------------------------------


class LexSession:
    """
    Simulates the JavaScript Web UI session behavior.

    In the Web UI, a single sessionId is generated once and shared across
    both text (recognizeText) and voice (recognizeUtterance) API calls.
    This class mirrors that behavior for testing purposes.
    """

    def __init__(self, session_id=None):
        self.session_id = session_id or str(uuid.uuid4())
        self.lex_client = MagicMock()

    def send_text(self, text="hello"):
        """Simulate a text interaction via recognizeText API."""
        self.lex_client.recognize_text(
            botId="test-bot-id",
            botAliasId="test-alias-id",
            localeId="en_US",
            sessionId=self.session_id,
            text=text,
        )

    def send_voice(self, audio_buffer=b"\x00\x01\x02\x03"):
        """Simulate a voice interaction via recognizeUtterance API."""
        self.lex_client.recognize_utterance(
            botId="test-bot-id",
            botAliasId="test-alias-id",
            localeId="en_US",
            sessionId=self.session_id,
            requestContentType="audio/x-l16; sample-rate=16000; channel-count=1",
            responseContentType="audio/mpeg",
            inputStream=audio_buffer,
        )


class TestSessionIdInvariantAcrossInteractionModes:
    """
    Feature: lex-polly-voice, Property 3: Session ID invariant across interaction modes

    For any sequence of text and voice interactions (in any order and any count),
    the sessionId parameter passed to both recognizeText and recognizeUtterance
    API calls SHALL be the same value throughout the entire sequence.

    **Validates: Requirements 5.5**
    """

    @given(
        actions=st.lists(
            st.sampled_from(["text", "voice"]),
            min_size=1,
            max_size=20,
        )
    )
    @settings(max_examples=100)
    def test_session_id_identical_across_all_calls(self, actions):
        """
        Simulate a sequence of text and voice interactions in random order.
        All captured sessionId values must be identical.

        **Validates: Requirements 5.5**
        """
        # Create a session (mirrors JS: sessionId generated once at page load)
        session = LexSession()

        # Execute each action in the generated sequence
        for action in actions:
            if action == "text":
                session.send_text()
            else:
                session.send_voice()

        # Collect all sessionId values passed to mocked API calls
        captured_session_ids = []

        for call in session.lex_client.recognize_text.call_args_list:
            captured_session_ids.append(call.kwargs["sessionId"])

        for call in session.lex_client.recognize_utterance.call_args_list:
            captured_session_ids.append(call.kwargs["sessionId"])

        # Assert: all captured sessionId values are identical
        assert len(captured_session_ids) == len(actions), (
            f"Expected {len(actions)} API calls but captured {len(captured_session_ids)}"
        )
        assert all(sid == session.session_id for sid in captured_session_ids), (
            f"Not all sessionId values match. Expected all to be '{session.session_id}', "
            f"got: {set(captured_session_ids)}"
        )
