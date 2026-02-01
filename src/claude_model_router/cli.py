#!/usr/bin/env python3
"""
Main CLI for claude-model-router.
"""
import argparse
import os
import subprocess
import sys
from typing import List, Optional

# Add parent directory to path for direct execution
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

__version__ = "1.0.0"

from claude_model_router.config import (
    CONFIG_KEYS,
    DEFAULT_OPENAI_BASE_URL,
    DEFAULT_OPENAI_CHAT_MODEL,
    DEFAULT_OPENAI_LIGHT_MODEL,
    DEFAULT_PROXY_URL,
    build_env_by_model,
    init_config_file,
    load_config,
    normalize_value,
)
from claude_model_router.env import (
    broadcast_env_change,
    delete_env_user,
    print_config_details,
    refresh_env_from_registry,
    set_env_system,
    set_env_user,
)
from claude_model_router.ip_detect import auto_select_model, warn_openai_in_cn
from claude_model_router.proxy_manager import ensure_proxy_running


def resolve_proxy_url(config: dict) -> str:
    """Resolve the proxy URL from environment or config."""
    proxy_url = os.environ.get("MODEL_ROUTER_PROXY_URL")
    if proxy_url:
        return proxy_url.rstrip("/")
    config_url = config.get("proxy_url")
    if config_url:
        return str(config_url).rstrip("/")
    return DEFAULT_PROXY_URL


