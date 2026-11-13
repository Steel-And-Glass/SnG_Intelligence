"""Synthetic fixtures shaped from Control DTOs; no provider or operational database."""

import copy
import json
from uuid import UUID, uuid4

import httpx
import pytest
from conftest import DATE, PROJECT_ID, TASK_ID, TOKEN
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from test_accounting import deposit  # noqa: F401
from test_agent import FakeModel, call, final, run_agent
from test_quotations import quotations  # noqa: F401

from app.agent.errors import InvalidToolCall, ToolResultTooLarge
from app.clients.sng_control import SnGControlClient
from app.clients.transport import create_http_client
from app.contracts.operations import (
    Engineering,
    IncrementalOpeningRecords,
    Measurements,
    OpeningFilings,
    OpeningRecords,
)
from app.contracts.quotations import ConfirmedBudgetQuotation
from app.contracts.surfaces import ManagementSurfaces
from app.core.errors import (
    AuthenticationRequired,
    BackendResponseError,
    ManagementRequired,
    OutboundPolicyError,
)
from app.main import create_app

SURFACES = "/api/management/analytics/surfaces"
SECOND = str(UUID(int=919))
THIRD = str(UUID(int=920))


@pytest.fixture
def surfaces(payloads):
    coverage = dict(
        value="362.22000000000000000001",
        unit="m2",
        eligible=2,
        excluded=1,
        source="current Commercial items",
        definition="Area includes quantity",
        exclusions={"InvalidSquareMeters": 1},
    )
    row = dict(
        projectId=PROJECT_ID,
        clientId=THIRD,
        projectName="Casa Uno",
        clientName="Cliente",
        sgCode="SG0012",
        city="Bogotá",
        productLine="Windows",
        quotedSquareMeters="300.22",
        quotedItems=1,
        referenceSquareMeters=None,
        measuredStructures=0,
        pendingStructures=2,
    )
    value = dict(
        generatedAt="2026-11-13T13:47:00.123456-05:00",
        totalProjects=51,
        skip=0,
        pageSize=50,
        hasMore=True,
        quoted=coverage,
        measured={
            **coverage,
            "value": "100.00",
            "source": "active physical structures",
            "exclusions": {"MissingOrInvalidDimensions": 1},
        },
        filed={
            **coverage,
            "value": None,
            "eligible": 0,
            "exclusions": {"FrozenVersionSelectionNotDefined": 1},
        },
        projects=[
            row,
            {
                **row,
                "projectId": SECOND,
                "projectName": "Casa Dos",
                "quotedSquareMeters": "62.00000000000000000001",
            },
        ],
    )
    payloads[SURFACES] = value
    return value


@pytest.fixture
def integration_backend(payloads):
    observations = []

    def handler(request):
        observations.append((request.url.path, dict(request.url.params)))
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert "cookie" not in request.headers
        assert request.url.host == "control.test"
        if request.url.path != "/api/auth/me":
            assert request.headers["X-SnG-Active-Role"] == "Management"
        value = payloads.get(request.url.path, 404)
        return httpx.Response(value) if isinstance(value, int) else httpx.Response(200, json=value)

    return httpx.MockTransport(handler), observations


