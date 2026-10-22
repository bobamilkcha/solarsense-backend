import uuid
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime

from app.models import (
    ChecklistItem,
    ChecklistItemStatus,
    Project,
    Site,
    SiteVisit,
    User,
    VisitStatus,
)
from app.modules.readings.exceptions import SiteNotFoundError
from app.modules.visits import schemas
from app.modules.visits.exceptions import (
    ChecklistItemNotFoundError,
    PendingItemsError,
    VisitCompletedError,
    VisitNotFoundError,
)
from app.modules.visits.template import default_items
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _progress(visit: SiteVisit) -> schemas.ChecklistProgress:
    counts = Counter(item.status for item in visit.items)
    return schemas.ChecklistProgress(
        total=len(visit.items),
        pending=counts[ChecklistItemStatus.PENDING],
        ok=counts[ChecklistItemStatus.OK],
        issue=counts[ChecklistItemStatus.ISSUE],
        not_applicable=counts[ChecklistItemStatus.NOT_APPLICABLE],
    )


def to_summary(visit: SiteVisit) -> schemas.VisitSummaryResponse:
    return schemas.VisitSummaryResponse(
        id=visit.id,
        site_id=visit.site_id,
        visited_by_id=visit.visited_by_id,
        visited_at=visit.visited_at,
        status=visit.status,
        notes=visit.notes,
        completed_at=visit.completed_at,
        created_at=visit.created_at,
        progress=_progress(visit),
    )


def to_response(visit: SiteVisit) -> schemas.VisitResponse:
    return schemas.VisitResponse(
        **to_summary(visit).model_dump(),
        items=[schemas.ChecklistItemResponse.model_validate(i) for i in visit.items],
    )


class VisitsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_visit(
        self,
        site_id: uuid.UUID,
        company_id: uuid.UUID | None,
        actor: User,
        data: schemas.VisitCreateRequest,
    ) -> SiteVisit:
        await self._authorized_site(site_id, company_id)

        visit = SiteVisit(
            site_id=site_id,
            visited_by_id=actor.id,
            visited_at=data.visited_at or datetime.now(UTC),
            notes=data.notes,
            items=[
                ChecklistItem(position=i, category=category, label=label)
                for i, (category, label) in enumerate(
                    default_items() if data.use_default_checklist else []
                )
            ],
        )
        self.db.add(visit)
        await self.db.commit()
        return await self._reload(visit.id)

    async def list_visits(
        self, site_id: uuid.UUID, company_id: uuid.UUID | None
    ) -> Sequence[SiteVisit]:
        await self._authorized_site(site_id, company_id)
        result = await self.db.scalars(
            select(SiteVisit)
            .where(SiteVisit.site_id == site_id)
            .order_by(SiteVisit.visited_at.desc())
        )
        return result.all()

    async def get_visit(self, visit_id: uuid.UUID, company_id: uuid.UUID | None) -> SiteVisit:
        visit = await self.db.get(SiteVisit, visit_id)
        if visit is None:
            raise VisitNotFoundError
        try:
            await self._authorized_site(visit.site_id, company_id)
        except SiteNotFoundError as exc:
            # Another company's visit: 404, not 403, so we don't leak its existence.
            raise VisitNotFoundError from exc
        return visit

    async def update_visit(
        self, visit_id: uuid.UUID, company_id: uuid.UUID | None, data: schemas.VisitUpdateRequest
    ) -> SiteVisit:
        visit = await self.get_visit(visit_id, company_id)
        reopening = data.status == VisitStatus.IN_PROGRESS
        if visit.status == VisitStatus.COMPLETED and not reopening:
            raise VisitCompletedError

        if data.visited_at is not None:
            visit.visited_at = data.visited_at
        if data.notes is not None:
            visit.notes = data.notes
        if data.status == VisitStatus.COMPLETED:
            if any(i.status == ChecklistItemStatus.PENDING for i in visit.items):
                raise PendingItemsError
            visit.status = VisitStatus.COMPLETED
            visit.completed_at = datetime.now(UTC)
        elif reopening:
            visit.status = VisitStatus.IN_PROGRESS
            visit.completed_at = None

        await self.db.commit()
        return await self._reload(visit.id)

    async def delete_visit(self, visit_id: uuid.UUID, company_id: uuid.UUID | None) -> None:
        visit = await self.get_visit(visit_id, company_id)
        await self.db.delete(visit)
        await self.db.commit()

    async def add_item(
        self,
        visit_id: uuid.UUID,
        company_id: uuid.UUID | None,
        data: schemas.ChecklistItemCreateRequest,
    ) -> ChecklistItem:
        visit = await self._editable_visit(visit_id, company_id)
        position = max((i.position for i in visit.items), default=-1) + 1
        item = ChecklistItem(position=position, category=data.category, label=data.label)
        # Go through the relationship (not db.add) so the loaded visit's item
        # list stays in sync with the database.
        visit.items.append(item)
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def update_item(
        self,
        visit_id: uuid.UUID,
        item_id: uuid.UUID,
        company_id: uuid.UUID | None,
        data: schemas.ChecklistItemUpdateRequest,
    ) -> ChecklistItem:
        visit = await self._editable_visit(visit_id, company_id)
        item = self._find_item(visit, item_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            if value is None and field in ("category", "label", "status"):
                continue  # required columns; null means "leave unchanged"
            setattr(item, field, value)
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def delete_item(
        self, visit_id: uuid.UUID, item_id: uuid.UUID, company_id: uuid.UUID | None
    ) -> None:
        visit = await self._editable_visit(visit_id, company_id)
        # Removing from the list deletes the row (delete-orphan cascade).
        visit.items.remove(self._find_item(visit, item_id))
        await self.db.commit()

    async def _editable_visit(self, visit_id: uuid.UUID, company_id: uuid.UUID | None) -> SiteVisit:
        visit = await self.get_visit(visit_id, company_id)
        if visit.status == VisitStatus.COMPLETED:
            raise VisitCompletedError
        return visit

    @staticmethod
    def _find_item(visit: SiteVisit, item_id: uuid.UUID) -> ChecklistItem:
        for item in visit.items:
            if item.id == item_id:
                return item
        raise ChecklistItemNotFoundError

    async def _reload(self, visit_id: uuid.UUID) -> SiteVisit:
        # Fresh load so the selectin-loaded items reflect what was just committed.
        visit = await self.db.scalar(
            select(SiteVisit)
            .where(SiteVisit.id == visit_id)
            .execution_options(populate_existing=True)
        )
        assert visit is not None
        return visit

    async def _authorized_site(self, site_id: uuid.UUID, company_id: uuid.UUID | None) -> Site:
        site = await self.db.get(Site, site_id)
        if site is None:
            raise SiteNotFoundError

        if company_id is not None:
            project = await self.db.get(Project, site.project_id)
            if project is None or project.company_id != company_id:
                # Site exists, just not in the caller's company — 404, not 403.
                raise SiteNotFoundError

        return site
