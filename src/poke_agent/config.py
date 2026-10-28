import os
from pathlib import Path


def _default_env_path() -> Path:
    package_dir = Path(__file__).resolve().parent
    project_root = package_dir.parents[1]
    root_env = project_root / ".env"
    if root_env.exists():
        return root_env
    return package_dir / ".env"


def load_env(env_path: Path | str | None = None) -> None:
    """
    Load environment variables from a .env file.
    Uses python-dotenv if available, otherwise falls back to a built-in parser.
    """
    env_file = Path(env_path) if env_path is not None else _default_env_path()

    if not env_file.exists():
        return

    try:
        from dotenv import load_dotenv

        load_dotenv(dotenv_path=env_file)
    except ImportError:
        # Fallback parser for .env files without requiring python-dotenv
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[7:]
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = val


# Automatically load .env on import
load_env()

# Configuration variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", os.getenv("MODEL", "gpt-6-luna"))
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "").strip() or None