@pytest.mark.anyio
async def test_surface_totals_precision_coverage_order_and_spoken_unit(
    surfaces, integration_backend
):
    model = FakeModel(
        call("get_management_surfaces", dict(project_id=None, skip=0, ascending=False)),
        final(
            "362,22000000000000000001 m² cotizados.", [f"project:{PROJECT_ID}", f"project:{SECOND}"]
        ),
    )
    result, metrics = await run_agent(model, integration_backend[0])
    envelope = json.loads(model.inputs[-1][0][-1].content)
    assert envelope["data"]["quoted"]["value"] == surfaces["quoted"]["value"]
    assert envelope["data"]["filed"]["value"] is None
    assert envelope["data"]["measured"]["exclusions"] == surfaces["measured"]["exclusions"]
    assert envelope["complete"] is False
    assert "clientId" not in json.dumps(envelope)
    assert [str(r.project_id) for r in result.references] == [PROJECT_ID, SECOND]
    assert "metros cuadrados" in result.spoken_answer and "m²" in result.answer
    assert metrics["tools_used"] == ["get_management_surfaces"]
    assert integration_backend[1] == [
        ("/api/auth/me", {}),
        (SURFACES, {"skip": "0", "ascending": "false"}),
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.pop("quoted"),
        lambda p: p["quoted"].update(unit="mm2"),
        lambda p: p["quoted"].update(value="NaN"),
        lambda p: p.update(totalProjects=True),
        lambda p: p["measured"].update(excluded=-1),
        lambda p: p["projects"][0].pop("projectId"),
    ],
)
def test_surface_contract_rejects_incompatible_payload(surfaces, mutation):
    mutation(surfaces)
    with pytest.raises(ValidationError):
        ManagementSurfaces.model_validate_json(json.dumps(surfaces))


@pytest.mark.anyio
@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", SURFACES),
        ("GET", SURFACES + "?skip=0&ascending=false&url=https://evil.test"),
        ("GET", SURFACES + "?skip=0&skip=1&ascending=false"),
        ("GET", SURFACES + "?skip=-1&ascending=false"),
        ("GET", SURFACES + "?skip=1000001&ascending=false"),
        ("GET", "https://evil.test" + SURFACES),
        ("GET", f"/api/projects/{PROJECT_ID}/engineering?role=OperationsHead"),
        ("GET", "/api/operations/preparations"),
        ("GET", f"/api/projects/{PROJECT_ID}/measurements/{TASK_ID}/file"),
    ],
)
async def test_new_routes_keep_transport_closed(method, path):
    def reject(request):
        pytest.fail("Rejected request reached network")

    async with create_http_client("https://control.test", 1, httpx.MockTransport(reject)) as client:
        with pytest.raises(OutboundPolicyError):
            await client.request(method, path)


@pytest.mark.parametrize("role", ["Engineering", "OperationsHead", "Management,Engineering", ""])
def test_explicit_active_role_must_be_management(settings, mock_backend, role):
    with TestClient(create_app(settings, transport=mock_backend[0])) as api:
        result = api.get(
            "/api/intelligence/session",
            headers={"Authorization": f"Bearer {TOKEN}", "X-SnG-Active-Role": role},
        )
    assert result.status_code == 403
    assert not mock_backend[1]
    assert TOKEN not in result.text


def document():
    return dict(
        id=THIRD,
        originalFileName="evidencia.pdf",
        contentType="application/pdf",
        sizeBytes=100,
        uploadedAt=DATE,
        isCurrent=True,
        replacedAt=None,
        replacedByDocumentId=None,
        uploadedBy={"email": "private@example.test"},
        storageKey="private/storage",
    )


def structure():
    return dict(
        id=TASK_ID,
        itemId=None,
        unitOrdinal=1,
        unitCount=1,
        itemNumber="V1",
        description="Ventana",
        location=None,
        width=2,
        height=1,
        note=None,
        createdAt=DATE,
        measuredAt=DATE,
        retiredAt=None,
        actualWidth=2.1,
        actualHeight=1.05,
        actualSystemText="Sistema",
        technicalComplete=True,
        sketchVersionId=THIRD,
        comparisonStatus="FutureStatus",
    )


