# Project Structure

```
.
├── template.yaml              # SAM template — all AWS infrastructure (Lex, Lambda, Cognito, S3)
├── samconfig.toml             # SAM CLI deployment defaults (stack name, region, capabilities)
├── src/
│   └── handler.py             # Lambda function (single module, all logic here)
├── tests/
│   ├── unit/
│   │   ├── test_handler.py    # Unit tests (intent routing, error handling, env var resolution)
│   │   ├── test_properties.py # Property-based tests (hypothesis — correctness invariants)
│   │   ├── test_conversation_context.py
│   │   └── test_invoke_bedrock.py
│   └── events/
│       └── fallback_event.json  # Sample Lex FallbackIntent event payload
├── conftest.py                # Root pytest config (pydantic/hypothesis workaround)
├── webui/
│   ├── index.html             # Chat UI template (placeholders replaced at deploy time)
│   └── dist/                  # Generated: configured index.html uploaded to S3
├── deploy-webui.sh            # Script to inject config and upload Web UI to S3
└── .kiro/
    ├── specs/                 # Feature specs (requirements, design, tasks)
    └── steering/              # AI assistant steering rules (this directory)
```

## Conventions

- **Single Lambda module**: All handler logic lives in `src/handler.py`. No sub-packages, no layers.
- **No requirements.txt / pyproject.toml**: The Lambda uses only boto3/botocore from the runtime. Dev dependencies (pytest, hypothesis) are installed manually.
- **Tests mirror source**: Tests import from `src.handler` directly. Mocks are applied at module level (`src.handler.bedrock_runtime`).
- **Test classes group by requirement**: Each test class validates a specific requirement and documents which requirement IDs it covers.
- **Property-based tests**: Use hypothesis with `@settings(max_examples=100)` and document the formal correctness property in the class docstring.
- **Infrastructure as single template**: Everything is in one `template.yaml` — no nested stacks, no separate SAM apps.
- **Stage isolation via parameter**: The `Stage` parameter controls resource name prefixes (`staging-` or `prod-`), enabling parallel deployments in the same account.
