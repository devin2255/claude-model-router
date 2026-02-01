"""
Configuration management for claude-model-router.
"""
import json
import os
import sys
from typing import Any, Dict, Optional

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_PROXY_URL = "http://127.0.0.1:19000"
DEFAULT_OPENAI_CHAT_MODEL = "gpt-5.2-codex"
DEFAULT_OPENAI_LIGHT_MODEL = "gpt-5.2-codex"
DEFAULT_KIMI_BASE_URL = "https://api.moonshot.cn/anthropic"
DEFAULT_KIMI_MODEL = "kimi-k2.5"
DEFAULT_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_NVIDIA_KIMI_MODEL = "moonshotai/kimi-k2.5"
DEFAULT_NVIDIA_GLM_MODEL = "z-ai/glm4.7"

DEFAULT_CONFIG = {
    "proxy_url": DEFAULT_PROXY_URL,
    "openai_base_url": DEFAULT_OPENAI_BASE_URL,
    "models": {
        "kimi": {
            "anthropic_base_url": DEFAULT_KIMI_BASE_URL,
            "anthropic_auth_token": "",
            "anthropic_model": DEFAULT_KIMI_MODEL,
            "anthropic_default_opus_model": "",
            "anthropic_default_sonnet_model": "",
            "anthropic_default_haiku_model": "",
            "claude_code_subagent_model": "",
            "use_proxy": False,
        },
        "openai": {
            "openai_base_url": DEFAULT_OPENAI_BASE_URL,
            "anthropic_base_url": "",
            "anthropic_auth_token": "",
            "anthropic_model": DEFAULT_OPENAI_CHAT_MODEL,
            "anthropic_default_opus_model": "",
            "anthropic_default_sonnet_model": "",
            "anthropic_default_haiku_model": "",
            "claude_code_subagent_model": "",
            "use_proxy": True,
        },
        "nvidia-kimi": {
            "openai_base_url": DEFAULT_NVIDIA_BASE_URL,
            "anthropic_base_url": DEFAULT_NVIDIA_BASE_URL,
            "anthropic_auth_token": "",
            "anthropic_model": DEFAULT_NVIDIA_KIMI_MODEL,
            "anthropic_default_opus_model": "",
            "anthropic_default_sonnet_model": "",
            "anthropic_default_haiku_model": "",
            "claude_code_subagent_model": "",
            "use_proxy": False,
        },
        "nvidia-glm": {
            "openai_base_url": DEFAULT_NVIDIA_BASE_URL,
            "anthropic_base_url": DEFAULT_NVIDIA_BASE_URL,
            "anthropic_auth_token": "",
            "anthropic_model": DEFAULT_NVIDIA_GLM_MODEL,
            "anthropic_default_opus_model": "",
            "anthropic_default_sonnet_model": "",
            "anthropic_default_haiku_model": "",
            "claude_code_subagent_model": "",
            "use_proxy": False,
        },
    },
}

CONFIG_KEYS = [
    "MODEL_ROUTER_ACTIVE_MODEL",
    "MODEL_ROUTER_PROXY_URL",
    "MODEL_ROUTER_OPENAI_BASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_API_BASE",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL",
    "ANTHROPIC_AUTH_TOKEN",
]


def get_config_path() -> str:
    """Get the path to the configuration file."""
    env_path = os.environ.get("MODEL_ROUTER_CONFIG")
    if env_path:
        return env_path
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "model-router.config.json")


