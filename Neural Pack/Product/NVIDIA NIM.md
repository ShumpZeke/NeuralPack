# NVIDIA NIM Provider Integration

NVIDIA NIM provides microservices and hosted endpoints for open-weight models accelerated with TensorRT-LLM and vLLM backends.

## Tested Working Models
Our discovery scan of the active API account confirmed access to 15 active models, including:
- `meta/llama-3.2-11b-vision-instruct` (Primary instruction-tuned testing model)
- `deepseek-ai/deepseek-v4-flash-0731`
- `deepseek-ai/deepseek-v4-pro-0813`
- `openai/gpt-oss-20b`
- `moonshotai/kimi-k3`
- `minimaxai/minimax-m3`

## Authentication & Security Rules
- Credentials are loaded via `os.environ["NVIDIA_API_KEY"]` or private git-ignored `.env` file.
- No credential is ever logged, displayed in CLI output, or committed to Git.
- All error messages, request logs, and exception dumps are filtered through `redact_secrets(...)` before emission.

## Error Handling & Reliability
- The provider wraps requests in a 3-attempt retry loop with exponential backoff.
- Intercepts read timeouts and rate limits (429 / 5xx) to ensure robust execution across congested shared queues.
