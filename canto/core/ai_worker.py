from __future__ import annotations

import json
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Protocol
from uuid import uuid4

import requests

from canto.models.ai_workers import (
    AIEndpointRecord,
    AIModelRecord,
    WorkerBudgetPolicy,
    WorkerUsageRecord,
)
from canto.models.delegation import DelegationScope
from canto.models.schemas import utc_now


class APIWorkerError(RuntimeError):
    def __init__(self, message: str, usage: WorkerUsageRecord | None = None):
        self.usage = usage
        super().__init__(message)


@dataclass(frozen=True)
class AgentToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class AgentResponse:
    text: str = ""
    tool_calls: list[AgentToolCall] = field(default_factory=list)
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    request_id: str | None = None


class AgentAdapter(Protocol):
    def complete(
        self,
        endpoint: AIEndpointRecord,
        credential: str | None,
        model_id: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AgentResponse: ...


class HttpAgentAdapter:
    """Provider transport with one normalized tool-call contract."""

    def __init__(self, session: requests.Session | None = None, timeout: float = 120):
        self.session = session or requests.Session()
        self.timeout = timeout

    def complete(self, endpoint, credential, model_id, messages, tools):
        url, headers, body = self._request(
            endpoint, credential, model_id, messages, tools
        )
        response = self.session.post(
            url,
            headers=headers,
            json=body,
            timeout=self.timeout,
            allow_redirects=False,
        )
        if 300 <= response.status_code < 400:
            raise APIWorkerError("AI Worker redirects are not followed")
        if response.status_code >= 400:
            detail = self._error_detail(response)
            suffix = f": {detail}" if detail else ""
            raise APIWorkerError(
                f"AI Worker request failed: HTTP {response.status_code}{suffix}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise APIWorkerError("AI Worker returned invalid JSON") from exc
        return self._parse(endpoint.provider, payload, response.headers)

    @staticmethod
    def _error_detail(response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return ""
        value = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(value, dict):
            value = value.get("message") or value.get("detail")
        return str(value)[:500] if value else ""

    @staticmethod
    def _request(endpoint, credential, model_id, messages, tools):
        base = endpoint.base_url.rstrip("/")
        if endpoint.provider in {"openai", "openai_compatible"}:
            url = base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions")
            return url, {"Authorization": f"Bearer {credential}"}, {
                "model": model_id,
                "messages": HttpAgentAdapter._openai_messages(messages),
                "tools": [{"type": "function", "function": tool} for tool in tools],
            }
        if endpoint.provider == "anthropic":
            system = "\n".join(m["content"] for m in messages if m["role"] == "system")
            content = HttpAgentAdapter._anthropic_messages(messages)
            return base + "/v1/messages", {
                "x-api-key": credential or "",
                "anthropic-version": "2023-06-01",
            }, {
                "model": model_id,
                "max_tokens": 4096,
                "system": system,
                "messages": content,
                "tools": [
                    {"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
                    for t in tools
                ],
            }
        if endpoint.provider == "google":
            from urllib.parse import quote

            url = base + f"/v1beta/models/{quote(model_id, safe='')}:generateContent?key={quote(credential or '')}"
            contents = HttpAgentAdapter._google_messages(messages)
            return url, {}, {
                "contents": contents,
                "tools": [{"functionDeclarations": tools}],
            }
        return base + "/api/chat", {}, {
            "model": model_id,
            "messages": HttpAgentAdapter._ollama_messages(messages),
            "tools": [{"type": "function", "function": tool} for tool in tools],
            "stream": False,
        }

    @staticmethod
    def _openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for message in messages:
            value = {"role": message["role"], "content": message.get("content", "")}
            if message.get("tool_call_id"):
                value["tool_call_id"] = message["tool_call_id"]
                if message.get("name"):
                    value["name"] = message["name"]
            if message.get("tool_calls"):
                value["tool_calls"] = [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(call["arguments"]),
                        },
                    }
                    for call in message["tool_calls"]
                ]
            result.append(value)
        return result

    @staticmethod
    def _anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for message in messages:
            if message["role"] == "system":
                continue
            role = "assistant" if message["role"] == "assistant" else "user"
            blocks: list[dict[str, Any]] = []
            if message.get("content"):
                blocks.append({"type": "text", "text": str(message["content"])})
            for call in message.get("tool_calls", []):
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call["id"],
                        "name": call["name"],
                        "input": call["arguments"],
                    }
                )
            if message["role"] == "tool":
                blocks = [
                    {
                        "type": "tool_result",
                        "tool_use_id": message["tool_call_id"],
                        "content": str(message.get("content", "")),
                    }
                ]
            if result and result[-1]["role"] == role:
                result[-1]["content"].extend(blocks)
            else:
                result.append({"role": role, "content": blocks})
        return result

    @staticmethod
    def _ollama_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for message in messages:
            value: dict[str, Any] = {
                "role": message["role"],
                "content": message.get("content", ""),
            }
            if message.get("tool_calls"):
                value["tool_calls"] = [
                    {
                        "function": {
                            "name": call["name"],
                            "arguments": call["arguments"],
                        }
                    }
                    for call in message["tool_calls"]
                ]
            result.append(value)
        return result

    @staticmethod
    def _google_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for message in messages:
            role = "model" if message["role"] == "assistant" else "user"
            parts: list[dict[str, Any]] = []
            if message.get("content"):
                parts.append({"text": str(message["content"])})
            for call in message.get("tool_calls", []):
                parts.append(
                    {
                        "functionCall": {
                            "name": call["name"],
                            "args": call["arguments"],
                        }
                    }
                )
            if message["role"] == "tool":
                parts = [
                    {
                        "functionResponse": {
                            "name": message["name"],
                            "response": {"result": message.get("content", "")},
                        }
                    }
                ]
            result.append({"role": role, "parts": parts})
        return result

    @staticmethod
    def _parse(provider: str, payload: dict, headers: Any) -> AgentResponse:
        calls: list[AgentToolCall] = []
        text = ""
        usage = payload.get("usage", {})
        if provider in {"openai", "openai_compatible"}:
            message = payload["choices"][0]["message"]
            text = message.get("content") or ""
            for item in message.get("tool_calls", []):
                function = item["function"]
                calls.append(AgentToolCall(item["id"], function["name"], json.loads(function.get("arguments") or "{}")))
        elif provider == "anthropic":
            for item in payload.get("content", []):
                if item.get("type") == "text":
                    text += item.get("text", "")
                elif item.get("type") == "tool_use":
                    calls.append(AgentToolCall(item["id"], item["name"], item.get("input", {})))
        elif provider == "google":
            parts = payload.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            for index, item in enumerate(parts):
                text += item.get("text", "")
                if "functionCall" in item:
                    call = item["functionCall"]
                    calls.append(AgentToolCall(f"google-{index}", call["name"], call.get("args", {})))
            usage = payload.get("usageMetadata", {})
        else:
            message = payload.get("message", {})
            text = message.get("content", "")
            for index, item in enumerate(message.get("tool_calls", [])):
                function = item.get("function", item)
                calls.append(AgentToolCall(f"ollama-{index}", function["name"], function.get("arguments", {})))
            usage = {
                "prompt_tokens": payload.get("prompt_eval_count", 0),
                "completion_tokens": payload.get("eval_count", 0),
            }
        return AgentResponse(
            text=text,
            tool_calls=calls,
            input_tokens=usage.get("input_tokens", usage.get("prompt_tokens", usage.get("promptTokenCount", 0))),
            cached_input_tokens=usage.get("cache_read_input_tokens", 0),
            output_tokens=usage.get("output_tokens", usage.get("completion_tokens", usage.get("candidatesTokenCount", 0))),
            reasoning_tokens=usage.get("reasoning_tokens", 0),
            request_id=headers.get("request-id") or headers.get("x-request-id"),
        )


