"""Provider-scoped text-token quotes; unknown costs are absent, never guessed.

Only standard OpenAI text rates explicitly checked on 2026-09-07 are included.
Quotes exclude tools, images, audio, taxes, tier changes and local compute. Source
metadata records a review, not proof that an endpoint billed that rate. No network
request, provider inference, model alias or fallback price is used at runtime.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import math
from typing import Optional
from urllib.parse import urlparse


class UnknownModelPricingError(LookupError):
    """No supported quote for the explicit provider/model combination."""


@dataclass(frozen=True)
class ModelPricing:
    input_per_million: float
    output_per_million: float
    cached_input_per_million: float
    provider: str
    source: str
    verified_on: str
    scope: str = 'standard text tokens, USD per million; excludes other fees'

    def __post_init__(self):
        rates = (self.input_per_million, self.output_per_million, self.cached_input_per_million)
        if any(type(x) not in (float, int) or not math.isfinite(x) or x < 0 for x in rates):
            raise ValueError('Pricing rates must be finite nonnegative numbers')
        if self.cached_input_per_million > self.input_per_million:
            raise ValueError('Cached-input rate exceeds uncached rate')
        url = urlparse(self.source)
        if not self.provider or url.scheme != 'https' or not url.hostname or url.username or url.password:
            raise ValueError('Pricing requires provider and an HTTPS source URL')
        reviewed = date.fromisoformat(self.verified_on)
        if reviewed.isoformat() != self.verified_on:
            raise ValueError('Pricing requires a canonical ISO review date')

PRICING_TABLE = {
    'gpt-4o': ModelPricing(2.50, 10.00, 1.25, 'openai',
                         'https://developers.openai.com/api/docs/models/gpt-4o', '2026-09-07'),
    'gpt-4o-mini': ModelPricing(0.15, 0.60, 0.075, 'openai',
                              'https://developers.openai.com/api/docs/models/gpt-4o-mini', '2026-09-07'),
}


def resolve_model_id(model_name):
    if not isinstance(model_name, str): return None
    key = model_name.strip().lower()
    return key if key in PRICING_TABLE else None


def get_pricing(model_name, strict=False, *, provider=None):
    key = resolve_model_id(model_name)
    row = PRICING_TABLE.get(key)
    if row is not None and provider == row.provider: return row
    if strict: raise UnknownModelPricingError('No documented pricing for this explicit provider/model combination')
    return None


def is_priced(model_name, *, provider=None):
    return get_pricing(model_name, provider=provider) is not None


def _require_counts(input_tokens, output_tokens, cached_input_tokens):
    if any(type(x) is not int or x < 0 for x in (input_tokens, output_tokens, cached_input_tokens)):
        raise ValueError('Token counts must be nonnegative integers')
    if cached_input_tokens > input_tokens: raise ValueError('Cached tokens exceed input tokens')


def estimate_cost(model_name, input_tokens, output_tokens=0, cached_input_tokens=0, strict=False, *, provider=None):
    _require_counts(input_tokens, output_tokens, cached_input_tokens)
    pricing = get_pricing(model_name, strict=strict, provider=provider)
    if pricing is None: return None
    # Do not round each tiny request to zero or inflate it before aggregation.
    return float(((input_tokens-cached_input_tokens)*Decimal(str(pricing.input_per_million))
                  + cached_input_tokens*Decimal(str(pricing.cached_input_per_million))
                  + output_tokens*Decimal(str(pricing.output_per_million))) / 1_000_000)


def calculate_savings(model_name, original_input_tokens, optimized_input_tokens, output_tokens=0,
                      cached_tokens=0, strict=False, *, provider=None):
    """Hypothetical gross quote difference with identical supplied output counts.

    This is not measured savings or answer-quality evidence. Negative differences
    remain negative; undefined ratios and unsupported quotes are None.
    """
    before = estimate_cost(model_name, original_input_tokens, output_tokens, strict=strict, provider=provider)
    after = estimate_cost(model_name, optimized_input_tokens, output_tokens, cached_tokens, strict=strict, provider=provider)
    if before is None or after is None: return None, None, None, None
    saved = before-after
    return before, after, saved, saved/before*100 if before else None
