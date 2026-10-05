#!/bin/bash
# deploy-webui.sh
# Deploys the Lex Web UI by:
# 1. Reading stack outputs (Bot ID, Alias ID, Cognito Pool ID, S3 bucket, CloudFront)
# 2. Injecting config into index.html
# 3. Uploading to S3
# 4. Invalidating CloudFront cache
# 5. Printing the HTTPS Web UI URL

set -e

STACK_NAME="${1:-staging-bedrock-chatbot}"
REGION="${2:-eu-central-1}"

echo "=== Deploying Lex Web UI ==="
echo "Stack: $STACK_NAME"
echo "Region: $REGION"
echo ""

# Get stack outputs
echo "Fetching stack outputs..."
OUTPUTS=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "Stacks[0].Outputs" \
    --output json)

get_output() {
    echo "$OUTPUTS" | python3 -c "
import sys, json
outputs = json.load(sys.stdin)
for o in outputs:
    if o['OutputKey'] == '$1':
        print(o['OutputValue'])
        break
"
}

BOT_ID=$(get_output "LexBotId")
ALIAS_ID=$(get_output "LexBotAliasId")
COGNITO_POOL_ID=$(get_output "CognitoIdentityPoolId")
BUCKET_NAME=$(get_output "WebUIBucketName")
WEBUI_URL=$(get_output "WebUIUrl")
WEBUI_HTTPS_URL=$(get_output "WebUIHttpsUrl")

if [ -z "$BOT_ID" ] || [ -z "$ALIAS_ID" ] || [ -z "$COGNITO_POOL_ID" ] || [ -z "$BUCKET_NAME" ]; then
    echo "ERROR: Could not retrieve all required stack outputs."
    echo "  Bot ID: $BOT_ID"
    echo "  Alias ID: $ALIAS_ID"
    echo "  Cognito Pool: $COGNITO_POOL_ID"
    echo "  Bucket: $BUCKET_NAME"
    echo ""
    echo "Make sure the stack '$STACK_NAME' is deployed and has the Cognito/WebUI resources."
    exit 1
fi

echo "  Bot ID: $BOT_ID"
echo "  Alias ID: $ALIAS_ID"
echo "  Cognito Pool: $COGNITO_POOL_ID"
echo "  Bucket: $BUCKET_NAME"
echo ""

# Generate index.html with injected config
echo "Generating configured index.html..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DIST_DIR="$SCRIPT_DIR/webui/dist"
mkdir -p "$DIST_DIR"

sed -e "s|{{REGION}}|$REGION|g" \
    -e "s|{{COGNITO_IDENTITY_POOL_ID}}|$COGNITO_POOL_ID|g" \
    -e "s|{{LEX_BOT_ID}}|$BOT_ID|g" \
    -e "s|{{LEX_BOT_ALIAS_ID}}|$ALIAS_ID|g" \
    "$SCRIPT_DIR/webui/index.html" > "$DIST_DIR/index.html"

echo "Uploading to S3..."
aws s3 cp "$DIST_DIR/index.html" "s3://$BUCKET_NAME/index.html" \
    --content-type "text/html" \
    --region "$REGION"

# Invalidate CloudFront cache if distribution exists
if [ -n "$WEBUI_HTTPS_URL" ]; then
    CF_DOMAIN=$(echo "$WEBUI_HTTPS_URL" | sed 's|https://||')
    DISTRIBUTION_ID=$(aws cloudfront list-distributions \
        --query "DistributionList.Items[?DomainName=='${CF_DOMAIN}'].Id" \
        --output text 2>/dev/null)

    if [ -n "$DISTRIBUTION_ID" ] && [ "$DISTRIBUTION_ID" != "None" ]; then
        echo "Invalidating CloudFront cache (${DISTRIBUTION_ID})..."
        aws cloudfront create-invalidation \
            --distribution-id "$DISTRIBUTION_ID" \
            --paths "/*" \
            --query 'Invalidation.Id' \
            --output text > /dev/null
        echo "Cache invalidation started."
    fi
fi

echo ""
echo "=== Deployment Complete ==="
echo ""
if [ -n "$WEBUI_HTTPS_URL" ]; then
    echo "Web UI URL (HTTPS): $WEBUI_HTTPS_URL"
    echo ""
    echo "Use the HTTPS URL above for voice/microphone support."
else
    echo "Web UI URL: $WEBUI_URL"
fi
echo ""
