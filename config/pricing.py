"""
Pricing configuration for model cost accounting (Phase 11).

Centralized, configurable pricing data for economic evaluation of
experimental runs across all three modes (A, B, C).

Reference pricing (initial configurable defaults):
- Groq GPT-OSS 120B: input $0.15/M, output $0.60/M
  (https://console.groq.com/docs/models)
- Jev 1.14.0: input $0.042/M, output $0.00/M
  (https://vercel.com/ai-gateway/models/jev-1.14.0)

Pricing is stored here once; no other module hardcodes per-token rates.
Historical benchmark costs are never silently recomputed: the pricing
version and effective date are recorded with each run, so a pricing
change produces a new version rather than rewriting old rows.

Actual expenditure vs estimated equivalent cost:
- ``cost_actual`` is the amount charged to the account, when known.
  Groq free-tier calls have actual expenditure of $0. Jev is NOT
  assumed free merely because Groq is; its actual cost must come
  from the Jev billing route, not from this file.
- ``cost_estimated`` applies the reference paid pricing above to the
  recorded token consumption. It is an economic estimate, not billing.
"""

import os
from dataclasses import dataclass
from typing import Optional


# Reference pricing defaults (USD per 1 million tokens).
DEFAULT_GROQ_INPUT_PRICE = 0.15
DEFAULT_GROQ_OUTPUT_PRICE = 0.60
DEFAULT_JEV_INPUT_PRICE = 0.042
DEFAULT_JEV_OUTPUT_PRICE = 0.00

GROQ_PRICING_SOURCE = "https://console.groq.com/docs/models"
JEV_PRICING_SOURCE = "https://vercel.com/ai-gateway/models/jev-1.14.0"
JEV_API_GUIDE_SOURCE = "https://typesafe-jev.com/en/guides/api/"

PRICING_VERSION = "2026-11-16-v1"
PRICING_EFFECTIVE_DATE = "2026-11-16"

# Model identifiers as configured in the project.
GROQ_MODEL_ID = "openai/gpt-oss-120b"
JEV_MODEL_ID = "jev-latest"


