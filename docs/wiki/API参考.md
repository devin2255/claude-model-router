# API 参考

## 代理服务器 API

代理服务器（model-router-proxy.py）提供 Anthropic API 兼容接口，将请求转换为 OpenAI 格式。

### 基础信息

| 属性 | 值 |
|------|-----|
| 默认地址 | `http://127.0.0.1:19000` |
| 协议 | HTTP/1.1 |
| 内容类型 | `application/json` |
| 认证 | Bearer Token 或 x-api-key |

### 端点列表

#### 健康检查

```
GET /health
```

**响应**：

```json
{
  "status": "ok",
  "proxy": "model-router",
  "version": "1.1",
  "capabilities": {
    "supports_responses": true,
    "retry_on_not_chat_model": true
  }
}
```

**字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| status | string | 状态，固定为 "ok" |
| proxy | string | 代理名称 |
| version | string | 代理版本 |
| capabilities.supports_responses | boolean | 是否支持 Responses API |
| capabilities.retry_on_not_chat_model | boolean | 是否支持 chat 模型错误重试 |

#### 消息接口

```
POST /v1/messages
```

**请求头**：

| 头字段 | 必需 | 说明 |
|--------|------|------|
| Authorization | 是 | `Bearer {api_key}` |
| Content-Type | 是 | `application/json` |

**请求体**（Anthropic 格式）：

```json
{
  "model": "gpt-5.2-codex",
  "messages": [
    {
      "role": "user",
      "content": "Hello!"
    }
  ],
  "max_tokens": 1024,
  "temperature": 0.7,
  "stream": false
}
```

**请求字段**：

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| model | string | 是 | 模型名称 |
| messages | array | 是 | 消息列表 |
| max_tokens | integer | 否 | 最大输出 token 数 |
| temperature | float | 否 | 温度参数 (0-1) |
| top_p | float | 否 | Top-p 采样 |
| stop_sequences | array | 否 | 停止序列 |
| tools | array | 否 | 工具定义 |
| tool_choice | string/object | 否 | 工具选择策略 |
| stream | boolean | 否 | 是否流式响应 |
| system | string | 否 | 系统提示词 |

**响应**（Anthropic 格式）：

```json
{
  "id": "msg_abc123",
  "type": "message",
  "role": "assistant",
  "model": "gpt-5.2-codex",
  "content": [
    {
      "type": "text",
      "text": "Hello! How can I help you today?"
    }
  ],
  "stop_reason": "end_turn",
  "stop_sequence": null,
  "usage": {
    "input_tokens": 10,
    "output_tokens": 20
  }
}
```

## 协议转换说明

### 请求转换

#### Anthropic → OpenAI (Chat Completions)

| Anthropic | OpenAI | 转换说明 |
|-----------|--------|----------|
| `messages` | `messages` | 直接传递，转换内容块 |
| `system` | `messages[0]` | 转为 system 角色消息 |
| `max_tokens` | `max_tokens` | 直接映射 |
| `temperature` | `temperature` | 直接映射 |
| `top_p` | `top_p` | 直接映射 |
| `stop_sequences` | `stop` | 直接映射 |
| `tools` | `tools` | 格式转换 |
| `tool_choice` | `tool_choice` | 格式转换 |
| `stream` | `stream` | 直接映射 |

#### Anthropic → OpenAI (Responses API)

用于 GPT-5、o 系列和 codex 模型：

| Anthropic | OpenAI | 转换说明 |
|-----------|--------|----------|
| `messages` | `input` | 转为 input items |
| `system` | `instructions` | 转为 instructions |
| `max_tokens` | `max_output_tokens` | 字段名变更 |
| `tools` | `tools` | 格式转换（简化版） |
| `tool_choice` | `tool_choice` | 格式转换 |
| `store` | - | 固定为 false |

### 消息内容转换

#### Anthropic 内容块 → OpenAI 消息

**文本块**：
```json
// Anthropic
{"type": "text", "text": "Hello"}

// OpenAI
{"role": "user", "content": "Hello"}
```

**工具调用**：
```json
// Anthropic
{"type": "tool_use", "id": "tool_123", "name": "search", "input": {"q": "test"}}

// OpenAI
{"role": "assistant", "tool_calls": [{"id": "tool_123", "type": "function", "function": {"name": "search", "arguments": "{\"q\": \"test\"}"}}]}
```

**工具结果**：
```json
// Anthropic
{"type": "tool_result", "tool_use_id": "tool_123", "content": "result"}

// OpenAI
{"role": "tool", "tool_call_id": "tool_123", "content": "result"}
```

### 响应转换

#### OpenAI → Anthropic

| OpenAI | Anthropic | 转换说明 |
|--------|-----------|----------|
| `choices[0].message.content` | `content[0].text` | 转为文本块 |
| `choices[0].message.tool_calls` | `content[].tool_use` | 转为工具块 |
| `choices[0].finish_reason` | `stop_reason` | 映射结束原因 |
| `usage.prompt_tokens` | `usage.input_tokens` | 字段名变更 |
| `usage.completion_tokens` | `usage.output_tokens` | 字段名变更 |

#### 结束原因映射

| OpenAI | Anthropic |
|--------|-----------|
| `stop` | `end_turn` |
| `tool_calls` | `tool_use` |
| `length` | `max_tokens` |
| `content_filter` | `end_turn` |

## 流式响应（SSE）

### 请求

设置 `"stream": true` 启用流式响应。

### 响应格式

```
event: message_start
data: {"type": "message_start", "message": {...}}

event: content_block_start
data: {"type": "content_block_start", "index": 0, "content_block": {...}}

event: content_block_delta
data: {"type": "content_block_delta", "index": 0, "delta": {...}}

event: content_block_stop
data: {"type": "content_block_stop", "index": 0}

event: message_delta
data: {"type": "message_delta", "delta": {...}}

event: message_stop
data: {"type": "message_stop"}
```

### 事件类型

| 事件 | 说明 |
|------|------|
| `message_start` | 消息开始 |
| `content_block_start` | 内容块开始 |
| `content_block_delta` | 内容增量 |
| `content_block_stop` | 内容块结束 |
| `message_delta` | 消息元数据更新 |
| `message_stop` | 消息结束 |

## 工具调用

### 工具定义转换

**Anthropic 格式**：
```json
{
  "name": "get_weather",
  "description": "Get weather information",
  "input_schema": {
    "type": "object",
    "properties": {
      "location": {"type": "string"}
    }
  }
}
```

**OpenAI 格式**：
```json
{
  "type": "function",
  "function": {
    "name": "get_weather",
    "description": "Get weather information",
    "parameters": {
      "type": "object",
      "properties": {
        "location": {"type": "string"}
      }
    }
  }
}
```

## 错误处理

### 错误响应格式

```json
{
  "error": {
    "type": "error_type",
    "message": "Error description"
  }
}
```

### HTTP 状态码

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 400 | 请求格式错误 |
| 401 | 认证失败 |
| 404 | 端点不存在 |
| 502 | 上游服务错误 |

## 相关源码文件

- `model-router-proxy.py:282-306` - anthropic_to_openai 转换
- `model-router-proxy.py:309-333` - anthropic_to_openai_responses 转换
- `model-router-proxy.py:367-386` - openai_to_anthropic 转换
- `model-router-proxy.py:389-439` - openai_responses_to_anthropic 转换
- `model-router-proxy.py:452-627` - AnthropicStreamWriter 流式处理
- `model-router-proxy.py:629-880` - ProxyHandler HTTP 处理器
