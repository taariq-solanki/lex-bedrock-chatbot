"""Integration tests for deployed Bedrock Chatbot stack.

These tests verify the deployed system works end-to-end.
They require a deployed CloudFormation stack and valid AWS credentials.

Usage:
    pytest tests/integration/ --stack-name staging-bedrock-chatbot --region eu-central-1

Validates: Requirements 16.1, 16.2, 16.3, 16.4
"""

import urllib.error
import urllib.request

import boto3


class TestLexBotInvocation:
    """Test 1: Verify Lex bot responds to FallbackIntent via Bedrock.

    Validates: Requirements 16.1, 16.2
    """

    def test_lex_bot_returns_non_empty_response(self, stack_outputs, region):
        """Invoke Lex bot and verify non-empty, non-error response.

        Sends a general knowledge question that will trigger FallbackIntent
        (NLU confidence < 0.40), which invokes the Lambda→Bedrock chain.
        Verifies the response is non-empty and not an error message.
        """
        bot_id = stack_outputs["LexBotId"]
        bot_alias_id = stack_outputs["LexBotAliasId"]

        lex_client = boto3.client("lexv2-runtime", region_name=region)
        response = lex_client.recognize_text(
            botId=bot_id,
            botAliasId=bot_alias_id,
            localeId="en_US",
            sessionId="integration-test-session",
            text="Tell me about Amazon",
        )

        messages = response.get("messages", [])
        assert len(messages) > 0, "Expected at least one message in response"

        content = messages[0].get("content", "")
        assert len(content) > 0, "Expected non-empty response content"
        # Verify it's not a generic error message
        assert "error" not in content.lower() or "sorry" not in content.lower()[:50], (
            f"Response appears to be an error: {content[:100]}"
        )


class TestCloudFrontWebUI:
    """Test 2: Verify CloudFront serves Web UI.

    Validates: Requirement 16.3
    """

    def test_cloudfront_returns_200(self, stack_outputs):
        """GET CloudFront URL and verify HTTP 200.

        Fetches the Web UI index page from the CloudFront distribution
        and asserts that it returns a valid HTML response.
        """
        cloudfront_url = stack_outputs["WebUIHttpsUrl"]

        req = urllib.request.Request(cloudfront_url)
        with urllib.request.urlopen(req, timeout=10) as response:
            assert response.status == 200, f"Expected 200, got {response.status}"
            body = response.read().decode("utf-8")
            assert len(body) > 0, "Expected non-empty response body"
            # Basic check that it's an HTML page
            assert "<html" in body.lower() or "<!doctype" in body.lower(), (
                "Response doesn't appear to be HTML"
            )
