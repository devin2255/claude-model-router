"""
IP geolocation detection for automatic model selection.
"""
import json
import sys
import urllib.error
import urllib.request
from typing import Optional, Tuple


def extract_country_code(payload: dict) -> Optional[str]:
    """Extract country code from IP geolocation API response."""
    if not isinstance(payload, dict):
        return None
    for key in (
        "country_code",
        "countryCode",
        "country_code2",
        "country",
        "country_name",
        "countryName",
    ):
        value = payload.get(key)
        if not value:
            continue
        code = str(value).strip().upper()
        if len(code) == 2:
            return code
        if code in {"CHINA", "PEOPLE'S REPUBLIC OF CHINA", "PRC"}:
            return "CN"
    return None


def fetch_geo_json(url: str, timeout: int = 5) -> Optional[dict]:
    """Fetch geolocation data from an API endpoint."""
    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "claude-model-router/1.0"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "ignore")
        return json.loads(raw)
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, ValueError):
        return None


def detect_country_code() -> Optional[str]:
    """Detect country code from multiple IP geolocation services."""
    urls = [
        "https://ipapi.co/json/",
        "https://ipinfo.io/json",
        "http://ip-api.com/json/",
    ]
    for url in urls:
        payload = fetch_geo_json(url)
        code = extract_country_code(payload)
        if code:
            return code
    return None


def auto_select_model(model_names: list) -> Tuple[Optional[str], str]:
    """Automatically select a model based on IP geolocation."""
    if not model_names:
        model_names = []
    country_code = detect_country_code()
    if country_code == "CN" and "kimi" in model_names:
        return "kimi", "Detected IP in mainland China, defaulting to kimi."
    if country_code and "openai" in model_names:
        return "openai", f"Detected IP in {country_code}, defaulting to openai."
    if "openai" in model_names:
        return "openai", "Could not detect IP location, defaulting to openai."
    if model_names:
        return model_names[0], "Could not detect IP location, using first available model."
    return None, "No available models found."


def warn_openai_in_cn() -> str:
    """Warn user when selecting openai from mainland China."""
    country_code = detect_country_code()
    if country_code != "CN":
        return "openai"
    print("Warning: Detected IP in mainland China, openai may be unavailable.")
    if not sys.stdin.isatty():
        print("Non-interactive mode, continuing with openai.")
        return "openai"
    while True:
        try:
            choice = input("Continue with openai? Enter Y to continue, N to use kimi [Y]: ").strip().lower()
        except EOFError:
            print("Unable to get input, continuing with openai.")
            return "openai"
        if choice in ("", "y", "yes", "openai"):
            return "openai"
        if choice in ("n", "no", "k", "kimi"):
            print("Switched to kimi configuration.")
            return "kimi"
        print("Please enter Y or N.")
