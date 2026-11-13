from time import perf_counter
from uuid import UUID

import httpx
from pydantic import SecretStr, TypeAdapter, ValidationError

from app.contracts.accounting import AccountingState
from app.contracts.auth import CurrentUser
from app.contracts.client_decision import ClientQuotationDecision
from app.contracts.documents import Document, ProjectDocuments
from app.contracts.management import ManagementOverview, ManagementTask
from app.contracts.notifications import ProjectNotification
from app.contracts.operations import (
    DepositVerifications,
    Engineering,
    IncrementalOpeningRecords,
    Measurements,
    OpeningFilings,
    OpeningRecords,
)
from app.contracts.portfolio import ManagementQuotationPortfolio
from app.contracts.projects import Project, ProjectTask
from app.contracts.quotation_rounds import QuotationRounds
from app.contracts.quotations import ConfirmedBudgetQuotation, ConfirmedCommercialQuotation
from app.contracts.surfaces import ManagementSurfaces
from app.core.errors import (
    AuthenticationRequired,
    BackendResponseError,
    BackendTimeout,
    BackendUnavailable,
    IntelligenceError,
    InvalidArguments,
    ManagementRequired,
    ResourceNotFound,
)
from app.core.latency import BackendOperation, backend_timing
from app.documents.download import DownloadedDocument
from app.documents.errors import DocumentTooLarge, DocumentUnavailable


def validate_project_id(project_id: UUID | str) -> UUID:
    if isinstance(project_id, UUID):
        return project_id
    if isinstance(project_id, str):
        try:
            return UUID(project_id)
        except ValueError:
            pass
    raise InvalidArguments()


