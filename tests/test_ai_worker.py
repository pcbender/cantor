from __future__ import annotations

import pytest

from canto.core.ai_worker import (
    APIWorkerError,
    APIWorkerHarness,
    AgentResponse,
    AgentToolCall,
    WorkspaceTools,
    HttpAgentAdapter,
)
from canto.models.ai_workers import AIEndpointRecord, AIModelRecord, WorkerBudgetPolicy
from canto.models.delegation import DelegationScope


class Adapter:
    def __init__(self):
        self.turn = 0

    def complete(self, endpoint, credential, model_id, messages, tools):
        self.turn += 1
        if self.turn == 1:
            return AgentResponse(
                tool_calls=[
                    AgentToolCall("1", "write_file", {"path": "src/result.txt", "content": "done\n"}),
                    AgentToolCall("2", "run_command", {"command": "git status --short"}),
                ],
                input_tokens=10,
                output_tokens=5,
                request_id="request-1",
            )
        return AgentResponse(text="Implemented and tested.", input_tokens=2, output_tokens=3)


def model():
    return AIModelRecord(
        model_key="local:coder",
        endpoint_id="local",
        provider="ollama",
        provider_model_id="coder",
        resolved_version="digest",
        classification="implementation",
        probe_stale=False,
        catalog_checksum="checksum",
    )


def test_api_worker_edits_workspace_and_records_usage(tmp_path):
    (tmp_path / "src").mkdir()
    harness = APIWorkerHarness(Adapter())

    usage, summary = harness.run(
        task_id="task-1",
        session_id="session-1",
        model=model(),
        endpoint=AIEndpointRecord(endpoint_id="local", provider="ollama", base_url="http://localhost:11434"),
        credential=None,
        prompt="Do the bounded work",
        workspace=tmp_path,
        scope=DelegationScope(allowed_paths=["src"], allowed_commands=["git status"]),
        budget=WorkerBudgetPolicy(enabled=True, max_turns=3, max_tool_calls=3),
    )

    assert (tmp_path / "src" / "result.txt").read_text() == "done\n"
    assert usage.turns == 2
    assert usage.tool_calls == 2
    assert usage.provider_request_ids == ["request-1"]
    assert summary == "Implemented and tested."


def test_workspace_tools_reject_denied_paths_and_commands(tmp_path):
    tools = WorkspaceTools(
        tmp_path,
        DelegationScope(
            allowed_paths=["src"],
            denied_paths=["src/secrets"],
            allowed_commands=["pytest"],
        ),
    )

    with pytest.raises(APIWorkerError, match="outside delegated"):
        tools.execute(AgentToolCall("1", "write_file", {"path": "src/secrets/key", "content": "x"}))
    with pytest.raises(APIWorkerError, match="Command is not allowed"):
        tools.execute(AgentToolCall("2", "run_command", {"command": "git push"}))


def test_worker_enforces_output_token_budget(tmp_path):
    class Expensive:
        def complete(self, *args, **kwargs):
            return AgentResponse(text="too much", output_tokens=20)

    with pytest.raises(APIWorkerError, match="output-token") as caught:
        APIWorkerHarness(Expensive()).run(
            task_id="t",
            session_id="s",
            model=model(),
            endpoint=AIEndpointRecord(endpoint_id="local", provider="ollama", base_url="http://localhost:11434"),
            credential=None,
            prompt="work",
            workspace=tmp_path,
            scope=DelegationScope(allowed_paths=["src"]),
            budget=WorkerBudgetPolicy(enabled=True, max_output_tokens=10),
        )
    assert caught.value.usage.output_tokens == 20


def test_provider_message_translation_preserves_structured_tool_results():
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "name": "read_file", "arguments": {"path": "src/a"}}]},
        {"role": "tool", "tool_call_id": "1", "name": "read_file", "content": "value"},
    ]

    openai = HttpAgentAdapter._openai_messages(messages)
    anthropic = HttpAgentAdapter._anthropic_messages(messages)
    google = HttpAgentAdapter._google_messages(messages)

    assert openai[0]["tool_calls"][0]["function"]["name"] == "read_file"
    assert anthropic[0]["content"][0]["type"] == "tool_use"
    assert anthropic[1]["content"][0]["type"] == "tool_result"
    assert google[0]["parts"][0]["functionCall"]["name"] == "read_file"
    assert google[1]["parts"][0]["functionResponse"]["name"] == "read_file"
