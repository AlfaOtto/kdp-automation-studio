import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

BASE_DIR = Path(__file__).parent


class Config:
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

    AMAZON_REGION = os.getenv("AMAZON_REGION", "US")
    AMAZON_BASE_URL = "https://www.amazon.com"
    AMAZON_MARKETPLACE_ID = "ATVPDKIKX0DER"

    MIN_DELAY_SECONDS = 2.0
    MAX_DELAY_SECONDS = 5.0
    MAX_RETRIES = 3
    DEFAULT_MAX_RESULTS = 40

    WEIGHT_COMPETITION = 0.45
    WEIGHT_DEMAND = 0.40
    WEIGHT_PRICING = 0.15

    OUTPUT_DIR   = BASE_DIR / "output"
    RESEARCH_DIR = BASE_DIR / "output" / "research"
    HISTORY_DIR  = BASE_DIR / "output" / "history"
    PRODUCTS_DIR = Path.home() / "Desktop" / "KDP"
    REPORTS_DIR  = BASE_DIR / "output" / "reports"
    LEARNING_DIR = BASE_DIR / "output" / "learning"
    ANALYTICS_DIR = BASE_DIR / "output" / "analytics"

    @classmethod
    def validate(cls):
        issues = []
        if not cls.ANTHROPIC_API_KEY:
            issues.append("ANTHROPIC_API_KEY not configured")
        for d in [cls.OUTPUT_DIR, cls.RESEARCH_DIR, cls.HISTORY_DIR,
                  cls.PRODUCTS_DIR, cls.REPORTS_DIR, cls.LEARNING_DIR]:
            d.mkdir(parents=True, exist_ok=True)
        return issues

    @classmethod
    def has_anthropic(cls) -> bool:
        return bool(cls.ANTHROPIC_API_KEY)

    @classmethod
    def has_openai(cls) -> bool:
        return bool(cls.OPENAI_API_KEY)