TOOLS = [
    {
        "name": "read_file",
        "description": "Read a UTF-8 file in the delegated Workspace.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write a UTF-8 file in an allowed Workspace path.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    {
        "name": "run_command",
        "description": "Run one allowlisted command without a shell.",
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
]


class WorkspaceTools:
    def __init__(self, workspace: Path, scope: DelegationScope):
        self.workspace = workspace.resolve()
        self.scope = scope

    def execute(self, call: AgentToolCall) -> str:
        if call.name == "read_file":
            return self._path(call.arguments["path"], write=False).read_text(encoding="utf-8")
        if call.name == "write_file":
            path = self._path(call.arguments["path"], write=True)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(call.arguments["content"]), encoding="utf-8")
            return f"wrote {path.relative_to(self.workspace)}"
        if call.name == "run_command":
            argv = shlex.split(str(call.arguments["command"]))
            if not argv or not any(
                argv[: len(shlex.split(allowed))] == shlex.split(allowed)
                for allowed in self.scope.allowed_commands
            ):
                raise APIWorkerError("Command is not allowed by delegation policy")
            completed = subprocess.run(
                argv,
                cwd=self.workspace,
                text=True,
                capture_output=True,
                timeout=120,
                check=False,
            )
            output = (completed.stdout + completed.stderr)[-20_000:]
            return json.dumps({"exit_code": completed.returncode, "output": output})
        raise APIWorkerError(f"Unknown Worker tool: {call.name}")

    def _path(self, value: str, *, write: bool) -> Path:
        relative = PurePosixPath(value)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise APIWorkerError(f"Invalid Workspace path: {value}")
        normalized = relative.as_posix().lstrip("./")
        allowed = any(normalized == p or normalized.startswith(f"{p}/") for p in self.scope.allowed_paths)
        denied = any(normalized == p or normalized.startswith(f"{p}/") for p in self.scope.denied_paths)
        if denied or (write and not allowed):
            raise APIWorkerError(f"Path is outside delegated write scope: {value}")
        path = (self.workspace / normalized).resolve()
        if self.workspace not in path.parents and path != self.workspace:
            raise APIWorkerError(f"Workspace path escaped root: {value}")
        current = self.workspace
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise APIWorkerError(f"Symlink paths are not allowed: {value}")
        return path


