# claude-model-router

Windows CLI tool for [Claude Code](https://github.com/anthropics/claude-code) to switch between AI models and automatically translate API protocols.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Features

- **Model Switching**: Easily switch between Kimi (Moonshot), OpenAI, and other AI providers
- **Protocol Translation**: Built-in proxy converts Anthropic API to OpenAI-compatible format
- **Auto-Detection**: Automatically detects your location and suggests the best model
- **Windows Integration**: Manages Windows environment variables seamlessly
- **Zero Dependencies**: Uses only Python standard library

## Quick Start

### Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/claude-model-router.git
cd claude-model-router
```

2. Add `scripts` folder to your PATH, or use the full path to run.

3. Initialize configuration:
```cmd
claude-model-router init
```

4. Edit `model-router.config.json` and add your API keys.

### Usage

```cmd
# Switch to Kimi (Moonshot)
claude-model-router kimi

# Switch to OpenAI
claude-model-router openai

# Interactive model selection with auto-detection
claude-model-router model

# Launch Claude Code with current settings
claude-model-router claude
```

**Shortcut:** Use `cmr` as shorthand for `claude-model-router`:

```cmd
cmr kimi
cmr openai
cmr model
cmr claude
```

## Configuration

Create `model-router.config.json` in the project root:

```json
{
  "proxy_url": "http://127.0.0.1:19000",
  "openai_base_url": "https://api.openai.com/v1",
  "models": {
    "kimi": {
      "anthropic_base_url": "https://api.moonshot.cn/anthropic",
      "anthropic_auth_token": "YOUR_KIMI_API_KEY",
      "anthropic_model": "kimi-k2.5"
    },
    "openai": {
      "anthropic_auth_token": "YOUR_OPENAI_API_KEY",
      "anthropic_model": "gpt-5.2-codex"
    }
  }
}
```

## How It Works

When you switch to `openai`:
1. The tool automatically starts a local proxy server (default: `http://127.0.0.1:19000`)
2. Sets `ANTHROPIC_BASE_URL` to point to this proxy
3. The proxy translates Anthropic `/v1/messages` requests to OpenAI `/v1/chat/completions` or `/v1/responses`
4. Supports streaming responses and tool calls

## Documentation

- [English Documentation](docs/README.md)
- [中文文档](docs/README_CN.md)
- [Wiki Documentation](docs/wiki/)

## Requirements

- Windows 10/11
- Python 3.6+
- Claude Code installed

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