@pytest.fixture
def operations(payloads):
    summary = dict(initial=2, added=0, retired=0, active=2, measured=1, pending=1, progress=50)
    delivery = dict(
        id=THIRD,
        number=1,
        submittedAt=DATE,
        submittedBySubject="private-subject",
        evidenceStatus="Frozen",
        scopeIssue=None,
        reportAvailability="Available",
        structureIds=[TASK_ID],
        documents=[
            dict(
                documentId=THIRD,
                fileName="medidas.pdf",
                sha256="private-hash",
                structureIds=[TASK_ID],
                associatedAt=DATE,
                associatedBySubject="private-subject",
            )
        ],
    )
    reference = dict(structureId=TASK_ID, submissionId=THIRD, evidenceVersion=1)
    common = dict(
        projectId=PROJECT_ID,
        taskId=TASK_ID,
        taskStatus="InProgress",
        checklistId=THIRD,
        revision=1,
        responsibleSubject="private-subject",
        canModify=True,
    )
    measurements = dict(
        **common,
        summary=summary,
        structures=[structure()],
        documents=[document()],
        submissionId=None,
        submittedAt=None,
        snapshot=None,
        isIncremental=True,
        deliveries=[delivery],
    )
    engineering = dict(
        **common,
        submissionId=None,
        startedAt=DATE,
        completedAt=None,
        total=2,
        completed=1,
        pending=1,
        progress=50,
        structures=[dict(structure=structure(), revision=1, completed=True, changedAt=DATE)],
        documents=[],
        currentDocumentId=None,
        isIncremental=True,
        deliveries=[delivery],
        workspace=dict(
            projectName="Casa Uno",
            sgCode=None,
            revision=1,
            assignableSubjects=["private-subject"],
            packages=[
                dict(
                    id=THIRD,
                    isIntake=False,
                    status="InProgress",
                    revision=1,
                    createdAt=DATE,
                    assignedAt=DATE,
                    completedAt=None,
                    structures=[reference],
                    responsibleSubject="private-subject",
                )
            ],
            actas=[
                dict(
                    id=THIRD,
                    number=1,
                    status="Confirmed",
                    createdAt=DATE,
                    revision=1,
                    structures=[reference],
                    currentDocumentId=THIRD,
                    documents=[
                        dict(
                            file=dict(document=document(), version=2, sha256="private-hash"),
                            structures=[reference],
                            matchesManifest=True,
                        )
                    ],
                    confirmedAt=DATE,
                )
            ],
        ),
    )
    records = dict(
        projectId=PROJECT_ID,
        serverNow=DATE,
        actas=[
            dict(
                id=THIRD,
                number=1,
                engineerSubject="private-subject",
                confirmedAt=DATE,
                lastActivityAt=DATE,
                rounds=[],
                reviews=[],
                documents=[],
                acceptances=[
                    dict(
                        id=THIRD,
                        roundId=THIRD,
                        signedDocumentId=THIRD,
                        presentedDocumentId=THIRD,
                        taskId=TASK_ID,
                        at=DATE,
                        actorSubject="private-subject",
                        attested=True,
                        structures=[
                            dict(structureId=TASK_ID, evidenceVersion=1, evidenceDocumentId=THIRD)
                        ],
                    )
                ],
            )
        ],
    )
    version = dict(
        id=THIRD,
        number=1,
        reason=None,
        createdAt=DATE,
        confirmedAt=DATE,
        members=[dict(structureId=TASK_ID, code="OP-1", confirmed=True)],
        documents=[
            dict(
                documentId=THIRD,
                category="OP",
                version=1,
                state="Current",
                name="OP.pdf",
                sizeBytes=100,
                uploadedAt=DATE,
                contentType="application/pdf",
                uploadedBySubject="private-subject",
                sha256="private-hash",
            )
        ],
    )
    filings = dict(
        projectName="Casa Uno",
        sgCode=None,
        filings=[
            dict(
                id=THIRD,
                taskId=TASK_ID,
                acceptanceId=THIRD,
                openingRecordId=THIRD,
                actaNumber=1,
                presentedDocumentId=THIRD,
                signedDocumentId=THIRD,
                acceptedAt=DATE,
                responsibleSubject="private-subject",
                status="Confirmed",
                number="RV-1",
                revision=2,
                blockedReason=None,
                structures=[dict(**reference, source=structure())],
                versions=[version, {**version, "id": SECOND, "number": 2, "confirmedAt": None}],
            )
        ],
    )
    legacy = dict(
        projectId=PROJECT_ID,
        submissionId=THIRD,
        serverNow=DATE,
        structures=[structure()],
        rounds=[],
        documents=[],
    )
    values = {
        "measurements": measurements,
        "engineering": engineering,
        "incremental-opening-records": records,
        "opening-filings": filings,
        "opening-records": legacy,
    }
    for route, value in values.items():
        payloads[f"/api/projects/{PROJECT_ID}/{route}"] = value
    return values