class APIWorkerHarness:
    def __init__(self, adapter: AgentAdapter | None = None):
        self.adapter = adapter or HttpAgentAdapter()

    def run(
        self,
        *,
        task_id: str,
        session_id: str,
        model: AIModelRecord,
        endpoint: AIEndpointRecord,
        credential: str | None,
        prompt: str,
        workspace: Path,
        scope: DelegationScope,
        budget: WorkerBudgetPolicy,
    ) -> tuple[WorkerUsageRecord, str]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "You are a Canto delegated Worker. Use only the supplied tools and bounded Workspace."},
            {"role": "user", "content": prompt},
        ]
        tools = WorkspaceTools(workspace, scope)
        usage = WorkerUsageRecord(
            usage_id=f"usage_{uuid4().hex}",
            task_id=task_id,
            session_id=session_id,
            model_key=model.model_key,
            endpoint_id=endpoint.endpoint_id,
            provider_model_id=model.provider_model_id,
            resolved_version=model.resolved_version,
        )
        summaries: list[str] = []
        started = time.monotonic()
        max_turns = budget.max_turns or 30
        max_tools = budget.max_tool_calls or 100
        for _ in range(max_turns):
            if budget.max_wall_seconds and time.monotonic() - started > budget.max_wall_seconds:
                raise APIWorkerError("Worker wall-time budget exceeded", usage)
            try:
                response = self.adapter.complete(endpoint, credential, model.provider_model_id, messages, TOOLS)
            except Exception as exc:
                raise APIWorkerError(str(exc), usage) from exc
            usage.input_tokens += response.input_tokens
            usage.cached_input_tokens += response.cached_input_tokens
            usage.output_tokens += response.output_tokens
            usage.reasoning_tokens += response.reasoning_tokens
            usage.turns += 1
            if response.request_id:
                usage.provider_request_ids.append(response.request_id)
            if budget.enabled:
                if budget.max_input_tokens and usage.input_tokens > budget.max_input_tokens:
                    raise APIWorkerError("Worker input-token budget exceeded", usage)
                if budget.max_output_tokens and usage.output_tokens > budget.max_output_tokens:
                    raise APIWorkerError("Worker output-token budget exceeded", usage)
            if response.text:
                summaries.append(response.text)
            if not response.tool_calls:
                usage.terminal_reason = "worker_completed"
                usage.ended_at = utc_now()
                return usage, "\n".join(summaries).strip()
            messages.append({
                "role": "assistant",
                "content": response.text,
                "tool_calls": [
                    {"id": c.call_id, "name": c.name, "arguments": c.arguments}
                    for c in response.tool_calls
                ],
            })
            for call in response.tool_calls:
                usage.tool_calls += 1
                usage.tool_names.append(call.name)
                if usage.tool_calls > max_tools:
                    raise APIWorkerError("Worker tool-call budget exceeded", usage)
                try:
                    result = tools.execute(call)
                except Exception as exc:
                    raise APIWorkerError(str(exc), usage) from exc
                messages.append({"role": "tool", "tool_call_id": call.call_id, "name": call.name, "content": result})
        raise APIWorkerError("Worker turn budget exceeded", usage)