def deep_merge(base: Dict[str, Any], override: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Deep merge two dictionaries."""
    merged = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config_file(path: str) -> Dict[str, Any]:
    """Load configuration from a JSON file."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            return payload
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Configuration file read failed: {path} ({exc})", file=sys.stderr)
    return {}


def get_config_template() -> Dict[str, Any]:
    """Get a template configuration with placeholder values."""
    template = json.loads(json.dumps(DEFAULT_CONFIG))
    template["models"]["kimi"]["anthropic_auth_token"] = "REPLACE_ME"
    template["models"]["openai"]["anthropic_auth_token"] = "REPLACE_ME"
    return template


def init_config_file() -> int:
    """Initialize a new configuration file from the template."""
    config_path = get_config_path()
    if os.path.exists(config_path):
        print(f"Configuration file already exists: {config_path}")
        return 0

    directory = os.path.dirname(os.path.abspath(config_path))
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)

    template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "config", "example.json")
    try:
        if os.path.exists(template_path):
            with open(template_path, "r", encoding="utf-8") as src:
                content = src.read()
            with open(config_path, "w", encoding="utf-8") as dst:
                dst.write(content)
        else:
            with open(config_path, "w", encoding="utf-8") as dst:
                json.dump(get_config_template(), dst, indent=2, ensure_ascii=False)
                dst.write("\n")
    except OSError as exc:
        print(f"Configuration file write failed: {config_path} ({exc})", file=sys.stderr)
        return 1

    print(f"Configuration file created: {config_path}")
    return 0


def set_nested(config: Dict[str, Any], path: tuple, value: str) -> None:
    """Set a nested value in a dictionary."""
    cursor = config
    for key in path[:-1]:
        node = cursor.get(key)
        if not isinstance(node, dict):
            node = {}
            cursor[key] = node
        cursor = node
    cursor[path[-1]] = value


def apply_env_overrides(config: Dict[str, Any]) -> Dict[str, Any]:
    """Apply environment variable overrides to the configuration."""
    overrides = {
        "MODEL_ROUTER_KIMI_AUTH_TOKEN": ("models", "kimi", "anthropic_auth_token"),
        "MODEL_ROUTER_OPENAI_AUTH_TOKEN": ("models", "openai", "anthropic_auth_token"),
    }
    for env_name, path in overrides.items():
        value = os.environ.get(env_name)
        if value:
            set_nested(config, path, value)
    return config


def load_config() -> Dict[str, Any]:
    """Load the full configuration with defaults and overrides."""
    config = deep_merge(DEFAULT_CONFIG, load_config_file(get_config_path()))
    return apply_env_overrides(config)


def normalize_value(value: Any, fallback: str = "") -> str:
    """Normalize a configuration value to a string."""
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def build_env_by_model(config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Build environment variable mappings for each configured model."""
    proxy_url = normalize_value(config.get("proxy_url"), DEFAULT_PROXY_URL)
    models = config.get("models") or {}
    env_by_model = {}

    for name in list(models.keys()):
        model_cfg = dict(models.get(name) or {})

        # Check if this model needs proxy
        use_proxy = model_cfg.get("use_proxy", False)

        # Determine default model based on whether it uses proxy (OpenAI-style) or not
        if use_proxy:
            default_model = DEFAULT_OPENAI_CHAT_MODEL
            default_base_url = proxy_url
        else:
            default_model = DEFAULT_KIMI_MODEL
            default_base_url = DEFAULT_KIMI_BASE_URL

        # Use configured base_url if provided, otherwise use default
        base_url = normalize_value(model_cfg.get("anthropic_base_url"), default_base_url)

        model_name = normalize_value(model_cfg.get("anthropic_model"), default_model)

        def pick(key: str) -> str:
            return normalize_value(model_cfg.get(key), model_name)

        env_by_model[name] = {
            "ANTHROPIC_BASE_URL": base_url,
            "ANTHROPIC_AUTH_TOKEN": normalize_value(model_cfg.get("anthropic_auth_token"), ""),
            "ANTHROPIC_MODEL": model_name,
            "ANTHROPIC_DEFAULT_OPUS_MODEL": pick("anthropic_default_opus_model"),
            "ANTHROPIC_DEFAULT_SONNET_MODEL": pick("anthropic_default_sonnet_model"),
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": pick("anthropic_default_haiku_model"),
            "CLAUDE_CODE_SUBAGENT_MODEL": pick("claude_code_subagent_model"),
            "_USE_PROXY": use_proxy,  # Internal flag, not an env var
        }

    return env_by_model
