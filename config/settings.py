"""
config/settings.py
Central configuration loaded from environment variables (.env file).
"""
import os
from dataclasses import dataclass, field
from typing import List, Dict, Any
from dotenv import load_dotenv

load_dotenv()


def _parse_hours(raw: str) -> List[int]:
    """Parse '8' or '8,18' into a list of ints."""
    try:
        return [int(h.strip()) for h in raw.split(",") if h.strip()]
    except ValueError:
        return [8]


@dataclass
class Settings:
    # ── Database ──────────────────────────────────────────────────────────────
    db_path: str = os.getenv("DB_PATH", "./data/jobs.db")

    # ── Telegram ──────────────────────────────────────────────────────────────
    telegram_token: str   = os.getenv("TELEGRAM_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # ── LLM backend selector ──────────────────────────────────────────────────
    # "ollama" → local Ollama (job-by-job)
    # "anthropic" → Anthropic API (batch scoring)
    llm_backend: str = os.getenv("LLM_BACKEND", "anthropic")

    # ── Ollama (local) ────────────────────────────────────────────────────────
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL")
    ollama_model: str = os.getenv("OLLAMA_MODEL")

    # ── Anthropic API ─────────────────────────────────────────────────────────
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str   = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    anthropic_batch_size: int = int(os.getenv("ANTHROPIC_BATCH_SIZE", "10"))

    # ── Scoring thresholds ────────────────────────────────────────────────────
    score_alert_threshold: int  = int(os.getenv("SCORE_ALERT_THRESHOLD",  "80"))
    score_digest_threshold: int = int(os.getenv("SCORE_DIGEST_THRESHOLD", "40"))
    score_save_threshold: int   = int(os.getenv("SCORE_SAVE_THRESHOLD",   "10"))
    max_alerts_per_run: int     = int(os.getenv("MAX_ALERTS_PER_RUN",     "2"))

    # ── Scheduler ─────────────────────────────────────────────────────────────
    schedule_hours: List[int] = field(
        default_factory=lambda: _parse_hours(os.getenv("SCHEDULE_HOURS", "8"))
    )

    # ── JobSpy search params ──────────────────────────────────────────────────
    jobspy_search_terms: List[str] = field(default_factory=lambda: [
        "data analyst",
        "business intelligence analyst",
        "data engineer",
        "BI developer",
        "information management",
        "monitoring evaluation data",
    ])
    jobspy_results_per_search: int = int(os.getenv("JOBSPY_RESULTS", "20"))
    jobspy_hours_old: int          = int(os.getenv("JOBSPY_HOURS_OLD", "48"))

    # ── Keyword groups (weighted) ─────────────────────────────────────────────
    keyword_groups: Dict[str, Any] = field(default_factory=lambda: {
        "core_data": {
            "keywords": [
                "data analyst", "business intelligence", "BI", "ETL", "SQL",
                "Power BI", "Tableau", "DAX", "data warehouse", "data pipeline",
                "analytics", "reporting", "dashboard", "Power Query",
                "operational data management", "information management",
            ],
            "weight": 2.0,
        },
        "engineering": {
            "keywords": [
                "data engineer", "data engineering", "pipeline", "warehouse",
                "Python", "dbt", "Spark", "Airflow", "cloud", "AWS", "Azure",
            ],
            "weight": 1.8,
        },
        "monitoring_evaluation": {
            "keywords": [
                "monitoring", "evaluation", "M&E", "MEAL", "results framework",
                "indicators", "logframe", "performance measurement",
            ],
            "weight": 1.5,
        },
        "programs_projects": {
            "keywords": [
                "program management", "project management", "portfolio",
                "consultant", "coordination", "strategy",
            ],
            "weight": 1.2,
        },
        "ai_tools": {
            "keywords": [
                "machine learning", "ML", "LLM", "AI", "artificial intelligence",
                "automation", "NLP", "RAG", "generative AI",
            ],
            "weight": 1.3,
        },
    })

    # ── Negative keywords ─────────────────────────────────────────────────────
    hard_negative_keywords: List[str] = field(default_factory=lambda: [
        "WASH", "protection officer", "field security", "security officer",
        "driver", "conductor", "intern", "internship", "nurse", "doctor",
        "medical", "lawyer", "legal officer", "paralegal",
    ])

    soft_negative_keywords: List[str] = field(default_factory=lambda: [
        "on-site required", "must be located", "clearance required",
        "US citizens only", "entry level", "without sponsorship",
    ])

    # ── Seniority keywords ────────────────────────────────────────────────────
    positive_seniority_keywords: List[str] = field(default_factory=lambda: [
        "senior", "lead", "principal", "specialist", "manager",
        "officer", "associate", "consultant", "director",
    ])

    negative_seniority_keywords: List[str] = field(default_factory=lambda: [
        "junior", "intern", "entry level", "entry-level",
        "trainee", "graduate",
    ])

    # ── Logging ───────────────────────────────────────────────────────────────
    log_dir: str   = os.getenv("LOG_DIR", "./logs")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
