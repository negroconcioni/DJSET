"""Application configuration."""
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Settings loaded from environment."""

    # Paths
    base_dir: Path = Path(__file__).resolve().parent.parent
    upload_dir: Path = Path("uploads")
    output_dir: Path = Path("output")

    # LLM (only for JSON decision; no audio processing)
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    mix_decision_model: str = "gpt-4o-mini"

    # Audio
    default_sr: int = 44100
    max_upload_mb: int = 100

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.upload_dir = self.base_dir / str(self.upload_dir)
        self.output_dir = self.base_dir / str(self.output_dir)

    model_config = {"env_prefix": "AUTOMIX_", "env_file": ".env"}


settings = Settings()