OPERATION_TOOLS = [
    ("get_project_measurements", "measurements", Measurements),
    ("get_project_engineering", "engineering", Engineering),
    (
        "get_project_incremental_opening_records",
        "incremental-opening-records",
        IncrementalOpeningRecords,
    ),
    ("get_project_opening_filings", "opening-filings", OpeningFilings),
    ("get_project_opening_records", "opening-records", OpeningRecords),
]


@pytest.mark.anyio
@pytest.mark.parametrize("tool,route,contract", OPERATION_TOOLS)
async def test_scoped_reads_preserve_evidence_without_identity(
    operations, integration_backend, tool, route, contract, caplog
):
    model = FakeModel(
        call("get_project_details", dict(project_id=PROJECT_ID)),
        call(tool, dict(project_id=PROJECT_ID), "operation"),
        final(keys=[f"project:{PROJECT_ID}"]),
    )
    response, _ = await run_agent(model, integration_backend[0])
    envelope = json.loads(model.inputs[-1][0][-1].content)
    assert envelope["data"]["available"] is True
    assert envelope["data"]["data"] == contract.model_validate_json(
        json.dumps(operations[route])
    ).model_dump(mode="json", by_alias=True)
    assert str(response.references[0].project_id) == PROJECT_ID
    for secret in (
        "private-subject",
        "private-hash",
        "private/storage",
        "private@example.test",
        TOKEN,
    ):
        assert secret not in repr(model.inputs) + response.model_dump_json() + caplog.text
    assert integration_backend[1][-1][0] == f"/api/projects/{PROJECT_ID}/{route}"


@pytest.mark.anyio
@pytest.mark.parametrize("tool,route,contract", OPERATION_TOOLS)
async def test_scoped_read_requires_fresh_unambiguous_project(
    integration_backend, tool, route, contract
):
    with pytest.raises(InvalidToolCall):
        await run_agent(FakeModel(call(tool, dict(project_id=PROJECT_ID))), integration_backend[0])
    assert not integration_backend[1]


def test_partial_deliveries_and_versions_remain_distinct(operations):
    measured = Measurements.model_validate_json(json.dumps(operations["measurements"]))
    assert measured.summary.pending == 1 and measured.summary.progress == 50
    assert measured.deliveries[0].structure_ids == [UUID(TASK_ID)]
    filings = OpeningFilings.model_validate_json(json.dumps(operations["opening-filings"]))
    assert [v.confirmed_at is None for v in filings.filings[0].versions] == [False, True]
    assert len(filings.filings[0].structures) == 1
    parsed = IncrementalOpeningRecords.model_validate_json(
        json.dumps(operations["incremental-opening-records"])
    )
    assert parsed.actas[0].acceptances[0].structures[0].evidence_version == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    "status,error",
    [(401, AuthenticationRequired), (403, ManagementRequired), (500, BackendResponseError)],
)
async def test_operational_errors_abort_generation(payloads, integration_backend, status, error):
    payloads[f"/api/projects/{PROJECT_ID}/measurements"] = status
    model = FakeModel(
        call("get_project_details", dict(project_id=PROJECT_ID)),
        call("get_project_measurements", dict(project_id=PROJECT_ID), "operation"),
    )
    with pytest.raises(error):
        await run_agent(model, integration_backend[0])
    assert len(model.inputs) == 2


@pytest.mark.anyio
async def test_missing_operational_state_is_unavailable_not_zero(integration_backend):
    model = FakeModel(
        call("get_project_details", dict(project_id=PROJECT_ID)),
        call("get_project_measurements", dict(project_id=PROJECT_ID), "operation"),
        final("No está disponible ese dato.", kind="unavailable"),
    )
    await run_agent(model, integration_backend[0])
    data = json.loads(model.inputs[-1][0][-1].content)["data"]
    assert data["available"] is False and data["data"] is None


