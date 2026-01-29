# model-router

Windows CLI to switch model settings and update environment variables.

## Usage

Open a new terminal after running for the updated environment to take effect.

```bat
model-router init
model-router model
model-router <model-name>
model-router claude
```

Tip: `model-router model` lists configured models and prompts for selection.

## Configuration

Run `model-router init` to generate `model-router.config.json`
from the example template, then fill in the API keys. If Python
is missing, `model-router init` will try to install it via `winget`
and you may need to reopen the terminal afterward.
You can also point to a custom path with `MODEL_ROUTER_CONFIG`.

Environment overrides (optional):
- `MODEL_ROUTER_KIMI_AUTH_TOKEN`
- `MODEL_ROUTER_OPENAI_AUTH_TOKEN`
- `MODEL_ROUTER_PROXY_URL`
- `MODEL_ROUTER_OPENAI_BASE_URL`

## Notes

- Running as Administrator will write system environment variables.
- Without admin rights, writing system variables may fail and only apply to the current process.
- `model-router model` lists configured models and prompts for selection; press Enter to auto-detect IP and choose a default.
- `model-router <model-name>` prints the updated config details after switching.
- `model-router openai` checks IP location, warns in mainland China, and prompts to continue or switch to kimi.
- `model-router claude` will print current config details and launch the Claude CLI in the same terminal.
- `mr` is a short alias for `model-router`.
- `/model` or `-m` is still supported for compatibility.
- `model-router model` auto-detects IP location and picks kimi (CN) or openai (non-CN) when available.
- `model-router openai` auto-starts a local protocol translation proxy and points `ANTHROPIC_BASE_URL` at it.

## Claude Code + OpenAI-compatible APIs

Claude Code uses Anthropic's `/v1/messages` API and builds requests based on
`ANTHROPIC_BASE_URL`. Many OpenAI-compatible services (for example OpenRouter)
only expose `/v1/chat/completions`, so pointing `ANTHROPIC_BASE_URL` directly
to those services often fails due to mismatched endpoints and auth behavior.

`model-router openai` now ships with a built-in protocol translation proxy and
auto-starts it. The proxy URL is written to `MODEL_ROUTER_PROXY_URL` and mirrored
to `ANTHROPIC_BASE_URL` (default `http://127.0.0.1:19000`). You can override
the upstream OpenAI base URL with `MODEL_ROUTER_OPENAI_BASE_URL`, which defaults
to `https://api.openai.com/v1`.
When the upstream is the official OpenAI domain, defaults are set to
`gpt-5.2-codex` (Responses API) for best Claude Code compatibility.