def resolve_openai_base_url(config: dict, model_cfg: Optional[dict] = None) -> str:
    """Resolve the OpenAI base URL from config or environment."""
    base_url = None
    if model_cfg:
        base_url = model_cfg.get("openai_base_url")
    if not base_url:
        base_url = (
            os.environ.get("MODEL_ROUTER_OPENAI_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or os.environ.get("OPENAI_API_BASE")
        )
    if not base_url:
        base_url = config.get("openai_base_url")
    if not base_url:
        base_url = DEFAULT_OPENAI_BASE_URL
    return base_url.rstrip("/")


def apply_openai_model_defaults(env_vars: dict, openai_base_url: str) -> None:
    """Apply default models for OpenAI API."""
    if "openai.com" not in openai_base_url.lower():
        return
    if not env_vars.get("ANTHROPIC_MODEL"):
        env_vars["ANTHROPIC_MODEL"] = DEFAULT_OPENAI_CHAT_MODEL
    if not env_vars.get("ANTHROPIC_DEFAULT_OPUS_MODEL"):
        env_vars["ANTHROPIC_DEFAULT_OPUS_MODEL"] = DEFAULT_OPENAI_CHAT_MODEL
    if not env_vars.get("ANTHROPIC_DEFAULT_SONNET_MODEL"):
        env_vars["ANTHROPIC_DEFAULT_SONNET_MODEL"] = DEFAULT_OPENAI_LIGHT_MODEL
    if not env_vars.get("ANTHROPIC_DEFAULT_HAIKU_MODEL"):
        env_vars["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = DEFAULT_OPENAI_LIGHT_MODEL
    if not env_vars.get("CLAUDE_CODE_SUBAGENT_MODEL"):
        env_vars["CLAUDE_CODE_SUBAGENT_MODEL"] = DEFAULT_OPENAI_LIGHT_MODEL


def configure_model(model: str, config: dict, env_by_model: dict) -> tuple:
    """Configure environment for the specified model."""
    env_vars = dict(env_by_model[model])
    proxy_message = None
    proxy_url = resolve_proxy_url(config)
    model_cfg = (config.get("models") or {}).get(model, {})
    openai_base_url = resolve_openai_base_url(config, model_cfg)
    env_vars["MODEL_ROUTER_PROXY_URL"] = proxy_url
    env_vars["MODEL_ROUTER_OPENAI_BASE_URL"] = openai_base_url

    # Check if this model needs proxy (based on config, not model name)
    use_proxy = env_vars.pop("_USE_PROXY", False)

    if use_proxy:
        env_vars["ANTHROPIC_BASE_URL"] = proxy_url
        auth_token = env_vars.get("ANTHROPIC_AUTH_TOKEN")
        if auth_token:
            env_vars["OPENAI_API_KEY"] = auth_token
        env_vars["OPENAI_BASE_URL"] = openai_base_url
        env_vars["OPENAI_API_BASE"] = openai_base_url
        apply_openai_model_defaults(env_vars, openai_base_url)
        _, proxy_message, resolved_proxy_url = ensure_proxy_running(
            proxy_url,
            openai_base_url,
            force_restart=True,
        )
        if resolved_proxy_url and resolved_proxy_url != proxy_url:
            env_vars["ANTHROPIC_BASE_URL"] = resolved_proxy_url
            env_vars["MODEL_ROUTER_PROXY_URL"] = resolved_proxy_url

    env_vars["MODEL_ROUTER_ACTIVE_MODEL"] = model

    system_ok = True
    failed_names = []
    for name, value in env_vars.items():
        delete_env_user(name)
        if not set_env_system(name, value):
            system_ok = False
            failed_names.append(name)

    for name, value in env_vars.items():
        os.environ[name] = value

    broadcast_env_change()
    return system_ok, proxy_message


def detect_active_model(model_names: List[str]) -> Optional[str]:
    """Detect which model is currently active."""
    active = os.environ.get("MODEL_ROUTER_ACTIVE_MODEL")
    if active in model_names:
        return active
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "").strip().lower()
    if "moonshot.cn" in base_url:
        return "kimi"
    if "openai.com" in base_url:
        return "openai"
    return None


def parse_args(argv: List[str], model_names: List[str]):
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Choose model and update environment variables.",
        prefix_chars="-/",
    )
    parser.add_argument(
        "model",
        nargs="?",
        choices=model_names,
        help="Model name: see config models",
    )
    parser.add_argument(
        "/model",
        "--model",
        "-m",
        dest="model_opt",
        choices=model_names,
        help="Model name: see config models",
    )
    parser.add_argument(
        "--version",
        "-v",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    args = parser.parse_args(argv)
    if args.model_opt and args.model and args.model_opt != args.model:
        parser.error("model arguments conflict")
    if args.model_opt:
        args.model = args.model_opt
    if not args.model:
        parser.error("model is required")
    return args


def prompt_select_model(model_names: List[str]) -> Optional[str]:
    """Prompt user to select a model interactively."""
    if not model_names:
        print("No models found in config. Please add models to model-router.config.json first.")
        return None
    print("Please select a model:")
    for idx, name in enumerate(model_names, 1):
        print(f"  {idx}. {name}")
    print("Enter number or model name (press Enter for auto-select):")
    while True:
        try:
            choice = input("> ").strip()
        except EOFError:
            return None
        if not choice:
            return None
        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(model_names):
                return model_names[index - 1]
        if choice in model_names:
            return choice
        print("Invalid input, please try again.")


def run_claude_cli(args: List[str], config: dict, env_by_model: dict) -> int:
    """Run the Claude CLI with current configuration."""
    refresh_env_from_registry(CONFIG_KEYS)
    active_model = detect_active_model(sorted(env_by_model.keys()))
    if active_model:
        print(f"Current model: {active_model}")
    else:
        print("Current model: unknown (please run 'claude-model-router kimi|openai|model' first)")
    print_config_details(CONFIG_KEYS, "Current configuration:")

    # Check if active model needs proxy
    if active_model and active_model in env_by_model:
        use_proxy = env_by_model[active_model].get("_USE_PROXY", False)
        if use_proxy:
            proxy_url = (
                os.environ.get("MODEL_ROUTER_PROXY_URL")
                or os.environ.get("ANTHROPIC_BASE_URL")
                or DEFAULT_PROXY_URL
            )
            model_cfg = (config.get("models") or {}).get(active_model, {})
            openai_base_url = resolve_openai_base_url(config, model_cfg)
            _, proxy_message, resolved_proxy_url = ensure_proxy_running(
                proxy_url,
                openai_base_url,
                force_restart=True,
            )
            if resolved_proxy_url and resolved_proxy_url != proxy_url:
                os.environ["ANTHROPIC_BASE_URL"] = resolved_proxy_url
                os.environ["MODEL_ROUTER_PROXY_URL"] = resolved_proxy_url
            if proxy_message:
                print(proxy_message)

    command = ["claude", *args]
    if os.name == "nt":
        return subprocess.call(subprocess.list2cmdline(command), shell=True)
    return subprocess.call(command)


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point."""
    if argv is None:
        argv = sys.argv[1:]

    if argv and argv[0].lower() == "init":
        return init_config_file()

    config = load_config()
    env_by_model = build_env_by_model(config)
    model_names = sorted(env_by_model.keys())

    if argv and argv[0].lower() == "claude":
        return run_claude_cli(argv[1:], config, env_by_model)

    if argv and argv[0].lower() == "model":
        if len(argv) > 1:
            print("`claude-model-router model` does not accept additional arguments.")
            print("Use `claude-model-router <model-name>` to specify manually.")
            return 2

        selected = None
        if sys.stdin.isatty():
            selected = prompt_select_model(model_names)
        if selected is None:
            selected, note = auto_select_model(model_names)
            print(note)
        if not selected:
            print("No available models found. Please configure models first.")
            return 1

        system_ok, proxy_message = configure_model(selected, config, env_by_model)
        if proxy_message:
            print(proxy_message)
        if system_ok:
            print(f"Model set: {selected} (system environment variables)")
        else:
            print(f"Failed to write system environment variables: {selected}")
            print("Tip: Run as administrator to write system environment variables.")
            print("Current settings only apply to this process and may not persist in new terminals.")
        print_config_details(CONFIG_KEYS, "Updated configuration:")
        return 0

    args = parse_args(argv, model_names)
    if args.model == "openai":
        args.model = warn_openai_in_cn()

    system_ok, proxy_message = configure_model(args.model, config, env_by_model)
    if proxy_message:
        print(proxy_message)
    if system_ok:
        print(f"Model set: {args.model} (system environment variables)")
    else:
        print(f"Failed to write system environment variables: {args.model}")
        print("Tip: Run as administrator to write system environment variables.")
        print("Current settings only apply to this process and may not persist in new terminals.")
    print_config_details(CONFIG_KEYS, "Updated configuration:")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
