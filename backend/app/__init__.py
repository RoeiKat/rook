import os

from dotenv import load_dotenv

load_dotenv()

# The Ollama client reads OLLAMA_HOST; keep OLLAMA_BASE_URL as Rook's public setting.
if ollama_base_url := os.getenv("OLLAMA_BASE_URL"):
    os.environ.setdefault("OLLAMA_HOST", ollama_base_url)
