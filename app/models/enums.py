from enum import StrEnum


class UserRole(StrEnum):
    INSTALLER = "installer"
    COMPANY_ADMIN = "company_admin"
    SUPER_ADMIN = "super_admin"


class VisitStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class ChecklistItemStatus(StrEnum):
    PENDING = "pending"
    OK = "ok"
    ISSUE = "issue"
    NOT_APPLICABLE = "not_applicable"
