from enum import StrEnum


class UserRole(StrEnum):
    INSTALLER = "installer"
    COMPANY_ADMIN = "company_admin"
    SUPER_ADMIN = "super_admin"