@pytest.mark.anyio
async def test_wrong_project_and_oversized_evidence_fail_safely(operations, integration_backend):
    data = operations["measurements"]
    data["projectId"] = SECOND
    async with create_http_client("https://control.test", 7, integration_backend[0]) as http:
        client = SnGControlClient(http, SecretStr(TOKEN), uuid4())
        with pytest.raises(BackendResponseError):
            await client.get_project_measurements(PROJECT_ID)
    data["projectId"] = PROJECT_ID
    data["structures"][0]["description"] = "x" * 50000
    with pytest.raises(ToolResultTooLarge):
        await run_agent(
            FakeModel(
                call("get_project_details", dict(project_id=PROJECT_ID)),
                call("get_project_measurements", dict(project_id=PROJECT_ID), "operation"),
            ),
            integration_backend[0],
        )


def test_budget_economics_current_contract(quotations):  # noqa: F811
    budget = copy.deepcopy(quotations[0])
    budget["economics"] = dict(
        status="Available",
        currencyCode="COP",
        projectTotal="1250000.15",
        projectTotalCell="H10",
        mainItemTotalsDiffer=True,
        items=[dict(section="Main", sourceRow=15, unitPrice="625000.07", totalPrice="1250000.14")],
    )
    parsed = ConfirmedBudgetQuotation.model_validate_json(json.dumps(budget))
    assert str(parsed.economics.project_total) == "1250000.15"
    assert parsed.economics.main_item_totals_differ is True
    budget["economics"]["projectTotal"] = "1250000.151"
    with pytest.raises(ValidationError):
        ConfirmedBudgetQuotation.model_validate_json(json.dumps(budget))


@pytest.mark.anyio
async def test_verification_reviews_keep_decisions_and_money(
    deposit,  # noqa: F811
    payloads,
    integration_backend,
):
    from app.contracts.operations import DepositVerifications

    reviews = [
        dict(
            id=str(UUID(int=10 + i)),
            status=status,
            submittedAt=DATE,
            decidedAt=None if status == "Pending" else DATE,
            note=None,
            documentIds=[THIRD],
            decidedBy={"email": "private@example.test"},
        )
        for i, status in enumerate(("Rejected", "Approved", "Pending"))
    ]
    value = dict(
        projectId=PROJECT_ID,
        available=True,
        accounting=deposit,
        documents=[document()],
        reviews=reviews,
        canManage=True,
    )
    payloads[f"/api/projects/{PROJECT_ID}/deposit-verifications"] = value
    model = FakeModel(
        call("get_project_details", dict(project_id=PROJECT_ID)),
        call("get_deposit_verifications", dict(project_id=PROJECT_ID), "reviews"),
        final("Hay revisiones de comprobantes.", [f"project:{PROJECT_ID}"]),
    )
    await run_agent(model, integration_backend[0])
    data = json.loads(model.inputs[-1][0][-1].content)["data"]["data"]
    assert [r["status"] for r in data["reviews"]] == ["Rejected", "Approved", "Pending"]
    assert data["accounting"]["deposit"]["amount"] == "5000000.01"
    assert "private@example.test" not in repr(model.inputs)
    value["accounting"]["projectId"] = SECOND
    async with create_http_client("https://control.test", 7, integration_backend[0]) as http:
        client = SnGControlClient(http, SecretStr(TOKEN), uuid4())
        with pytest.raises(BackendResponseError):
            await client.get_deposit_verifications(PROJECT_ID)
    value["accounting"]["projectId"] = PROJECT_ID
    value.pop("available")
    with pytest.raises(ValidationError):
        DepositVerifications.model_validate_json(json.dumps(value))


