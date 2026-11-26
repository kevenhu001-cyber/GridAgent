"""Workspace model settings. API keys belong to the current client session."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ModelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    model: str = Field(default="", max_length=200)
    base_url: str = Field(default="", max_length=500)

    @field_validator("base_url")
    @classmethod
    def validate_endpoint(cls, value):
        if value:
            parsed = urlsplit(value)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None
                    or parsed.password is not None or parsed.query or parsed.fragment or parsed.port == 0):
                raise ValueError("Use an HTTP(S) base URL without credentials, query parameters or a fragment")
        return value.rstrip("/")


def stored_settings(root):
    path = Path(root) / "model-settings.json"
    try:
        return ModelSettings.model_validate_json(path.read_bytes())
    except FileNotFoundError:
        return ModelSettings()


def active_settings(root=None):
    saved = stored_settings(root) if root is not None else ModelSettings()
    return ModelSettings(model=os.getenv("GRIDAGENT_MODEL", saved.model),
                         base_url=os.getenv("GRIDAGENT_BASE_URL", saved.base_url))


def local_endpoint(settings):
    return urlsplit(settings.base_url).hostname in {"localhost", "127.0.0.1", "::1"}


def save_settings(root, model, base_url):
    data = ModelSettings(model=model, base_url=base_url)
    if not data.model:
        raise ValueError("Enter a model name")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    stage = root / (".model-settings-" + uuid4().hex)
    try:
        stage.write_text(json.dumps(data.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
        stage.replace(root / "model-settings.json")
    finally:
        stage.unlink(missing_ok=True)
    return data


def check_connection(settings, key=None, *, factory=None):
    from langchain_core.messages import HumanMessage

    from .agent import model_from_env

    create = factory or model_from_env
    model = create(settings=settings, api_key=key)
    model.invoke([HumanMessage(content="Reply with OK. This is a GridAgent connection check.")])
    return f"Connected to {settings.model}"
