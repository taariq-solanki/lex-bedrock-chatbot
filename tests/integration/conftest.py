"""Integration test configuration.

Provides CLI options and shared fixtures for deployed stack testing.

Usage:
    pytest tests/integration/ --stack-name staging-bedrock-chatbot --region eu-central-1
"""

import boto3
import pytest


def pytest_addoption(parser):
    """Add custom CLI options for integration tests."""
    parser.addoption("--stack-name", required=True, help="CloudFormation stack name")
    parser.addoption("--region", default="eu-central-1", help="AWS region")


@pytest.fixture(scope="session")
def stack_name(request):
    """Return the CloudFormation stack name from CLI args."""
    return request.config.getoption("--stack-name")


@pytest.fixture(scope="session")
def region(request):
    """Return the AWS region from CLI args."""
    return request.config.getoption("--region")


@pytest.fixture(scope="session")
def stack_outputs(stack_name, region):
    """Retrieve stack outputs from CloudFormation."""
    cfn = boto3.client("cloudformation", region_name=region)
    response = cfn.describe_stacks(StackName=stack_name)
    outputs = response["Stacks"][0]["Outputs"]
    return {o["OutputKey"]: o["OutputValue"] for o in outputs}
