"""Create an ignored Wrangler secret-bulk file from the local AI-writer config."""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / ".cloudflare-secrets.json"


def main() -> None:
    local_env = {key: value or "" for key, value in dotenv_values(ROOT / ".env").items()}
    models_path = ROOT / "config" / "models.json"
    models_json = local_env.get("MODELS_JSON", "").strip()
    if not models_json and models_path.is_file():
        models_json = models_path.read_text(encoding="utf-8")
    if not models_json:
        model = {
            "value": local_env.get("WRITER_MODEL", "gpt-5.5").strip() or "gpt-5.5",
            "label": local_env.get("WRITER_MODEL", "gpt-5.5").strip() or "gpt-5.5",
            "provider": local_env.get("LLM_PROVIDER", "openai").strip() or "openai",
            "api_key": local_env.get("OPENAI_API_KEY", "").strip(),
        }
        if model["provider"].lower() == "anthropic":
            model["api_key"] = local_env.get("ANTHROPIC_API_KEY", "").strip()
            if base_url := local_env.get("ANTHROPIC_BASE_URL", "").strip():
                model["base_url"] = base_url
        elif base_url := local_env.get("OPENAI_BASE_URL", "").strip():
            model["base_url"] = base_url
        models_json = json.dumps({"default": model["value"], "models": [model]}, ensure_ascii=False)
    parsed_models = json.loads(models_json)
    if not parsed_models.get("models"):
        raise SystemExit("No model is configured in config/models.json or .env")
    if any(not (model.get("api_key") or "").strip() for model in parsed_models["models"]):
        raise SystemExit("At least one configured model is missing its API key")

    values = {
        "SESSION_SECRET": local_env.get("SESSION_SECRET", "").strip() or secrets.token_urlsafe(48),
        "MODELS_JSON": json.dumps(parsed_models, ensure_ascii=False, separators=(",", ":")),
        "INTERNAL_BACKUP_TOKEN": secrets.token_urlsafe(48),
        "STATE_SEED_TOKEN": secrets.token_urlsafe(48),
        "ADMIN_USER": local_env.get("ADMIN_USER", "sherry").strip() or "sherry",
        "FREE_LIMIT": local_env.get("FREE_LIMIT", "10").strip() or "10",
        "USAGE_TIMEZONE": local_env.get("USAGE_TIMEZONE", "Asia/Shanghai").strip() or "Asia/Shanghai",
    }
    OUTPUT.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        OUTPUT.chmod(0o600)
    except OSError:
        pass
    print("Created ignored .cloudflare-secrets.json with local model settings and generated internal tokens.")


if __name__ == "__main__":
    main()
