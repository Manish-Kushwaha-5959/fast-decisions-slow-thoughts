
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:

    groq_api_key: str
    groq_model: str
    groq_temperature: float
    groq_max_completion_tokens: int
    groq_timeout: float

    typesafe_api_key: str
    jev_model: str

    # Mode C escalation thresholds (provisional; require calibration).
    tool_confidence_threshold: float
    completion_ambiguity_lower: float
    completion_ambiguity_upper: float

    @classmethod
    def from_env(cls):

        return cls(

            groq_api_key=os.getenv(
                "GROQ_API_KEY", ""
            ),

            groq_model=os.getenv(
                "GROQ_MODEL",
                "openai/gpt-oss-120b"
            ),

            groq_temperature=float(
                os.getenv("GROQ_TEMPERATURE", "0.2")
            ),

            groq_max_completion_tokens=int(
                os.getenv(
                    "GROQ_MAX_COMPLETION_TOKENS", "1024"
                )
            ),

            groq_timeout=float(
                os.getenv("GROQ_TIMEOUT", "60")
            ),

            typesafe_api_key=os.getenv(
                "TYPESAFE_API_KEY", ""
            ),

            jev_model=os.getenv(
                "JEV_MODEL", "jev-latest"
            ),

            tool_confidence_threshold=float(
                os.getenv(
                    "TOOL_CONFIDENCE_THRESHOLD", "0.60"
                )
            ),

            completion_ambiguity_lower=float(
                os.getenv(
                    "COMPLETION_AMBIGUITY_LOWER", "0.50"
                )
            ),

            completion_ambiguity_upper=float(
                os.getenv(
                    "COMPLETION_AMBIGUITY_UPPER", "0.70"
                )
            )
        )

    def validate_groq(self):

        if not self.groq_api_key:
            raise ValueError(
                "GROQ_API_KEY is missing from .env"
            )

    def validate_typesafe(self):

        if not self.typesafe_api_key:
            raise ValueError(
                "TYPESAFE_API_KEY is missing from .env"
            )


settings = Settings.from_env()
