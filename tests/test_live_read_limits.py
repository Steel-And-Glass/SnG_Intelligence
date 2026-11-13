import json
import logging

import pytest
from conftest import PROJECT_ID, TOKEN
from conversation_repository import MemoryRepository
from test_agent import FakeModel, call, final
from test_live import KEY, SESSION
from test_sideband import begin, complete, function, setup_live, until

from app.conversation.store import ConversationStore
from app.live.events import ProviderError, parse_event


@pytest.mark.anyio
async def test_oversized_real_tool_result_recovers_turn_and_next_query_works(
    payloads, mock_backend, caplog
):
    caplog.set_level(logging.INFO, logger="sng_intelligence")
    payloads["/api/management/tasks"] *= 300
    model = FakeModel(
        call("list_management_tasks"), call("get_management_overview"), final("Hay 19 proyectos.")
    )
    store = ConversationStore(MemoryRepository())
    entry = await store.create("manager")
    try:
        async with setup_live(mock_backend[0], model) as (manager, socket, vault, registry, _):
            manager._conversations = store
            await store.bind_live(SESSION, entry.conversation_id, "manager")
            for number in (1, 2):
                response_id = f"response_{number}"
                begin(socket, response_id)
                socket.incoming.put_nowait(function(f"call_{number}"))
                complete(socket, response_id)
                await until(
                    lambda n=number: sum(e["type"] == "response.create" for e in socket.sent) == n
                )
                assert not socket.closed and registry.owned(SESSION, "manager")
                assert vault._get(SESSION).subject == "manager"
            outputs = [
                json.loads(e["item"]["output"])
                for e in socket.sent
                if e["type"] == "response.item.create"
            ]
            assert outputs[0]["responseType"] == "unavailable"
            assert "demasiados datos" in outputs[0]["spokenAnswer"]
            assert outputs[1]["spokenAnswer"] == "Hay 19 proyectos."
            turns = store.repository.turns[entry.conversation_id]
            assert len(turns) == 2 and turns[0].references == "[]"
            assert turns[0].response_type == "unavailable"
            assert len(model.inputs) == 3  # No model sees the oversized result.
            assert "demasiados datos" in repr(model.inputs[1])  # Safe durable semantic turn only.
            logs = [
                json.loads(r.message)
                for r in caplog.records
                if r.name == "sng_intelligence" and r.message.startswith("{")
            ]
            rejected = next(r for r in logs if r.get("operation") == "tool_result_rejected")
            assert rejected["tool"] == "list_management_tasks"
            assert rejected["result_bytes"] > rejected["limit_bytes"] == 48000
            assert any(r.get("live_event") == "turn_recovered" for r in logs)
    finally:
        await store.shutdown()
    for private in (TOKEN, KEY, PROJECT_ID):
        assert private not in caplog.text


@pytest.mark.parametrize(
    "code,kind,category,safe_type",
    [
        (
            "context_length_exceeded",
            "invalid_request_error",
            "context_length_exceeded",
            "invalid_request_error",
        ),
        ("insufficient_quota", "rate_limit_error", "insufficient_quota", "rate_limit_error"),
        ("server_error", "server_error", "server_error", "server_error"),
        ("private-business-name", "private-identity", "other_provider_error", "unknown"),
    ],
)
def test_provider_diagnostics_are_closed_categories(code, kind, category, safe_type):
    event = parse_event(
        json.dumps(
            {
                "type": "error",
                "error": {
                    "code": code,
                    "type": kind,
                    "message": "private-business-text",
                    "param": "private-parameter",
                    "client_event_id": "private-id",
                },
            }
        )
    )
    assert isinstance(event, ProviderError)
    assert event.error.safe_category() == category
    assert event.error.safe_type() == safe_type
    assert "private" not in repr(event)
    assert "message" not in event.error.model_dump()


@pytest.mark.anyio
async def test_provider_failure_still_closes_and_diagnostics_do_not_leak(mock_backend, caplog):
    caplog.set_level(logging.INFO, logger="sng_intelligence")
    async with setup_live(mock_backend[0]) as (manager, socket, vault, registry, _):
        socket.incoming.put_nowait(
            json.dumps(
                {
                    "type": "error",
                    "error": {
                        "code": "context_length_exceeded",
                        "type": "invalid_request_error",
                        "message": "private-business-content",
                        "param": "private-parameter",
                    },
                }
            )
        )
        await until(lambda: not manager._runs)
        assert socket.closed and not registry._entries
    assert "context_length_exceeded" in caplog.text
    assert "invalid_request_error" in caplog.text
    assert "private-business-content" not in caplog.text
    assert "private-parameter" not in caplog.text
