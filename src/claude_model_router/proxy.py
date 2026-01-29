#!/usr/bin/env python3
"""
Protocol translation proxy - Converts Anthropic API to OpenAI API.
"""
import argparse
import json
import os
import sys
import uuid
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional

DEFAULT_UPSTREAM_BASE = "https://api.openai.com/v1"
DEFAULT_USER_AGENT = "claude-model-router-proxy/1.0"
PROXY_VERSION = "1.1"
PROXY_CAPABILITIES = {
    "supports_responses": True,
    "retry_on_not_chat_model": True,
}


def resolve_upstream_base() -> str:
    """Resolve the upstream base URL from environment."""
    base = (
        os.environ.get("MODEL_ROUTER_OPENAI_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("OPENAI_API_BASE")
        or DEFAULT_UPSTREAM_BASE
    )
    return base.rstrip("/")


def build_upstream_url(base: str, endpoint: str) -> str:
    """Build upstream URL from base and endpoint."""
    base = base.rstrip("/")
    endpoint = (endpoint or "").lstrip("/")
    if not endpoint:
        endpoint = "v1/chat/completions"
    if base.endswith("/v1"):
        if endpoint.startswith("v1/"):
            endpoint = endpoint[len("v1/"):]
        return f"{base}/{endpoint}"
    if endpoint.startswith("v1/"):
        return f"{base}/{endpoint}"
    return f"{base}/v1/{endpoint}"


def should_use_responses(model: Optional[str]) -> bool:
    """Check if the model requires the Responses API."""
    if not model:
        return False
    model = str(model).strip()
    if not model:
        return False
    m = model.lower()
    if m.startswith("gpt-5") or m.startswith("o"):
        return True
    if "codex" in m:
        return True
    if os.environ.get("MODEL_ROUTER_FORCE_RESPONSES", "").strip() in {"1", "true", "yes", "on"}:
        return True
    return False


def is_not_chat_model_error(payload: Optional[dict]) -> bool:
    """Check if the error indicates the model doesn't support chat completions."""
    if not isinstance(payload, dict):
        return False
    err = payload.get("error")
    message = ""
    if isinstance(err, dict):
        message = str(err.get("message") or "")
    elif err is not None:
        message = str(err)
    else:
        message = str(payload.get("message") or "")
    msg = message.lower()
    if "not a chat model" in msg and "chat/completions" in msg:
        return True
    return "v1/chat/completions" in msg


def safe_json_loads(text: str) -> Optional[dict]:
    """Safely parse JSON, returning None on failure."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def coerce_text(content: Any) -> str:
    """Coerce content to text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                block_type = block.get("type")
                if block_type == "text":
                    parts.append(block.get("text", ""))
                elif block_type == "image":
                    parts.append("[image omitted]")
                else:
                    parts.append("[unsupported content omitted]")
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content)


def map_tools(tools: List[dict]) -> List[dict]:
    """Map Anthropic tools to OpenAI format."""
    mapped = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        name = tool.get("name")
        if not name:
            continue
        fn = {"name": name}
        if tool.get("description"):
            fn["description"] = tool["description"]
        if tool.get("input_schema"):
            fn["parameters"] = tool["input_schema"]
        mapped.append({"type": "function", "function": fn})
    return mapped


def map_tools_responses(tools: List[dict]) -> List[dict]:
    """Map Anthropic tools to OpenAI Responses API format."""
    mapped = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        name = tool.get("name")
        if not name:
            continue
        fn = {"type": "function", "name": name}
        if tool.get("description"):
            fn["description"] = tool["description"]
        if tool.get("input_schema"):
            fn["parameters"] = tool["input_schema"]
        if "strict" in tool:
            fn["strict"] = bool(tool["strict"])
        mapped.append(fn)
    return mapped


def map_tool_choice(tool_choice: Any) -> Any:
    """Map Anthropic tool choice to OpenAI format."""
    if isinstance(tool_choice, str):
        return tool_choice
    if not isinstance(tool_choice, dict):
        return "auto"
    choice_type = tool_choice.get("type")
    if choice_type in {"auto", "none"}:
        return choice_type
    if choice_type == "tool" and tool_choice.get("name"):
        return {"type": "function", "function": {"name": tool_choice["name"]}}
    return "auto"


