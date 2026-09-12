# Provider Adapters

NeuralPack defines a clean provider interface in `npk/providers/base.py`:

```python
class BaseProvider(ABC):
    name: str
    capabilities: ProviderCapabilities

    @abstractmethod
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        stream: bool = False,
        **kwargs: Any,
    ) -> ChatResponse | Generator[Dict[str, Any], None, None]:
        pass

    @abstractmethod
    def list_models(self) -> List[str]:
        pass
```

## Implemented Adapters
1. **`NvidiaNIMProvider` (`npk/providers/nvidia.py`)**:
   - Endpoint: `https://integrate.api.nvidia.com/v1`
   - Authenticates with `NVIDIA_API_KEY` loaded securely from environment.
   - Supports standard OpenAI chat completions, streaming (`stream=True`), and exact token accounting.
   - Includes automatic exponential backoff (retries on 429, 500, 502, 503, 504 and read timeouts).
2. **`MockProvider` (`npk/providers/mock.py`)**:
   - Fast offline provider used for record/replay, CI/CD, and offline testing without incurring API costs.

## Roadmap Adapters
- `OpenAIProvider`: Official OpenAI API (`https://api.openai.com/v1`).
- `AnthropicProvider`: Anthropic Messages API with native `cache_control` integration.
- `GeminiProvider`: Google Gemini OpenAI-compatible / vertex endpoints.
