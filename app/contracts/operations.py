"""Read projections: retain operational evidence, omit identities and write capabilities."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import Field

from app.contracts.accounting import AccountingState
from app.contracts.base import BackendContract

Number = Annotated[Decimal, Field(allow_inf_nan=False)]


class OperationalDocument(BackendContract):
    id: UUID
    original_file_name: str
    content_type: str | None
    size_bytes: int
    uploaded_at: datetime
    is_current: bool
    replaced_at: datetime | None
    replaced_by_document_id: UUID | None


class VerificationReview(BackendContract):
    id: UUID
    status: str
    submitted_at: datetime
    decided_at: datetime | None
    note: str | None
    document_ids: list[UUID]


class DepositVerifications(BackendContract):
    project_id: UUID
    available: bool
    accounting: AccountingState
    documents: list[OperationalDocument]
    reviews: list[VerificationReview]


class MeasurementSummary(BackendContract):
    initial: int
    added: int
    retired: int
    active: int
    measured: int
    pending: int
    progress: Number


class Structure(BackendContract):
    id: UUID
    item_id: UUID | None
    unit_ordinal: int
    unit_count: int
    item_number: str | None
    description: str
    location: str | None
    width: Number
    height: Number
    note: str | None
    created_at: datetime
    measured_at: datetime | None
    retired_at: datetime | None
    actual_width: Number | None = None
    actual_height: Number | None = None
    actual_system_text: str | None = None
    image_catalog_item_id: UUID | None = None
    sketch_version_id: UUID | None = None
    technical_complete: bool = False
    measurement_type: str | None = None
    actual_location: str | None = None
    installation_observations: str | None = None
    comparison_status: str = "PendingReview"
    comparison_current: bool = False
    width_difference_mm: Number | None = None
    height_difference_mm: Number | None = None
    modification_complete: bool = False


class DeliveryDocument(BackendContract):
    document_id: UUID
    file_name: str | None
    structure_ids: list[UUID]
    associated_at: datetime | None


class MeasurementDelivery(BackendContract):
    id: UUID
    number: int
    submitted_at: datetime
    evidence_status: str
    scope_issue: str | None
    report_availability: str
    structure_ids: list[UUID]
    documents: list[DeliveryDocument]


class MeasurementSnapshot(BackendContract):
    commercial_quotation_id: UUID
    quotation_round: int
    summary: MeasurementSummary
    structures: list[Structure]
    document_ids: list[UUID]


class Measurements(BackendContract):
    project_id: UUID
    task_id: UUID
    task_status: str
    checklist_id: UUID | None
    revision: int
    summary: MeasurementSummary
    structures: list[Structure]
    documents: list[OperationalDocument]
    submission_id: UUID | None
    submitted_at: datetime | None
    snapshot: MeasurementSnapshot | None
    is_incremental: bool = False
    deliveries: list[MeasurementDelivery] | None = None


class EngineeringReference(BackendContract):
    structure_id: UUID
    submission_id: UUID
    evidence_version: int


class EngineeringDocument(BackendContract):
    document: OperationalDocument
    version: int


class EngineeringOrigin(BackendContract):
    submission_id: UUID
    number: int
    evidence_version: int


class EngineeringWork(BackendContract):
    package_id: UUID
    opening_record_id: UUID | None


class EngineeringRow(BackendContract):
    structure: Structure
    revision: int
    completed: bool
    changed_at: datetime | None
    origin: EngineeringOrigin | None = None
    work: EngineeringWork | None = None


class EngineeringPackage(BackendContract):
    id: UUID
    is_intake: bool
    status: str
    revision: int
    created_at: datetime
    assigned_at: datetime
    completed_at: datetime | None
    structures: list[EngineeringReference]


class EngineeringScopedDocument(BackendContract):
    file: EngineeringDocument
    structures: list[EngineeringReference]
    matches_manifest: bool


class EngineeringActa(BackendContract):
    id: UUID
    number: int
    status: str
    created_at: datetime
    revision: int
    structures: list[EngineeringReference]
    current_document_id: UUID | None
    documents: list[EngineeringScopedDocument]
    confirmed_at: datetime | None


class EngineeringWorkspace(BackendContract):
    project_name: str
    sg_code: str | None
    revision: int
    packages: list[EngineeringPackage]
    actas: list[EngineeringActa]


class Engineering(BackendContract):
    project_id: UUID
    checklist_id: UUID | None
    submission_id: UUID | None
    task_id: UUID
    task_status: str
    started_at: datetime
    completed_at: datetime | None
    revision: int
    total: int
    completed: int
    pending: int
    progress: Number
    structures: list[EngineeringRow]
    documents: list[EngineeringDocument]
    current_document_id: UUID | None
    is_incremental: bool | None = None
    deliveries: list[MeasurementDelivery] | None = None
    workspace: EngineeringWorkspace | None = None


class OpeningRow(BackendContract):
    structure: Structure
    submission_id: UUID
    submission_number: int
    source_evidence_version: int
    evidence_version: int
    evidence_document_id: UUID
    approval: str
    acceptance_id: UUID | None
    revision: int


class OpeningRound(BackendContract):
    id: UUID
    number: int
    status: str
    revision: int
    task_id: UUID
    document_id: UUID
    received_at: datetime
    presented_at: datetime | None
    first_response_at: datetime | None
    resolved_at: datetime | None
    superseded_at: datetime | None
    elapsed_seconds: Number | None
    first_response_seconds: Number | None
    resolution_seconds: Number | None
    structures: list[OpeningRow]


class OpeningDocumentRow(BackendContract):
    structure_id: UUID
    evidence_version: int
    evidence_document_id: UUID


class OpeningDocument(BackendContract):
    round_id: UUID | None
    review_id: UUID | None
    kind: str
    version: int
    document: OperationalDocument
    structures: list[OpeningDocumentRow]


class OpeningAcceptance(BackendContract):
    id: UUID
    round_id: UUID
    signed_document_id: UUID
    presented_document_id: UUID
    task_id: UUID
    at: datetime
    attested: bool
    structures: list[OpeningDocumentRow]


class OpeningReviewRow(BackendContract):
    structure_id: UUID
    evidence_version: int
    requested: bool
    changed: bool
    completed: bool
    revision: int
    changed_at: datetime | None


class OpeningReview(BackendContract):
    id: UUID
    round_id: UUID
    task_id: UUID
    created_at: datetime
    completed_at: datetime | None
    revision: int
    declared: bool
    document_id: UUID | None
    structures: list[OpeningReviewRow]


class OpeningActa(BackendContract):
    id: UUID
    number: int
    confirmed_at: datetime
    last_activity_at: datetime
    rounds: list[OpeningRound]
    reviews: list[OpeningReview]
    documents: list[OpeningDocument]
    acceptances: list[OpeningAcceptance]


class IncrementalOpeningRecords(BackendContract):
    project_id: UUID
    server_now: datetime
    actas: list[OpeningActa]


class FilingOp(BackendContract):
    structure_id: UUID
    code: str
    confirmed: bool


class FilingDocument(BackendContract):
    document_id: UUID
    category: str
    version: int
    state: str
    name: str
    size_bytes: int
    uploaded_at: datetime
    content_type: str | None


class FilingVersion(BackendContract):
    id: UUID
    number: int
    reason: str | None
    created_at: datetime
    confirmed_at: datetime | None
    members: list[FilingOp]
    documents: list[FilingDocument]


class FilingSource(EngineeringReference):
    source: Structure


class OpeningFiling(BackendContract):
    id: UUID
    task_id: UUID | None
    acceptance_id: UUID
    opening_record_id: UUID
    acta_number: int
    presented_document_id: UUID
    signed_document_id: UUID
    accepted_at: datetime
    status: str
    number: str | None
    revision: int
    blocked_reason: str | None
    structures: list[FilingSource]
    versions: list[FilingVersion]


class OpeningFilings(BackendContract):
    project_name: str
    sg_code: str | None
    filings: list[OpeningFiling]


class LegacyOpeningRow(BackendContract):
    structure_id: UUID
    approval: str
    approval_document_id: UUID | None
    carried_approval: bool
    change_description: str | None
    affected: bool
    review_completed: bool
    revision: int


class LegacyOpeningRound(BackendContract):
    id: UUID
    number: int
    status: str
    revision: int
    presentation_task_id: UUID
    review_task_id: UUID | None
    filing_task_id: UUID | None
    presented_document_id: UUID
    revised_document_id: UUID | None
    signed_document_id: UUID | None
    received_at: datetime
    presented_at: datetime | None
    responded_at: datetime | None
    response_seconds: Number | None
    general_observations: str | None
    affected_declared: bool
    structures: list[LegacyOpeningRow]


class LegacyOpeningDocument(BackendContract):
    round_id: UUID
    kind: str
    version: int
    document: OperationalDocument
    affected_structure_ids: list[UUID]


class OpeningRecords(BackendContract):
    project_id: UUID
    submission_id: UUID
    server_now: datetime
    structures: list[Structure]
    rounds: list[LegacyOpeningRound]
    documents: list[LegacyOpeningDocument]