@pytest.mark.anyio
async def test_surface_project_filter_and_page_are_sent_exactly(
    surfaces, payloads, integration_backend
):
    surfaces["projects"] = surfaces["projects"][:1]
    surfaces.update(skip=50, totalProjects=1, hasMore=False)
    model = FakeModel(
        call("get_project_details", dict(project_id=PROJECT_ID)),
        call(
            "get_management_surfaces",
            dict(project_id=PROJECT_ID, skip=50, ascending=True),
            "surface",
        ),
        final(),
    )
    await run_agent(model, integration_backend[0])
    assert integration_backend[1][-1] == (
        SURFACES,
        dict(skip="50", ascending="true", projectId=PROJECT_ID),
    )


@pytest.mark.anyio
async def test_ambiguous_surface_filter_is_rejected(payloads, integration_backend):
    base = payloads[f"/api/projects/{PROJECT_ID}"]
    payloads["/api/projects"] = [
        {**base, "name": "Casa Uno"},
        {**base, "id": SECOND, "name": "Casa Dos"},
    ]
    with pytest.raises(InvalidToolCall):
        await run_agent(
            FakeModel(
                call("find_projects", {"query": "Casa"}),
                call(
                    "get_management_surfaces",
                    dict(project_id=PROJECT_ID, skip=0, ascending=False),
                    "surface",
                ),
            ),
            integration_backend[0],
        )
    assert not any(path == SURFACES for path, _ in integration_backend[1])


@pytest.mark.anyio
async def test_surface_context_followup_reloads_tasks_and_compares_in_order(
    surfaces, payloads, integration_backend
):
    from conversation_repository import MemoryRepository
    from test_decision_support import with_context

    from app.conversation.context import ConversationTurn
    from app.conversation.store import ConversationStore

    project = payloads[f"/api/projects/{PROJECT_ID}"]
    payloads[f"/api/projects/{SECOND}"] = {**project, "id": SECOND, "name": "Casa Dos"}
    payloads[f"/api/projects/{SECOND}/tasks"] = []
    store = ConversationStore(MemoryRepository())
    key = (await store.create("manager")).conversation_id
    first = FakeModel(
        call("get_management_surfaces", dict(project_id=None, skip=0, ascending=False)),
        final("Casa Uno y Casa Dos.", [f"project:{PROJECT_ID}", f"project:{SECOND}"]),
    )
    try:
        async with store.operation(key, "manager") as context:
            answer = await with_context(first, integration_backend[0], context, "Mayor superficie")
            await store.append(
                key, "manager", ConversationTurn.completed("text", "Mayor superficie", answer)
            )
        task = payloads[f"/api/projects/{PROJECT_ID}/tasks"][0]
        task.update(status="InProgress", leadTimeStatus="Overdue", deadlineAt=DATE, wasOverdue=True)
        second = FakeModel(
            call("get_project_details", dict(project_id=PROJECT_ID)),
            call("get_project_details", dict(project_id=SECOND), "second"),
            final("El primero tiene una tarea atrasada.", [f"project:{PROJECT_ID}"]),
        )
        async with store.operation(key, "manager") as context:
            await with_context(
                second, integration_backend[0], context, "¿Cuál de ellos está atrasado?"
            )
        fresh = json.loads(second.inputs[1][0][-1].content)
        assert fresh["data"]["tasks"][0]["leadTimeStatus"] == "Overdue"
        third = FakeModel(
            call("get_project_details", dict(project_id=PROJECT_ID)),
            call("get_project_details", dict(project_id=SECOND), "second"),
            call(
                "compare_projects",
                dict(
                    project_ids=[PROJECT_ID, SECOND],
                    include_documents=False,
                    include_activity=False,
                ),
                "compare",
            ),
            final("Comparación actual.", [f"project:{PROJECT_ID}", f"project:{SECOND}"]),
        )
        async with store.operation(key, "manager") as context:
            result = await with_context(
                third, integration_backend[0], context, "Compara los dos primeros"
            )
        assert [str(r.project_id) for r in result.references] == [PROJECT_ID, SECOND]
        assert integration_backend[1].count((f"/api/projects/{PROJECT_ID}/tasks", {})) == 3
        assert "Casa Uno" in repr(third.inputs[0]) and "Casa Dos" in repr(third.inputs[0])
    finally:
        await store.shutdown()