class SnGControlClient:
    """Request-scoped credential holder over a lifespan-scoped connection pool.

    Never register this object globally or pass it to a model. Dispose in a finally block.
    """

    def __init__(self, http: httpx.AsyncClient, token: SecretStr, request_id: UUID) -> None:
        self._http = http
        self._token: SecretStr | None = token
        self._request_id = request_id

    def clear_credentials(self) -> None:
        self._token = None

    async def _get[T](self, path: str, adapter: TypeAdapter[T], operation: BackendOperation) -> T:
        start = perf_counter()
        status = "cancelled"
        try:
            result = await self._read(path, adapter)
            status = "success"
            return result
        except IntelligenceError as exc:
            status = exc.code
            raise
        except Exception:
            status = "failure"
            raise
        finally:
            backend_timing(operation, (perf_counter() - start) * 1000, status)

    async def _read[T](self, path: str, adapter: TypeAdapter[T]) -> T:
        if self._token is None:
            raise AuthenticationRequired()
        request = self._http.build_request(
            "GET",
            path,
            headers={
                "Authorization": f"Bearer {self._token.get_secret_value()}",
                "X-Request-ID": str(self._request_id),
                "Accept": "application/json",
                **({"X-SnG-Active-Role": "Management"} if path != "/api/auth/me" else {}),
            },
        )
        error: IntelligenceError | None = None
        response: httpx.Response | None = None
        try:
            response = await self._http.send(request, follow_redirects=False)
        except httpx.TimeoutException:
            error = BackendTimeout()
        except httpx.RequestError:
            error = BackendUnavailable()
        finally:
            # Do not leave credentials in response.request or exception request objects.
            request.headers.pop("Authorization", None)
        if error is not None:
            # Raise outside except so no httpx exception/context can carry credentials.
            raise error
        assert response is not None
        status_errors: dict[int, type[IntelligenceError]] = {
            401: AuthenticationRequired,
            403: ManagementRequired,
            404: ResourceNotFound,
            429: BackendUnavailable,
        }
        if response.status_code in status_errors:
            raise status_errors[response.status_code]()
        if response.status_code != 200:
            raise BackendResponseError()
        try:
            # JSON-mode strict validation accepts JSON UUID/datetime strings, not coercive bools.
            return adapter.validate_json(response.content, strict=True)
        except ValidationError:
            pass
        raise BackendResponseError()

    async def get_management_surfaces(
        self, project_id: UUID | None, skip: int, ascending: bool
    ) -> ManagementSurfaces:
        if type(skip) is not int or not 0 <= skip <= 1_000_000 or type(ascending) is not bool:
            raise InvalidArguments()
        path = f"/api/management/analytics/surfaces?skip={skip}&ascending={str(ascending).lower()}"
        if project_id is not None:
            project_id = validate_project_id(project_id)
            path += f"&projectId={project_id}"
        result = await self._get(path, TypeAdapter(ManagementSurfaces), "management_surfaces")
        if result.skip != skip or (
            project_id is not None and any(row.project_id != project_id for row in result.projects)
        ):
            raise BackendResponseError()
        return result

    async def get_deposit_verifications(
        self, project_id: UUID | str
    ) -> DepositVerifications | None:
        identifier = validate_project_id(project_id)
        try:
            result = await self._get(
                f"/api/projects/{identifier}/deposit-verifications",
                TypeAdapter(DepositVerifications),
                "deposit_verifications",
            )
        except ResourceNotFound:
            return None
        if result.project_id != identifier:
            raise BackendResponseError()
        if result.accounting.project_id != identifier:
            raise BackendResponseError()
        return result

    async def get_project_measurements(self, project_id: UUID | str) -> Measurements | None:
        identifier = validate_project_id(project_id)
        try:
            result = await self._get(
                f"/api/projects/{identifier}/measurements",
                TypeAdapter(Measurements),
                "measurements",
            )
        except ResourceNotFound:
            return None
        if result.project_id != identifier:
            raise BackendResponseError()
        return result

    async def get_project_engineering(self, project_id: UUID | str) -> Engineering | None:
        identifier = validate_project_id(project_id)
        try:
            result = await self._get(
                f"/api/projects/{identifier}/engineering", TypeAdapter(Engineering), "engineering"
            )
        except ResourceNotFound:
            return None
        if result.project_id != identifier:
            raise BackendResponseError()
        return result

    async def get_project_opening_records(self, project_id: UUID | str) -> OpeningRecords | None:
        identifier = validate_project_id(project_id)
        try:
            result = await self._get(
                f"/api/projects/{identifier}/opening-records",
                TypeAdapter(OpeningRecords),
                "opening_records",
            )
        except ResourceNotFound:
            return None
        if result.project_id != identifier:
            raise BackendResponseError()
        return result

    async def get_project_incremental_opening_records(
        self, project_id: UUID | str
    ) -> IncrementalOpeningRecords | None:
        identifier = validate_project_id(project_id)
        try:
            result = await self._get(
                f"/api/projects/{identifier}/incremental-opening-records",
                TypeAdapter(IncrementalOpeningRecords),
                "incremental_opening_records",
            )
        except ResourceNotFound:
            return None
        if result.project_id != identifier:
            raise BackendResponseError()
        return result

    async def get_project_opening_filings(self, project_id: UUID | str) -> OpeningFilings | None:
        identifier = validate_project_id(project_id)
        try:
            result = await self._get(
                f"/api/projects/{identifier}/opening-filings",
                TypeAdapter(OpeningFilings),
                "opening_filings",
            )
        except ResourceNotFound:
            return None
        return result

    async def get_current_user(self) -> CurrentUser:
        return await self._get("/api/auth/me", TypeAdapter(CurrentUser), "auth_me")

    async def get_management_quotation_portfolio(self) -> ManagementQuotationPortfolio:
        return await self._get(
            "/api/management/quotation-portfolio",
            TypeAdapter(ManagementQuotationPortfolio),
            "quotation_portfolio",
        )

    async def get_management_overview(self) -> ManagementOverview:
        return await self._get(
            "/api/management/overview", TypeAdapter(ManagementOverview), "management_overview"
        )

    async def list_management_tasks(self) -> list[ManagementTask]:
        return await self._get(
            "/api/management/tasks", TypeAdapter(list[ManagementTask]), "management_tasks"
        )

    async def get_project(self, project_id: UUID | str) -> Project:
        identifier = validate_project_id(project_id)
        return await self._get(
            f"/api/projects/{identifier}", TypeAdapter(Project), "project_details"
        )

    async def list_projects(self) -> list[Project]:
        return await self._get("/api/projects", TypeAdapter(list[Project]), "projects_list")

    async def list_project_tasks(self, project_id: UUID | str) -> list[ProjectTask]:
        identifier = validate_project_id(project_id)
        return await self._get(
            f"/api/projects/{identifier}/tasks", TypeAdapter(list[ProjectTask]), "project_tasks"
        )

    async def list_project_documents(self, project_id: UUID | str) -> ProjectDocuments:
        identifier = validate_project_id(project_id)
        return await self._get(
            f"/api/projects/{identifier}/documents", TypeAdapter(ProjectDocuments), "documents"
        )

    async def list_project_notifications(self, project_id: UUID | str) -> list[ProjectNotification]:
        identifier = validate_project_id(project_id)
        return await self._get(
            f"/api/projects/{identifier}/notifications",
            TypeAdapter(list[ProjectNotification]),
            "notifications",
        )

    async def get_initial_deposit(self, project_id: UUID | str) -> AccountingState:
        identifier = validate_project_id(project_id)
        result = await self._get(
            f"/api/projects/{identifier}/initial-deposit",
            TypeAdapter(AccountingState),
            "initial_deposit",
        )
        if result.project_id != identifier:
            raise BackendResponseError()
        return result

    async def get_quotation_rounds(self, project_id: UUID | str) -> QuotationRounds:
        identifier = validate_project_id(project_id)
        result = await self._get(
            f"/api/projects/{identifier}/quotation-rounds",
            TypeAdapter(QuotationRounds),
            "quotation_rounds",
        )
        if result.project_id != identifier:
            raise BackendResponseError()
        return result

    async def get_client_quotation_decision(
        self, project_id: UUID | str
    ) -> ClientQuotationDecision:
        identifier = validate_project_id(project_id)
        result = await self._get(
            f"/api/projects/{identifier}/client-quotation-decision",
            TypeAdapter(ClientQuotationDecision),
            "client_quotation_decision",
        )
        if result.project_id != identifier:
            raise BackendResponseError()
        return result

    async def get_budget_quotation(self, project_id: UUID | str) -> ConfirmedBudgetQuotation | None:
        identifier = validate_project_id(project_id)
        try:
            result = await self._get(
                f"/api/projects/{identifier}/budget-quotation/view",
                TypeAdapter(ConfirmedBudgetQuotation),
                "budget_quotation",
            )
        except ResourceNotFound:
            return None
        if result.project_id != identifier:
            raise BackendResponseError()
        return result

    async def get_commercial_quotation(
        self, project_id: UUID | str
    ) -> ConfirmedCommercialQuotation | None:
        identifier = validate_project_id(project_id)
        try:
            result = await self._get(
                f"/api/projects/{identifier}/commercial-quotation/view",
                TypeAdapter(ConfirmedCommercialQuotation),
                "commercial_quotation",
            )
        except ResourceNotFound:
            return None
        if result.project_id != identifier:
            raise BackendResponseError()
        return result

    async def download_project_document(
        self,
        project_id: UUID | str,
        document_id: UUID | str,
        *,
        metadata: Document,
        max_bytes: int,
    ) -> DownloadedDocument:
        """Closed streaming read. Metadata comes from an authenticated official listing."""
        from email.message import Message

        project, document = validate_project_id(project_id), validate_project_id(document_id)
        if document != metadata.id or max_bytes <= 0 or max_bytes > 49_000_000:
            raise InvalidArguments()
        if metadata.size_bytes < 0 or metadata.size_bytes > max_bytes:
            raise DocumentTooLarge()
        if self._token is None:
            raise AuthenticationRequired()
        request = self._http.build_request(
            "GET",
            f"/api/projects/{project}/documents/{document}/file",
            headers={
                "Authorization": f"Bearer {self._token.get_secret_value()}",
                "X-Request-ID": str(self._request_id),
                "Accept": "application/octet-stream",
                "Accept-Encoding": "identity",
                "X-SnG-Active-Role": "Management",
            },
        )
        response: httpx.Response | None = None
        buffer = bytearray()
        error: IntelligenceError | None = None
        try:
            response = await self._http.send(request, stream=True, follow_redirects=False)
            statuses: dict[int, type[IntelligenceError]] = {
                401: AuthenticationRequired,
                403: ManagementRequired,
                404: DocumentUnavailable,
                410: DocumentUnavailable,
                429: BackendUnavailable,
            }
            if response.status_code in statuses:
                raise statuses[response.status_code]()
            if response.status_code != 200:
                raise BackendResponseError()
            if response.headers.get("content-encoding", "identity") != "identity":
                raise BackendResponseError()
            length = response.headers.get("content-length")
            if length is not None:
                if not length.isdecimal() or len(length) > 20:
                    raise BackendResponseError()
                if int(length) > max_bytes:
                    raise DocumentTooLarge()
                if int(length) != metadata.size_bytes:
                    raise DocumentUnavailable()
            disposition = response.headers.get("content-disposition")
            if disposition:
                header = Message()
                header["content-disposition"] = disposition
                if header.get_filename() != metadata.original_file_name:
                    raise DocumentUnavailable()
            async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                if len(buffer) + len(chunk) > max_bytes:
                    raise DocumentTooLarge()
                buffer.extend(chunk)
            if len(buffer) != metadata.size_bytes:
                raise DocumentUnavailable()
            return DownloadedDocument(
                project,
                document,
                metadata.original_file_name,
                metadata.content_type or "application/octet-stream",
                bytes(buffer),
            )
        except httpx.TimeoutException:
            error = BackendTimeout()
        except httpx.RequestError:
            error = BackendUnavailable()
        finally:
            request.headers.pop("Authorization", None)
            buffer.clear()
            if response is not None:
                await response.aclose()
        assert error is not None
        raise error
