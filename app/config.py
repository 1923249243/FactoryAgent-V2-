import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


class Settings(BaseModel):
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    llm_timeout_seconds: float = Field(
        default=float(os.getenv("LLM_TIMEOUT_SECONDS", "20")),
        ge=1,
        le=120,
    )
    database_path: str = os.getenv("DATABASE_PATH", "data/factory_agent.db")
    drawings_dir: str = os.getenv("DRAWINGS_DIR", "data/drawings")
    engineering_dir: str = os.getenv("ENGINEERING_DIR", "data/engineering")
    engineering_evidence_dir: str = os.getenv(
        "ENGINEERING_EVIDENCE_DIR", "data/engineering/v43_real_motor/evidence"
    )
    engineering_planner_llm: bool = os.getenv("ENGINEERING_PLANNER_LLM", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


settings = Settings()

if settings.database_path != ":memory:":
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
