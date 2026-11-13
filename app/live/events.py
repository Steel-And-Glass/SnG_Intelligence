"""Only finalized Responses function items may cross the execution boundary."""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.agent.contracts import ChatRequest, StrictModel
from app.live.contracts import OpaqueId
from app.live.errors import LiveProtocolError

MAX_EVENT_BYTES = 256 * 1024


class WireModel(BaseModel):
    model_config = ConfigDict(strict=True, hide_input_in_errors=True)


class Question(StrictModel):
    question: str = Field(min_length=1, max_length=4000, repr=False)

    @field_validator("question")
    @classmethod
    def non_blank(cls, value: str) -> str:
        return ChatRequest.non_blank(value).strip()


class Delegation(WireModel):
    id: OpaqueId
    target: Literal["responses"]
    response_id: OpaqueId | None = None


class DelegationCreated(WireModel):
    type: Literal["session.delegation.created"]
    delegation: Delegation


class ResponseIdentity(WireModel):
    id: OpaqueId


class ResponseLifecycle(WireModel):
    type: Literal[
        "response.created", "response.completed", "response.failed", "response.incomplete"
    ]
    response: ResponseIdentity


class FunctionCall(WireModel):
    type: Literal["function_call"]
    name: Literal["consult_sng_intelligence"]
    call_id: OpaqueId
    arguments: str = Field(max_length=24000, repr=False)
    status: Literal["completed"] | None = None


class ItemDone(WireModel):
    type: Literal["response.output_item.done"]
    item: FunctionCall


class ResponseEvent(WireModel):
    type: Literal["response.event"]
    delegation_id: OpaqueId
    event: ResponseLifecycle | ItemDone


class Closed(WireModel):
    type: Literal["session.closed"]


class ProviderErrorCode(WireModel):
    code: str = Field(max_length=128, repr=False)
    type: str | None = Field(default=None, max_length=128, repr=False)

    def safe_category(self) -> str:
        # Exact closed vocabulary: arbitrary provider strings never become log fields.
        known = {
            "responses_validation_failed",
            "rate_limit_exceeded",
            "rate_limit_error",
            "tool_outputs_required",
            "function_call_outputs_required",
            "server_error",
            "insufficient_quota",
            "context_length_exceeded",
            "max_output_tokens",
            "invalid_api_key",
            "model_not_found",
            "permission_denied",
            "response_generation_failed",
            "response_timeout",
            "response_cancelled",
            "response_in_progress",
            "response_not_found",
            "invalid_request_error",
            "unknown_parameter",
            "invalid_parameter",
            "invalid_value",
        }
        return self.code if self.code in known else "other_provider_error"

    def safe_type(self) -> str:
        known = {
            "invalid_request_error",
            "server_error",
            "rate_limit_error",
            "authentication_error",
            "permission_error",
            "api_error",
        }
        return self.type if self.type in known else "unknown"


class ProviderError(WireModel):
    type: Literal["error"]
    error: ProviderErrorCode
    # Deliberately project away the provider's raw message and error payload.


Event = DelegationCreated | ResponseEvent | Closed | ProviderError


def parse_event(raw: str | bytes) -> Event | None:
    try:
        if len(raw.encode() if isinstance(raw, str) else raw) > MAX_EVENT_BYTES:
            raise ValueError()
        value = json.loads(raw)
        if not isinstance(value, dict) or not isinstance(value.get("type"), str):
            raise ValueError()
        kind = value["type"]
        if kind == "session.closed":
            return Closed.model_validate(value)
        if kind == "error":
            return ProviderError.model_validate(value)
        if kind == "session.delegation.created":
            return DelegationCreated.model_validate(value)
        if kind == "response.event":
            nested = value.get("event")
            if not isinstance(nested, dict) or not isinstance(nested.get("type"), str):
                raise ValueError()
            if nested["type"] == "response.output_item.done":
                item = nested.get("item")
                if not isinstance(item, dict):
                    raise ValueError()
                if item.get("type") in {"message", "reasoning"}:
                    return None
            elif nested["type"] not in {
                "response.created",
                "response.completed",
                "response.failed",
                "response.incomplete",
            }:
                return None  # Includes arguments delta/done: never an execution trigger.
            return ResponseEvent.model_validate(value)
        return None  # Audio/transcript events are discarded, never accumulated.
    except (ValueError, ValidationError, TypeError, RecursionError):
        pass
    raise LiveProtocolError()