@pytest.mark.anyio
async def test_live_delegates_surface_tool_without_credentials(surfaces, integration_backend):
    from test_live import SESSION
    from test_sideband import begin, complete, function, setup_live, until

    model = FakeModel(
        call("get_management_surfaces", dict(project_id=None, skip=0, ascending=False)),
        final("La superficie cotizada incluye cantidades.", [f"project:{PROJECT_ID}"]),
    )
    async with setup_live(integration_backend[0], model) as (manager, socket, _, registry, _):
        begin(socket, "response_surface")
        socket.incoming.put_nowait(function("call_surface", "¿Qué superficie cotizamos?"))
        complete(socket, "response_surface")
        await until(lambda: any(e["type"] == "response.create" for e in socket.sent))
        assert registry.owned(SESSION, "manager") and not socket.closed
        assert TOKEN not in repr(socket.sent) + repr(model.inputs)
        assert (SURFACES, {"skip": "0", "ascending": "false"}) in integration_backend[1]


@pytest.mark.anyio
async def test_missing_manufacturing_source_does_not_trigger_substitute_reads(integration_backend):
    model = FakeModel(
        final("No dispongo de evidencia de fabricación ejecutada.", kind="unavailable")
    )
    result, _ = await run_agent(model, integration_backend[0], "¿Cuántos m² hemos fabricado?")
    assert result.response_type == "unavailable" and not result.references
    assert not integration_backend[1]


@pytest.mark.anyio
async def test_current_project_wire_contract_no_longer_requires_created_by(
    payloads, integration_backend
):
    project = payloads[f"/api/projects/{PROJECT_ID}"]
    assert "createdBy" not in project
    project.update(createdByName="Private creator", isCreatedByMe=True)
    model = FakeModel(call("get_project_details", dict(project_id=PROJECT_ID)), final())
    await run_agent(model, integration_backend[0])
    assert "Private creator" not in repr(model.inputs)
    project.pop("isCreatedByMe")
    with pytest.raises(BackendResponseError):
        await run_agent(
            FakeModel(call("get_project_details", dict(project_id=PROJECT_ID))),
            integration_backend[0],
        )


@pytest.mark.parametrize("role,allowed", [("Management", True), ("Engineering", False)])
def test_new_surface_tool_through_chat_http(settings, surfaces, integration_backend, role, allowed):
    from test_chat import chat_app

    model = FakeModel(
        call("get_management_surfaces", dict(project_id=None, skip=0, ascending=False)),
        final("La fuente acredita superficie cotizada.", [f"project:{PROJECT_ID}"]),
    )
    with TestClient(chat_app(settings, integration_backend[0], model)) as api:
        response = api.post(
            "/api/intelligence/chat",
            json={"message": "¿Qué superficie cotizamos?"},
            headers={"Authorization": f"Bearer {TOKEN}", "X-SnG-Active-Role": role},
        )
    assert response.status_code == (200 if allowed else 403)
    assert TOKEN not in response.text
    if allowed:
        assert response.json()["references"][0]["projectId"] == PROJECT_ID
    else:
        assert not model.inputs and not integration_backend[1]


@pytest.mark.anyio
async def test_surface_cannot_ground_unknown_project(surfaces, integration_backend):
    from app.agent.errors import UngroundedReference

    with pytest.raises(UngroundedReference):
        await run_agent(
            FakeModel(
                call("get_management_surfaces", dict(project_id=None, skip=0, ascending=False)),
                final(keys=[f"project:{THIRD}"]),
                final(keys=[f"project:{THIRD}"]),
            ),
            integration_backend[0],
        )


@pytest.mark.parametrize("route,contract", [(r, c) for _, r, c in OPERATION_TOOLS])
def test_required_operational_contract_fields_cannot_disappear(operations, route, contract):
    value = operations[route]
    value.pop("filings" if route == "opening-filings" else "projectId")
    with pytest.raises(ValidationError):
        contract.model_validate_json(json.dumps(value))
