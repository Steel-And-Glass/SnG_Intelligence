from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.contracts.base import BackendContract

Surface = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
Count = Annotated[int, Field(ge=0)]


class SurfaceCoverage(BackendContract):
    value: Surface | None
    unit: Literal["m2"]
    eligible: Count
    excluded: Count
    source: str
    definition: str
    exclusions: dict[str, Count]


class SurfaceProject(BackendContract):
    project_id: UUID
    project_name: str
    client_name: str
    sg_code: str | None
    city: str
    product_line: str
    quoted_square_meters: Surface | None
    quoted_items: Count
    reference_square_meters: Surface | None
    measured_structures: Count
    pending_structures: Count


class ManagementSurfaces(BackendContract):
    generated_at: datetime
    total_projects: Count
    skip: Count
    page_size: Annotated[int, Field(gt=0)]
    has_more: bool
    quoted: SurfaceCoverage
    measured: SurfaceCoverage
    filed: SurfaceCoverage
    projects: list[SurfaceProject]