@dataclass(frozen=True)
class ModelPricing:
    """Pricing record for one model/provider route."""

    provider: str
    model_identifier: str
    input_price_per_million: float
    output_price_per_million: float
    currency: str
    pricing_source_url: str
    effective_date: str
    pricing_version: str
    model_description: Optional[str] = None

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Return estimated cost (currency units) for token usage."""

        input_cost = (input_tokens / 1_000_000) * self.input_price_per_million
        output_cost = (output_tokens / 1_000_000) * self.output_price_per_million
        return input_cost + output_cost


@dataclass(frozen=True)
class PricingConfig:
    """Container for all configured model pricing."""

    groq_gpt_oss_120b: ModelPricing
    jev_1_14_0: ModelPricing

    def get_pricing_for_provider(self, provider: str) -> Optional[ModelPricing]:
        if provider == "groq":
            return self.groq_gpt_oss_120b
        if provider == "jev":
            return self.jev_1_14_0
        return None

    def get_pricing_for_model(self, model_id: str) -> Optional[ModelPricing]:
        if model_id == GROQ_MODEL_ID:
            return self.groq_gpt_oss_120b
        if model_id == JEV_MODEL_ID:
            return self.jev_1_14_0
        return None

    def calculate_costs_by_provider(
        self,
        groq_input_tokens: int,
        groq_output_tokens: int,
        jev_input_tokens: int,
        jev_output_tokens: int
    ) -> dict:
        """Return per-provider and total estimated costs."""

        groq_cost = self.groq_gpt_oss_120b.calculate_cost(
            groq_input_tokens, groq_output_tokens
        )
        jev_cost = self.jev_1_14_0.calculate_cost(
            jev_input_tokens, jev_output_tokens
        )
        return {
            "groq": groq_cost,
            "jev": jev_cost,
            "total": groq_cost + jev_cost
        }


def get_default_pricing_config() -> PricingConfig:
    """Build pricing config from reference defaults."""

    return PricingConfig(
        groq_gpt_oss_120b=ModelPricing(
            provider="groq",
            model_identifier=GROQ_MODEL_ID,
            input_price_per_million=DEFAULT_GROQ_INPUT_PRICE,
            output_price_per_million=DEFAULT_GROQ_OUTPUT_PRICE,
            currency="USD",
            pricing_source_url=GROQ_PRICING_SOURCE,
            effective_date=PRICING_EFFECTIVE_DATE,
            pricing_version=PRICING_VERSION,
            model_description="Groq GPT-OSS 120B"
        ),
        jev_1_14_0=ModelPricing(
            provider="jev",
            model_identifier=JEV_MODEL_ID,
            input_price_per_million=DEFAULT_JEV_INPUT_PRICE,
            output_price_per_million=DEFAULT_JEV_OUTPUT_PRICE,
            currency="USD",
            pricing_source_url=JEV_PRICING_SOURCE,
            effective_date=PRICING_EFFECTIVE_DATE,
            pricing_version=PRICING_VERSION,
            model_description="Jev 1.14.0"
        )
    )


def get_pricing_from_env() -> PricingConfig:
    """Load pricing config, allowing environment overrides."""

    groq_input = float(
        os.getenv("GROQ_INPUT_PRICE_PER_MILLION", DEFAULT_GROQ_INPUT_PRICE)
    )
    groq_output = float(
        os.getenv("GROQ_OUTPUT_PRICE_PER_MILLION", DEFAULT_GROQ_OUTPUT_PRICE)
    )
    jev_input = float(
        os.getenv("JEV_INPUT_PRICE_PER_MILLION", DEFAULT_JEV_INPUT_PRICE)
    )
    jev_output = float(
        os.getenv("JEV_OUTPUT_PRICE_PER_MILLION", DEFAULT_JEV_OUTPUT_PRICE)
    )

    return PricingConfig(
        groq_gpt_oss_120b=ModelPricing(
            provider="groq",
            model_identifier=os.getenv("GROQ_MODEL", GROQ_MODEL_ID),
            input_price_per_million=groq_input,
            output_price_per_million=groq_output,
            currency="USD",
            pricing_source_url=GROQ_PRICING_SOURCE,
            effective_date=PRICING_EFFECTIVE_DATE,
            pricing_version=PRICING_VERSION,
            model_description="Groq GPT-OSS 120B"
        ),
        jev_1_14_0=ModelPricing(
            provider="jev",
            model_identifier=os.getenv("JEV_MODEL", JEV_MODEL_ID),
            input_price_per_million=jev_input,
            output_price_per_million=jev_output,
            currency="USD",
            pricing_source_url=JEV_PRICING_SOURCE,
            effective_date=PRICING_EFFECTIVE_DATE,
            pricing_version=PRICING_VERSION,
            model_description="Jev 1.14.0"
        )
    )


def verify_jev_pricing_route(jev_model: str) -> tuple[bool, str]:
    """Check whether a configured Jev model matches the assumed pricing route.

    The reference Jev pricing ($0.042/M input, $0.00/M output) assumes the
    Vercel AI Gateway `jev-1.14.0` route. A different model identifier or
    endpoint may have different pricing; this check flags that mismatch so
    cost figures are not silently applied to the wrong route.

    Returns (is_compatible, message).
    """

    compatible_ids = {"jev-1.14.0", "jev-latest"}
    if jev_model in compatible_ids:
        return True, (
            f"Jev model '{jev_model}' matches the assumed pricing route "
            f"({JEV_PRICING_SOURCE})."
        )

    return False, (
        f"Jev model '{jev_model}' does not match the assumed pricing route "
        f"'jev-1.14.0' ({JEV_PRICING_SOURCE}). Verify the endpoint and "
        f"pricing before applying Jev cost figures."
    )


_default_pricing_config: Optional[PricingConfig] = None


def get_pricing_config() -> PricingConfig:
    """Return the global pricing configuration (env-based or default)."""

    global _default_pricing_config
    if _default_pricing_config is None:
        try:
            _default_pricing_config = get_pricing_from_env()
        except (ValueError, TypeError):
            _default_pricing_config = get_default_pricing_config()
    return _default_pricing_config


def reset_pricing_config() -> None:
    """Reset the global pricing config (used by tests)."""

    global _default_pricing_config
    _default_pricing_config = None
