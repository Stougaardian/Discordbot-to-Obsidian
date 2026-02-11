import os
from dataclasses import dataclass

from dotenv import load_dotenv


ENV_FILE = os.getenv(
    "ENV_FILE",
    os.path.join(os.path.dirname(__file__), "discordBotToken.env"),
)
VAULT_ENV_FILE = os.getenv(
    "VAULT_ENV_FILE",
    os.path.join(os.path.dirname(__file__), ".env"),
)
load_dotenv(ENV_FILE, override=False)
load_dotenv(VAULT_ENV_FILE, override=True)


def _get_env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value


@dataclass
class Settings:
    discord_bot_token: str | None = _get_env("DISCORD_BOT_TOKEN")
    vault_path: str | None = _get_env("VAULT_PATH")
    agent_api_url: str = _get_env("AGENT_API_URL", "http://localhost:8000/chat")
    model_backend: str = _get_env("MODEL_BACKEND", "local").lower()
    codex_bin: str = _get_env("CODEX_BIN", "codex")
    codex_args: str = _get_env("CODEX_ARGS", "")
    openai_api_key: str | None = _get_env("OPENAI_API_KEY")

    max_snippets: int = int(_get_env("MAX_SNIPPETS", "10"))
    max_snippet_lines: int = int(_get_env("MAX_SNIPPET_LINES", "5"))
    session_path: str = _get_env(
        "SESSION_PATH",
        os.path.join(os.path.dirname(__file__), "data", "sessions.json"),
    )
    session_max_turns: int = int(_get_env("SESSION_MAX_TURNS", "16"))
    request_timeout_s: int = int(_get_env("REQUEST_TIMEOUT_S", "60"))


settings = Settings()
