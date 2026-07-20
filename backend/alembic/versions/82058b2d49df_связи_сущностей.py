"""Связи сущностей

Revision ID: 82058b2d49df
Revises: d16e7f08d828
Create Date: 2026-07-21 02:37:46.739592

Добавляет две таблицы графа взаимосвязей (ТЗ 13): узлы и связи между ними.

Из автосгенерированной версии удалён блок `create_foreign_key` по трём десяткам
существующих таблиц. Это ложное срабатывание Alembic: внешние ключи
происхождения объявлены с `use_alter=True`, и автогенерация не распознаёт их в
уже созданной схеме, предлагая завести повторно. Выполнение такого блока
породило бы дубликаты ограничений на всех таблицах проекта.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "82058b2d49df"
down_revision: str | None = "d16e7f08d828"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "graph_nodes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("node_key", sa.String(length=64), nullable=False),
        sa.Column("node_type", sa.String(length=24), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("sublabel", sa.Text(), nullable=True),
        sa.Column("identifier", sa.String(length=32), nullable=True),
        sa.Column("identifier_kind", sa.String(length=8), nullable=True),
        sa.Column("risk_level", sa.String(length=16), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("risk_is_preliminary", sa.Boolean(), nullable=False),
        sa.Column("territory_id", sa.UUID(), nullable=True),
        sa.Column("ref_entity_type", sa.String(length=32), nullable=True),
        sa.Column("ref_entity_id", sa.UUID(), nullable=True),
        sa.Column("source_layer", sa.String(length=16), nullable=False),
        sa.Column("degree", sa.Integer(), nullable=False),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("source_dataset_id", sa.UUID(), nullable=True),
        sa.Column("import_job_id", sa.UUID(), nullable=True),
        sa.Column("source_row_ref", sa.String(length=255), nullable=True),
        sa.Column("natural_key", sa.String(length=255), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_as_of", sa.Date(), nullable=True),
        sa.Column("validation_status", sa.String(length=24), nullable=False),
        sa.Column("validation_notes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("data_version", sa.Integer(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.CheckConstraint("degree >= 0", name="ck_graph_node_degree_non_negative"),
        sa.CheckConstraint(
            "identifier IS NULL OR identifier_kind IS NOT NULL",
            name="ck_graph_node_identifier_kind",
        ),
        sa.ForeignKeyConstraint(
            ["import_job_id"], ["import_jobs.id"], ondelete="SET NULL", use_alter=True
        ),
        sa.ForeignKeyConstraint(
            ["source_dataset_id"], ["source_datasets.id"], ondelete="SET NULL", use_alter=True
        ),
        sa.ForeignKeyConstraint(["territory_id"], ["territories.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("node_key", name="uq_graph_node_key"),
    )
    op.create_index(
        op.f("ix_graph_nodes_import_job_id"), "graph_nodes", ["import_job_id"], unique=False
    )
    op.create_index("ix_graph_nodes_label", "graph_nodes", ["label"], unique=False)
    op.create_index(
        op.f("ix_graph_nodes_natural_key"), "graph_nodes", ["natural_key"], unique=False
    )
    op.create_index("ix_graph_nodes_risk_level", "graph_nodes", ["risk_level"], unique=False)
    op.create_index(
        op.f("ix_graph_nodes_source_dataset_id"),
        "graph_nodes",
        ["source_dataset_id"],
        unique=False,
    )
    op.create_index("ix_graph_nodes_territory", "graph_nodes", ["territory_id"], unique=False)
    op.create_index("ix_graph_nodes_type", "graph_nodes", ["node_type"], unique=False)

    op.create_table(
        "entity_relations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("relation_type", sa.String(length=24), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("confidence_basis", sa.String(length=255), nullable=False),
        sa.Column("source_node_id", sa.UUID(), nullable=False),
        sa.Column("target_node_id", sa.UUID(), nullable=False),
        sa.Column("source_layer", sa.String(length=16), nullable=False),
        sa.Column("derivation_rule", sa.String(length=128), nullable=False),
        sa.Column("territory_id", sa.UUID(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("source_dataset_id", sa.UUID(), nullable=True),
        sa.Column("import_job_id", sa.UUID(), nullable=True),
        sa.Column("source_row_ref", sa.String(length=255), nullable=True),
        sa.Column("natural_key", sa.String(length=255), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_as_of", sa.Date(), nullable=True),
        sa.Column("validation_status", sa.String(length=24), nullable=False),
        sa.Column("validation_notes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("data_version", sa.Integer(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "source_node_id <> target_node_id", name="ck_entity_relation_no_self_loop"
        ),
        sa.ForeignKeyConstraint(
            ["import_job_id"], ["import_jobs.id"], ondelete="SET NULL", use_alter=True
        ),
        sa.ForeignKeyConstraint(
            ["source_dataset_id"], ["source_datasets.id"], ondelete="SET NULL", use_alter=True
        ),
        sa.ForeignKeyConstraint(["source_node_id"], ["graph_nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_node_id"], ["graph_nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["territory_id"], ["territories.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "relation_type", "source_node_id", "target_node_id", name="uq_entity_relation_pair"
        ),
    )
    op.create_index(
        "ix_entity_relations_confidence", "entity_relations", ["confidence"], unique=False
    )
    op.create_index(
        op.f("ix_entity_relations_import_job_id"),
        "entity_relations",
        ["import_job_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_entity_relations_natural_key"), "entity_relations", ["natural_key"], unique=False
    )
    op.create_index(
        "ix_entity_relations_source", "entity_relations", ["source_node_id"], unique=False
    )
    op.create_index(
        op.f("ix_entity_relations_source_dataset_id"),
        "entity_relations",
        ["source_dataset_id"],
        unique=False,
    )
    op.create_index(
        "ix_entity_relations_target", "entity_relations", ["target_node_id"], unique=False
    )
    op.create_index(
        "ix_entity_relations_territory", "entity_relations", ["territory_id"], unique=False
    )
    op.create_index("ix_entity_relations_type", "entity_relations", ["relation_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_entity_relations_type", table_name="entity_relations")
    op.drop_index("ix_entity_relations_territory", table_name="entity_relations")
    op.drop_index("ix_entity_relations_target", table_name="entity_relations")
    op.drop_index(op.f("ix_entity_relations_source_dataset_id"), table_name="entity_relations")
    op.drop_index("ix_entity_relations_source", table_name="entity_relations")
    op.drop_index(op.f("ix_entity_relations_natural_key"), table_name="entity_relations")
    op.drop_index(op.f("ix_entity_relations_import_job_id"), table_name="entity_relations")
    op.drop_index("ix_entity_relations_confidence", table_name="entity_relations")
    op.drop_table("entity_relations")

    op.drop_index("ix_graph_nodes_type", table_name="graph_nodes")
    op.drop_index("ix_graph_nodes_territory", table_name="graph_nodes")
    op.drop_index(op.f("ix_graph_nodes_source_dataset_id"), table_name="graph_nodes")
    op.drop_index("ix_graph_nodes_risk_level", table_name="graph_nodes")
    op.drop_index(op.f("ix_graph_nodes_natural_key"), table_name="graph_nodes")
    op.drop_index("ix_graph_nodes_label", table_name="graph_nodes")
    op.drop_index(op.f("ix_graph_nodes_import_job_id"), table_name="graph_nodes")
    op.drop_table("graph_nodes")