def map_tool_choice_responses(tool_choice: Any) -> Any:
    """Map Anthropic tool choice to OpenAI Responses API format."""
    if isinstance(tool_choice, str):
        return tool_choice
    if not isinstance(tool_choice, dict):
        return "auto"
    choice_type = tool_choice.get("type")
    if choice_type in {"auto", "none", "required"}:
        return choice_type
    if choice_type == "tool" and tool_choice.get("name"):
        return {"type": "function", "name": tool_choice["name"]}
    return "auto"


def map_tool_use(block: dict) -> dict:
    """Map a tool_use block to OpenAI tool_calls format."""
    tool_id = block.get("id") or f"tool_{uuid.uuid4().hex}"
    name = block.get("name") or "tool"
    input_value = block.get("input", {})
    if isinstance(input_value, str):
        arguments = input_value
    else:
        arguments = json.dumps(input_value, ensure_ascii=False)
    return {
        "id": tool_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def map_tool_result(block: dict) -> dict:
    """Map a tool_result block to OpenAI tool response format."""
    tool_id = block.get("tool_use_id") or block.get("id") or "tool_unknown"
    content = coerce_text(block.get("content"))
    if block.get("is_error"):
        content = f"[tool_error] {content}"
    return {"role": "tool", "tool_call_id": tool_id, "content": content}


def convert_anthropic_message_to_responses_items(message: dict) -> List[dict]:
    """Convert an Anthropic message to OpenAI Responses API items."""
    if not isinstance(message, dict):
        return []
    role = message.get("role", "user")
    content = message.get("content")
    if isinstance(content, str):
        return [{"role": role, "content": content}]
    if not isinstance(content, list):
        return []
    items = []
    text_parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text_parts.append(block.get("text", ""))
        elif block_type == "tool_use":
            tool_id = block.get("id") or f"tool_{uuid.uuid4().hex}"
            name = block.get("name") or "tool"
            arguments = block.get("input", {})
            if isinstance(arguments, str):
                args_str = arguments
            else:
                args_str = json.dumps(arguments, ensure_ascii=False)
            items.append({
                "type": "function_call",
                "id": f"fc_{tool_id}",
                "call_id": tool_id,
                "name": name,
                "arguments": args_str,
            })
        elif block_type == "tool_result":
            call_id = block.get("tool_use_id") or block.get("id") or "tool_unknown"
            output = coerce_text(block.get("content"))
            if block.get("is_error"):
                output = f"[tool_error] {output}"
            items.append({"type": "function_call_output", "call_id": call_id, "output": output})
        elif block_type == "image":
            text_parts.append("[image omitted]")
        else:
            text_parts.append("[unsupported content omitted]")
    if text_parts:
        items.insert(0, {"role": role, "content": "".join(text_parts)})
    return items


def convert_anthropic_message(message: dict) -> List[dict]:
    """Convert an Anthropic message to OpenAI format."""
    if not isinstance(message, dict):
        return []
    role = message.get("role", "user")
    content = message.get("content")
    if isinstance(content, str):
        return [{"role": role, "content": content}]
    if not isinstance(content, list):
        return []
    text_parts = []
    tool_calls = []
    tool_results = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text_parts.append(block.get("text", ""))
        elif block_type == "tool_use":
            tool_calls.append(map_tool_use(block))
        elif block_type == "tool_result":
            tool_results.append(map_tool_result(block))
        elif block_type == "image":
            text_parts.append("[image omitted]")
        else:
            text_parts.append("[unsupported content omitted]")
    messages = []
    if text_parts or tool_calls:
        msg = {"role": role, "content": "".join(text_parts)}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        messages.append(msg)
    messages.extend(tool_results)
    return messages


def anthropic_to_openai(payload: dict) -> dict:
    """Convert Anthropic request payload to OpenAI format."""
    openai = {}
    model = payload.get("model")
    if model:
        openai["model"] = model
    if "max_tokens" in payload:
        openai["max_tokens"] = payload["max_tokens"]
    if "temperature" in payload:
        openai["temperature"] = payload["temperature"]
    if "top_p" in payload:
        openai["top_p"] = payload["top_p"]
    if "stop_sequences" in payload:
        openai["stop"] = payload["stop_sequences"]
    if "tools" in payload:
        openai["tools"] = map_tools(payload["tools"])
    if "tool_choice" in payload:
        openai["tool_choice"] = map_tool_choice(payload["tool_choice"])
    messages = []
    system_text = coerce_text(payload.get("system"))
    if system_text:
        messages.append({"role": "system", "content": system_text})
    for msg in payload.get("messages", []) or []:
        messages.extend(convert_anthropic_message(msg))
    openai["messages"] = messages
    return openai


def anthropic_to_openai_responses(payload: dict) -> dict:
    """Convert Anthropic request to OpenAI Responses API format."""
    openai = {}
    model = payload.get("model")
    if model:
        openai["model"] = model
    if "max_tokens" in payload:
        openai["max_output_tokens"] = payload["max_tokens"]
    if "temperature" in payload:
        openai["temperature"] = payload["temperature"]
    if "top_p" in payload:
        openai["top_p"] = payload["top_p"]
    if "tools" in payload:
        openai["tools"] = map_tools_responses(payload["tools"])
    if "tool_choice" in payload:
        openai["tool_choice"] = map_tool_choice_responses(payload["tool_choice"])
    system_text = coerce_text(payload.get("system"))
    if system_text:
        openai["instructions"] = system_text
    input_items = []
    for msg in payload.get("messages", []) or []:
        input_items.extend(convert_anthropic_message_to_responses_items(msg))
    openai["input"] = input_items
    openai["store"] = False
    return openai


def openai_message_to_blocks(message: dict) -> tuple:
    """Extract content blocks and tool calls from OpenAI message."""
    blocks = []
    text_content = message.get("content")
    if isinstance(text_content, list):
        text_content = "".join(
            part.get("text", "") for part in text_content if part.get("type") == "text"
        )
    if text_content:
        blocks.append({"type": "text", "text": text_content})
    tool_calls = message.get("tool_calls") or []
    for call in tool_calls:
        func = call.get("function") or {}
        name = func.get("name") or "tool"
        args_raw = func.get("arguments") or ""
        try:
            args = json.loads(args_raw) if args_raw else {}
        except json.JSONDecodeError:
            args = {"_raw": args_raw}
        tool_id = call.get("id") or f"tool_{uuid.uuid4().hex}"
        blocks.append({"type": "tool_use", "id": tool_id, "name": name, "input": args})
    return blocks, bool(tool_calls)


def map_finish_reason(finish_reason: Optional[str], has_tool_calls: bool) -> str:
    """Map OpenAI finish reason to Anthropic format."""
    if finish_reason == "tool_calls" or has_tool_calls:
        return "tool_use"
    if finish_reason == "length":
        return "max_tokens"
    return "end_turn"


def openai_to_anthropic(payload: dict) -> dict:
    """Convert OpenAI response to Anthropic format."""
    choices = payload.get("choices") or []
    choice = choices[0] if choices else {}
    message = choice.get("message") or {}
    blocks, has_tool_calls = openai_message_to_blocks(message)
    finish_reason = choice.get("finish_reason")
    usage = payload.get("usage") or {}
    return {
        "id": f"msg_{payload.get('id') or uuid.uuid4().hex}",
        "type": "message",
        "role": "assistant",
        "model": payload.get("model") or message.get("model") or "",
        "content": blocks,
        "stop_reason": map_finish_reason(finish_reason, has_tool_calls),
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }


def openai_responses_to_anthropic(payload: dict, requested_model: Optional[str] = None) -> dict:
    """Convert OpenAI Responses API output to Anthropic format."""
    output = payload.get("output") or []
    blocks = []
    has_tool_calls = False
    for item in output:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "message" and item.get("role") == "assistant":
            content = item.get("content") or []
            if isinstance(content, str):
                blocks.append({"type": "text", "text": content})
            elif isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "output_text" and part.get("text"):
                        blocks.append({"type": "text", "text": part.get("text", "")})
        elif item_type == "function_call":
            has_tool_calls = True
            call_id = item.get("call_id") or item.get("id") or f"tool_{uuid.uuid4().hex}"
            name = item.get("name") or "tool"
            args_raw = item.get("arguments") or ""
            try:
                args = json.loads(args_raw) if args_raw else {}
            except json.JSONDecodeError:
                args = {"_raw": args_raw}
            blocks.append({"type": "tool_use", "id": call_id, "name": name, "input": args})
    usage = payload.get("usage") or {}
    normalized_usage = {
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
    }
    stop_reason = "end_turn"
    if has_tool_calls:
        stop_reason = "tool_use"
    incomplete = payload.get("incomplete_details") or {}
    if isinstance(incomplete, dict) and incomplete.get("reason") in {"max_tokens", "max_output_tokens"}:
        stop_reason = "max_tokens"
    return {
        "id": f"msg_{payload.get('id') or uuid.uuid4().hex}",
        "type": "message",
        "role": "assistant",
        "model": payload.get("model") or requested_model or "",
        "content": blocks or [{"type": "text", "text": ""}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": normalized_usage,
    }


def extract_api_key(headers: dict) -> Optional[str]:
    """Extract API key from request headers."""
    api_key = headers.get("x-api-key") or headers.get("X-Api-Key")
    if api_key:
        return api_key.strip()
    auth = headers.get("Authorization") or headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(None, 1)[1].strip()
    return os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")


class AnthropicStreamWriter:
    """Handles streaming response conversion from OpenAI to Anthropic format."""

    def __init__(self, handler, requested_model: Optional[str]):
        self.handler = handler
        self.requested_model = requested_model
        self.started = False
        self.message_id = None
        self.model = None
        self.next_index = 0
        self.text_index = None
        self.started_blocks = []
        self.tool_states = {}
        self.finish_reason = None
        self.usage = None

    def _write_event(self, event: str, data: dict) -> None:
        payload = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        try:
            self.handler.wfile.write(payload.encode("utf-8"))
            self.handler.wfile.flush()
        except BrokenPipeError:
            raise

    def _start_message(self, message_id: Optional[str], model: Optional[str]) -> None:
        if self.started:
            return
        self.message_id = f"msg_{message_id or uuid.uuid4().hex}"
        self.model = model or self.requested_model or ""
        self.started = True
        self._write_event(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": self.message_id,
                    "type": "message",
                    "role": "assistant",
                    "model": self.model,
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            },
        )

    def _start_text_block(self) -> int:
        if self.text_index is not None:
            return self.text_index
        index = self.next_index
        self.next_index += 1
        self.text_index = index
        self.started_blocks.append(index)
        self._write_event(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": index,
                "content_block": {"type": "text", "text": ""},
            },
        )
        return index

    def _start_tool_block(self, tool_index: int, tool_id: str, name: str) -> int:
        if tool_index in self.tool_states and self.tool_states[tool_index].get("content_index") is not None:
            return self.tool_states[tool_index]["content_index"]
        index = self.next_index
        self.next_index += 1
        state = self.tool_states.setdefault(tool_index, {})
        state["content_index"] = index
        state["started"] = True
        self.started_blocks.append(index)
        self._write_event(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": index,
                "content_block": {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": name,
                    "input": {},
                },
            },
        )
        return index

    def handle_text_delta(self, text: Optional[str]) -> None:
        if text is None:
            return
        index = self._start_text_block()
        self._write_event(
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": index,
                "delta": {"type": "text_delta", "text": text},
            },
        )

    def handle_tool_delta(self, tool_call: dict) -> None:
        tool_index = tool_call.get("index", 0)
        state = self.tool_states.setdefault(tool_index, {"pending_args": []})
        if tool_call.get("id"):
            state["id"] = tool_call["id"]
        function = tool_call.get("function") or {}
        if function.get("name"):
            state["name"] = function["name"]
        args_fragment = function.get("arguments")
        if args_fragment:
            state.setdefault("pending_args", []).append(args_fragment)
        if state.get("started"):
            for fragment in state.get("pending_args") or []:
                self._write_event(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": state["content_index"],
                        "delta": {"type": "input_json_delta", "partial_json": fragment},
                    },
                )
            state["pending_args"] = []
            return
        if state.get("name"):
            tool_id = state.get("id") or f"tool_{uuid.uuid4().hex}"
            index = self._start_tool_block(tool_index, tool_id, state["name"])
            for fragment in state.get("pending_args") or []:
                self._write_event(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": index,
                        "delta": {"type": "input_json_delta", "partial_json": fragment},
                    },
                )
            state["pending_args"] = []

    def finalize_pending_tools(self) -> None:
        for tool_index, state in list(self.tool_states.items()):
            if state.get("started"):
                continue
            if not state.get("name") and not (state.get("pending_args") or []):
                continue
            tool_id = state.get("id") or f"tool_{uuid.uuid4().hex}"
            name = state.get("name") or "tool"
            index = self._start_tool_block(tool_index, tool_id, name)
            for fragment in state.get("pending_args") or []:
                self._write_event(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": index,
                        "delta": {"type": "input_json_delta", "partial_json": fragment},
                    },
                )
            state["pending_args"] = []

    def finish(self) -> None:
        self.finalize_pending_tools()
        stop_reason = map_finish_reason(self.finish_reason, bool(self.tool_states))
        for index in self.started_blocks:
            self._write_event(
                "content_block_stop",
                {"type": "content_block_stop", "index": index},
            )
        message_delta = {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
        }
        if self.usage:
            message_delta["usage"] = {
                "input_tokens": self.usage.get("prompt_tokens", 0),
                "output_tokens": self.usage.get("completion_tokens", 0),
            }
        self._write_event("message_delta", message_delta)
        self._write_event("message_stop", {"type": "message_stop"})


class ProxyHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the protocol translation proxy."""

    protocol_version = "HTTP/1.1"

    def _send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_text(self, status: int, text: str) -> None:
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/health":
            self._send_json(
                200,
                {
                    "status": "ok",
                    "proxy": "claude-model-router",
                    "version": PROXY_VERSION,
                    "capabilities": PROXY_CAPABILITIES,
                },
            )
            return
        self._send_text(404, "Not Found")

    def do_POST(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        if not (path.endswith("/messages") or path.endswith("/v1/messages")):
            self._send_text(404, "Not Found")
            return

        raw_body = self._read_body()
        payload = safe_json_loads(raw_body.decode("utf-8", "ignore") or "{}")
        if not isinstance(payload, dict):
            self._send_json(400, {"error": {"type": "invalid_request", "message": "Invalid JSON"}})
            return

        stream = bool(payload.get("stream"))
        requested_model = payload.get("model")
        use_responses = should_use_responses(requested_model)
        api_key = extract_api_key(self.headers)
        if not api_key:
            self._send_json(401, {"error": {"type": "auth_error", "message": "Missing API key"}})
            return

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": DEFAULT_USER_AGENT,
        }

        def _send_upstream(use_responses: bool):
            if use_responses:
                openai_payload = anthropic_to_openai_responses(payload)
                endpoint = "v1/responses"
            else:
                openai_payload = anthropic_to_openai(payload)
                endpoint = "v1/chat/completions"
            openai_payload["stream"] = stream
            upstream_url = build_upstream_url(self.server.upstream_base, endpoint)
            request_data = json.dumps(openai_payload, ensure_ascii=False).encode("utf-8")
            request = urllib.request.Request(upstream_url, data=request_data, headers=headers, method="POST")
            with urllib.request.urlopen(request, timeout=self.server.upstream_timeout) as response:
                if stream:
                    if use_responses:
                        self._handle_responses_stream(response, openai_payload.get("model"))
                    else:
                        self._handle_stream(response, openai_payload.get("model"))
                else:
                    raw = response.read().decode("utf-8", "ignore")
                    upstream_payload = safe_json_loads(raw) or {}
                    if use_responses:
                        self._send_json(
                            response.status,
                            openai_responses_to_anthropic(
                                upstream_payload,
                                openai_payload.get("model"),
                            ),
                        )
                    else:
                        self._send_json(response.status, openai_to_anthropic(upstream_payload))

        try:
            _send_upstream(use_responses)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "ignore")
            error_payload = safe_json_loads(body)
            if (not use_responses) and is_not_chat_model_error(error_payload):
                try:
                    _send_upstream(True)
                    return
                except urllib.error.HTTPError as retry_exc:
                    retry_body = retry_exc.read().decode("utf-8", "ignore")
                    retry_payload = safe_json_loads(retry_body)
                    if retry_payload is None:
                        self._send_text(retry_exc.code, retry_body or "Upstream error")
                    else:
                        self._send_json(retry_exc.code, retry_payload)
                    return
            if error_payload is None:
                self._send_text(exc.code, body or "Upstream error")
            else:
                self._send_json(exc.code, error_payload)
        except urllib.error.URLError as exc:
            self._send_json(502, {"error": {"type": "upstream_error", "message": str(exc)}})

    def _handle_stream(self, response, requested_model: Optional[str]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        writer = AnthropicStreamWriter(self, requested_model)
        try:
            for raw_line in response:
                line = raw_line.decode("utf-8", "ignore").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                event_payload = safe_json_loads(data)
                if not isinstance(event_payload, dict):
                    continue
                if not writer.started:
                    writer._start_message(event_payload.get("id"), event_payload.get("model"))
                usage = event_payload.get("usage")
                if isinstance(usage, dict):
                    writer.usage = usage
                choices = event_payload.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                delta = choice.get("delta") or {}
                if "content" in delta:
                    writer.handle_text_delta(delta.get("content"))
                for tool_call in delta.get("tool_calls") or []:
                    if isinstance(tool_call, dict):
                        writer.handle_tool_delta(tool_call)
                if choice.get("finish_reason"):
                    writer.finish_reason = choice.get("finish_reason")
        except BrokenPipeError:
            return
        if writer.started:
            writer.finish()

    def _handle_responses_stream(self, response, requested_model: Optional[str]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        writer = AnthropicStreamWriter(self, requested_model)
        tool_args = {}
        try:
            for raw_line in response:
                line = raw_line.decode("utf-8", "ignore").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                event = safe_json_loads(data)
                if not isinstance(event, dict):
                    continue
                etype = event.get("type")
                if etype in {"response.created", "response.in_progress", "response.queued"}:
                    resp = event.get("response") or {}
                    if not writer.started:
                        writer._start_message(resp.get("id"), resp.get("model") or requested_model)
                    continue
                if etype == "response.output_text.delta":
                    if not writer.started:
                        writer._start_message(event.get("response_id"), requested_model)
                    writer.handle_text_delta(event.get("delta"))
                    continue
                if etype == "response.output_text.done":
                    if not writer.started:
                        writer._start_message(event.get("response_id"), requested_model)
                    writer.handle_text_delta(event.get("text"))
                    continue
                if etype == "response.output_item.added":
                    item = event.get("item") or {}
                    if not isinstance(item, dict):
                        continue
                    if item.get("type") != "function_call":
                        continue
                    index = int(event.get("output_index", 0) or 0)
                    call_id = item.get("call_id") or item.get("id") or f"tool_{uuid.uuid4().hex}"
                    name = item.get("name") or "tool"
                    args = item.get("arguments") or ""
                    tool_args[index] = args
                    if not writer.started:
                        writer._start_message(event.get("response_id"), requested_model)
                    writer.handle_tool_delta(
                        {"index": index, "id": call_id, "function": {"name": name, "arguments": args}}
                    )
                    continue
                if etype == "response.function_call_arguments.delta":
                    index = int(event.get("output_index", 0) or 0)
                    delta = event.get("delta") or ""
                    tool_args[index] = tool_args.get(index, "") + delta
                    if not writer.started:
                        writer._start_message(event.get("response_id"), requested_model)
                    writer.handle_tool_delta({"index": index, "function": {"arguments": delta}})
                    continue
                if etype == "response.function_call_arguments.done":
                    index = int(event.get("output_index", 0) or 0)
                    full = event.get("arguments") or ""
                    prev = tool_args.get(index, "")
                    if full and full.startswith(prev):
                        remaining = full[len(prev):]
                        if remaining:
                            writer.handle_tool_delta({"index": index, "function": {"arguments": remaining}})
                        tool_args[index] = full
                    continue
                if etype in {"response.completed", "response.incomplete", "response.failed"}:
                    resp = event.get("response") or {}
                    if not writer.started:
                        writer._start_message(
                            resp.get("id") or event.get("response_id"),
                            resp.get("model") or requested_model,
                        )
                    usage = resp.get("usage")
                    if isinstance(usage, dict):
                        writer.usage = {
                            "prompt_tokens": usage.get("input_tokens", 0),
                            "completion_tokens": usage.get("output_tokens", 0),
                        }
                    incomplete = resp.get("incomplete_details") or {}
                    if isinstance(incomplete, dict) and incomplete.get("reason") in {
                        "max_tokens",
                        "max_output_tokens",
                    }:
                        writer.finish_reason = "length"
                    break
        except BrokenPipeError:
            return
        if writer.started:
            writer.finish()


def parse_args(argv: List[str]):
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="claude-model-router proxy")
    parser.add_argument("--host", default=os.environ.get("MODEL_ROUTER_PROXY_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MODEL_ROUTER_PROXY_PORT", "19000")))
    parser.add_argument("--upstream", default=resolve_upstream_base())
    parser.add_argument("--timeout", type=int, default=60)
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point for the proxy server."""
    if argv is None:
        argv = sys.argv[1:]
    args = parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), ProxyHandler)
    server.upstream_timeout = args.timeout
    server.upstream_base = args.upstream.rstrip("/")
    server.daemon_threads = True
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
