# claude-model-router（中文说明）

Windows CLI 用于切换模型配置并更新环境变量。

## 使用方式

运行上面的任一命令后，建议打开新终端以确保环境变量生效。

```bat
claude-model-router init
claude-model-router model
claude-model-router <模型名>
claude-model-router claude
```

**快捷命令：** 使用 `cmr` 作为 `claude-model-router` 的缩写：

```bat
cmr init
cmr model
cmr <模型名>
cmr claude
```

提示：`claude-model-router model` 或 `cmr model` 会列出配置文件中的 models 并提供交互式选择。

## 配置方式

建议先运行 `claude-model-router init` 或 `cmr init` 生成
`model-router.config.json`，再填写密钥。若未安装 Python，
`init` 命令会尝试通过 `winget` 自动安装，安装后
可能需要重新打开终端。也可以用 `MODEL_ROUTER_CONFIG`
指向自定义配置路径。

环境变量覆盖（可选）：
- `MODEL_ROUTER_KIMI_AUTH_TOKEN`
- `MODEL_ROUTER_OPENAI_AUTH_TOKEN`
- `MODEL_ROUTER_PROXY_URL`
- `MODEL_ROUTER_OPENAI_BASE_URL`

## 说明

- `cmr model` 会列出配置文件中的 models 并提供交互式选择；回车则自动检测公网 IP 并选择默认模型。
- `cmr <模型名>` 切换后会输出更新后的配置详情。
- `cmr openai` 会检测 IP，如在中国大陆会提示可能不可用，并询问是否继续或改用 kimi。
- `cmr claude` 会输出当前配置详情，并在当前终端启动 Claude CLI。
- `cmr` 为 `claude-model-router` 的短命令别名。
- 以管理员身份运行可写入系统环境变量；非管理员可能写入失败且仅对当前进程生效。
- `cmr openai` 会自动启动本地协议转换代理，并将 `ANTHROPIC_BASE_URL` 指向代理地址。

## Claude Code 与 OpenAI 兼容 API

Claude Code 遵循 Anthropic 的 `/v1/messages` 协议，并基于
`ANTHROPIC_BASE_URL` 发送请求。许多 OpenAI 兼容服务（如 OpenRouter）
只提供 `/v1/chat/completions`，因此直接把 `ANTHROPIC_BASE_URL` 指向
这些服务通常会失败（路径/协议/鉴权不一致）。

现在 `cmr openai` 已内置并自动启动协议转换代理，代理地址会写入
`MODEL_ROUTER_PROXY_URL`，同时同步到 `ANTHROPIC_BASE_URL`（默认
`http://127.0.0.1:19000`）。上游 OpenAI 基地址可通过
`MODEL_ROUTER_OPENAI_BASE_URL` 指定，默认是 `https://api.openai.com/v1`。
当上游为 OpenAI 官方域名时，会自动使用 `gpt-5.2-codex`（走 `/v1/responses`）
作为默认模型，以获得更好的 Claude Code 兼容性。
