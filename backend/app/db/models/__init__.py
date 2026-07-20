"""Реестр моделей.

Импорт всех модулей моделей в одном месте нужен затем, чтобы к моменту
автогенерации миграции и создания схемы `Base.metadata` содержала все таблицы.
Без этого Alembic видит только те модели, которые случайно импортировал кто-то
другой, и молча генерирует неполную миграцию.
"""

from app.db.base import Base
from app.db.models.access import (
    AuditAction,
    AuditLogEntry,
    Permission,
    Role,
    RoleCode,
    SavedView,
    SensitiveDataAccess,
    User,
    role_permissions,
)
from app.db.models.budget import BudgetFact, BudgetMonthlyMetric, BudgetProgram
from app.db.models.graph import (
    EntityRelation,
    GraphNode,
    NodeType,
    RelationConfidence,
    RelationDirection,
    RelationType,
)
from app.db.models.infrastructure import (
    ConstructionExpertiseObject,
    PppProject,
    ProjectEntity,
    ProjectEntityKind,
    ProjectParticipant,
    TerritoryPrecision,
)
from app.db.models.organization import (
    Address,
    Identifier,
    Organization,
    OrganizationPersonRole,
    Person,
)
from app.db.models.procurement import (
    Contract,
    ContractAddition,
    Customer,
    Lot,
    Procurement,
    Supplier,
)
from app.db.models.source import (
    DataQualityIssue,
    ImportJob,
    ImportStatus,
    IssueSeverity,
    SourceDataset,
    SourceFile,
)
from app.db.models.subsidy import SubsidyPayment, SubsidyProgram, SubsidyRecipient
from app.db.models.territory import (
    AliasKind,
    BoundaryVersion,
    PopulationStat,
    Territory,
    TerritoryAlias,
    TerritoryGeometry,
    TerritoryLevel,
)

__all__ = [
    "Address",
    "AliasKind",
    "AuditAction",
    "AuditLogEntry",
    "Base",
    "BoundaryVersion",
    "BudgetFact",
    "BudgetMonthlyMetric",
    "BudgetProgram",
    "ConstructionExpertiseObject",
    "Contract",
    "ContractAddition",
    "Customer",
    "DataQualityIssue",
    "EntityRelation",
    "GraphNode",
    "Identifier",
    "ImportJob",
    "ImportStatus",
    "IssueSeverity",
    "Lot",
    "NodeType",
    "Organization",
    "OrganizationPersonRole",
    "Permission",
    "Person",
    "PopulationStat",
    "PppProject",
    "Procurement",
    "ProjectEntity",
    "ProjectEntityKind",
    "ProjectParticipant",
    "RelationConfidence",
    "RelationDirection",
    "RelationType",
    "Role",
    "RoleCode",
    "SavedView",
    "SensitiveDataAccess",
    "SourceDataset",
    "SourceFile",
    "SubsidyPayment",
    "SubsidyProgram",
    "SubsidyRecipient",
    "Supplier",
    "Territory",
    "TerritoryAlias",
    "TerritoryGeometry",
    "TerritoryLevel",
    "TerritoryPrecision",
    "User",
    "role_permissions",
]
