"""Dataset metadata, quality reports and the unranked product catalog.

Revision ID: 0001_data_foundation
Revises: None
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_data_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("dataset_id", sa.String(64), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("cleaning_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), server_default="ready", nullable=False),
        sa.Column("original_rows", sa.BigInteger(), nullable=False),
        sa.Column("cleaned_rows", sa.BigInteger(), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("artifacts", postgresql.JSONB(), nullable=False),
        sa.Column("artifact_dir", sa.Text(), nullable=False),
        sa.Column("manifest", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "dataset_id ~ '^[0-9a-f]{64}$'", name=op.f("ck_datasets_dataset_id_sha256")
        ),
        sa.CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_datasets_source_sha256")
        ),
        sa.CheckConstraint(
            "length(trim(cleaning_version)) > 0",
            name=op.f("ck_datasets_cleaning_version"),
        ),
        sa.CheckConstraint("status IN ('ready')", name=op.f("ck_datasets_status")),
        sa.CheckConstraint(
            "original_rows >= 0", name=op.f("ck_datasets_original_rows")
        ),
        sa.CheckConstraint(
            "cleaned_rows >= 0 AND cleaned_rows <= original_rows",
            name=op.f("ck_datasets_cleaned_rows"),
        ),
        sa.CheckConstraint(
            "length(trim(artifact_dir)) > 0", name=op.f("ck_datasets_artifact_dir")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(config) = 'object'", name=op.f("ck_datasets_config_object")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(artifacts) = 'object'",
            name=op.f("ck_datasets_artifacts_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(manifest) = 'object'",
            name=op.f("ck_datasets_manifest_object"),
        ),
        sa.PrimaryKeyConstraint("dataset_id", name="pk_datasets"),
    )
    op.create_table(
        "data_quality_reports",
        sa.Column("dataset_id", sa.String(64), nullable=False),
        sa.Column("report", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint(
            "jsonb_typeof(report) = 'object'",
            name=op.f("ck_data_quality_reports_report_object"),
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.dataset_id"],
            name="fk_data_quality_reports_dataset_id_datasets",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("dataset_id", name="pk_data_quality_reports"),
    )
    op.create_table(
        "products",
        sa.Column("dataset_id", sa.String(64), nullable=False),
        sa.Column("stock_code", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "length(trim(stock_code)) > 0", name=op.f("ck_products_stock_code")
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.dataset_id"],
            name="fk_products_dataset_id_datasets",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("dataset_id", "stock_code", name="pk_products"),
    )


def downgrade() -> None:
    op.drop_table("products")
    op.drop_table("data_quality_reports")
    op.drop_table("datasets")
