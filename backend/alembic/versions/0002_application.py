"""Durable jobs and application lineage for forecasting/inventory artifacts.

Revision ID: 0002_application
Revises: 0001_data_foundation

All new foreign keys cascade from their parent. No existing analytical file,
metadata row or frozen model is modified by this schema migration.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_application"
down_revision = "0001_data_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_configurations",
        sa.Column("configuration_id", sa.String(length=64), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "configuration_id ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_inventory_configurations_configuration_id_sha256"),
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name=op.f("ck_inventory_configurations_currency")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(config) = 'object'",
            name=op.f("ck_inventory_configurations_config_object"),
        ),
        sa.PrimaryKeyConstraint(
            "configuration_id", name=op.f("pk_inventory_configurations")
        ),
    )
    op.create_table(
        "jobs",
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="queued", nullable=False
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("locked_by", sa.String(length=64), nullable=True),
        sa.Column("lease_token", sa.String(length=36), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "result",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
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
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = 'running' AND locked_by IS NOT NULL AND length(trim(locked_by)) > 0 AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR (status <> 'running' AND locked_by IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL)",
            name=op.f("ck_jobs_lease_state"),
        ),
        sa.CheckConstraint(
            "job_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
            name=op.f("ck_jobs_job_id_uuid"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name=op.f("ck_jobs_payload_object")
        ),
        sa.CheckConstraint(
            "kind IN ('dataset_import', 'training', 'forecasting', 'inventory')",
            name=op.f("ck_jobs_kind"),
        ),
        sa.CheckConstraint(
            "lease_token IS NULL OR lease_token ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
            name=op.f("ck_jobs_lease_token_uuid"),
        ),
        sa.CheckConstraint(
            "payload_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_jobs_payload_hash_sha256")
        ),
        sa.CheckConstraint(
            "result IS NULL OR (jsonb_typeof(result) = 'object')",
            name=op.f("ck_jobs_result_object"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name=op.f("ck_jobs_status"),
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND attempts <= max_attempts", name=op.f("ck_jobs_attempts")
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR length(trim(error_code)) > 0",
            name=op.f("ck_jobs_error_code"),
        ),
        sa.CheckConstraint(
            "length(trim(idempotency_key)) > 0", name=op.f("ck_jobs_idempotency_key")
        ),
        sa.CheckConstraint(
            "max_attempts BETWEEN 1 AND 5", name=op.f("ck_jobs_max_attempts")
        ),
        sa.PrimaryKeyConstraint("job_id", name=op.f("pk_jobs")),
        sa.UniqueConstraint("kind", "idempotency_key", name=op.f("uq_jobs_kind")),
    )
    op.create_index(
        "ix_jobs_queued_available",
        "jobs",
        ["available_at", "created_at"],
        unique=False,
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.create_index(
        "ix_jobs_running_expiry",
        "jobs",
        ["lease_expires_at"],
        unique=False,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_table(
        "training_runs",
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("dataset_id", sa.String(length=64), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("artifact_dir", sa.Text(), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(config) = 'object'",
            name=op.f("ck_training_runs_config_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metrics) = 'object'",
            name=op.f("ck_training_runs_metrics_object"),
        ),
        sa.CheckConstraint(
            "length(trim(artifact_dir)) > 0 AND artifact_dir = trim(artifact_dir) AND artifact_dir !~ '^/' AND artifact_dir !~ '^[A-Za-z]:' AND artifact_dir !~ '(^|/)[.][.]?(/|$)' AND strpos(artifact_dir, chr(92)) = 0",
            name=op.f("ck_training_runs_artifact_dir_relative"),
        ),
        sa.CheckConstraint(
            "manifest_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_training_runs_manifest_sha256_sha256"),
        ),
        sa.CheckConstraint(
            "run_id ~ '^[0-9a-f]{64}$'", name=op.f("ck_training_runs_run_id_sha256")
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.dataset_id"],
            name=op.f("fk_training_runs_dataset_id_datasets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_training_runs")),
        sa.UniqueConstraint(
            "run_id", "dataset_id", name=op.f("uq_training_runs_run_id")
        ),
    )
    op.create_table(
        "forecast_batches",
        sa.Column("forecast_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=24), nullable=False),
        sa.Column(
            "metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("artifact_dir", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "forecast_id ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_forecast_batches_forecast_id_sha256"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata_json) = 'object'",
            name=op.f("ck_forecast_batches_metadata_json_object"),
        ),
        sa.CheckConstraint(
            "length(trim(artifact_dir)) > 0 AND artifact_dir = trim(artifact_dir) AND artifact_dir !~ '^/' AND artifact_dir !~ '^[A-Za-z]:' AND artifact_dir !~ '(^|/)[.][.]?(/|$)' AND strpos(artifact_dir, chr(92)) = 0",
            name=op.f("ck_forecast_batches_artifact_dir_relative"),
        ),
        sa.CheckConstraint(
            "scope IN ('one_week', 'retrospective')",
            name=op.f("ck_forecast_batches_scope"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["training_runs.run_id"],
            name=op.f("fk_forecast_batches_run_id_training_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("forecast_id", name=op.f("pk_forecast_batches")),
    )
    op.create_table(
        "model_artifacts",
        sa.Column("model_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("family", sa.String(length=32), nullable=False),
        sa.Column("artifact_key", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "family IN ('ridge', 'random_forest', 'xgboost')",
            name=op.f("ck_model_artifacts_family"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata_json) = 'object'",
            name=op.f("ck_model_artifacts_metadata_json_object"),
        ),
        sa.CheckConstraint(
            "length(trim(artifact_key)) > 0 AND artifact_key = trim(artifact_key) AND artifact_key !~ '^/' AND artifact_key !~ '^[A-Za-z]:' AND artifact_key !~ '(^|/)[.][.]?(/|$)' AND strpos(artifact_key, chr(92)) = 0",
            name=op.f("ck_model_artifacts_artifact_key_relative"),
        ),
        sa.CheckConstraint(
            "model_id ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_model_artifacts_model_id_sha256"),
        ),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_model_artifacts_sha256_sha256")
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["training_runs.run_id"],
            name=op.f("fk_model_artifacts_run_id_training_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("model_id", name=op.f("pk_model_artifacts")),
    )
    op.create_table(
        "weekly_demand",
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("stock_code", sa.String(length=128), nullable=False),
        sa.Column("week", sa.Date(), nullable=False),
        sa.Column("dataset_id", sa.String(length=64), nullable=False),
        sa.Column("gross_units", sa.BigInteger(), nullable=False),
        sa.Column("returned_units", sa.BigInteger(), nullable=False),
        sa.Column("cancellation_units", sa.BigInteger(), nullable=False),
        sa.Column("net_units", sa.BigInteger(), nullable=False),
        sa.Column("revenue", sa.Float(), nullable=False),
        sa.Column("transactions", sa.BigInteger(), nullable=False),
        sa.Column("unique_customers", sa.BigInteger(), nullable=False),
        sa.Column("average_price", sa.Float(), nullable=True),
        sa.CheckConstraint(
            "(gross_units = 0 AND average_price IS NULL AND revenue = 0 AND transactions = 0 AND unique_customers = 0) OR (gross_units > 0 AND average_price IS NOT NULL AND average_price > 0 AND average_price < 'Infinity'::float8)",
            name=op.f("ck_weekly_demand_average_price"),
        ),
        sa.CheckConstraint(
            "revenue >= 0 AND revenue < 'Infinity'::float8",
            name=op.f("ck_weekly_demand_revenue_finite"),
        ),
        sa.CheckConstraint(
            "extract(isodow from week) = 1", name=op.f("ck_weekly_demand_week_monday")
        ),
        sa.CheckConstraint(
            "gross_units >= 0 AND returned_units >= 0 AND cancellation_units >= 0",
            name=op.f("ck_weekly_demand_movement_units"),
        ),
        sa.CheckConstraint(
            "net_units::numeric = gross_units::numeric - returned_units::numeric - cancellation_units::numeric",
            name=op.f("ck_weekly_demand_net_units"),
        ),
        sa.CheckConstraint(
            "transactions >= 0 AND unique_customers >= 0 AND unique_customers <= transactions",
            name=op.f("ck_weekly_demand_transaction_counts"),
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id", "stock_code"],
            ["products.dataset_id", "products.stock_code"],
            name=op.f("fk_weekly_demand_dataset_id_products"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "dataset_id"],
            ["training_runs.run_id", "training_runs.dataset_id"],
            name=op.f("fk_weekly_demand_run_id_training_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "run_id", "stock_code", "week", name=op.f("pk_weekly_demand")
        ),
    )
    op.create_table(
        "forecast_values",
        sa.Column("forecast_id", sa.String(length=64), nullable=False),
        sa.Column("stock_code", sa.String(length=128), nullable=False),
        sa.Column("week", sa.Date(), nullable=False),
        sa.Column("method", sa.String(length=64), nullable=False),
        sa.Column("point", sa.Float(), nullable=False),
        sa.Column("lower", sa.Float(), nullable=False),
        sa.Column("upper", sa.Float(), nullable=False),
        sa.Column("actual", sa.BigInteger(), nullable=True),
        sa.Column("nominal_coverage", sa.Float(), nullable=False),
        sa.Column("uncertainty_label", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "lower >= 0 AND lower < 'Infinity'::float8 AND point >= lower AND point <= upper AND upper < 'Infinity'::float8",
            name=op.f("ck_forecast_values_bounds_finite"),
        ),
        sa.CheckConstraint(
            "actual IS NULL OR actual >= 0", name=op.f("ck_forecast_values_actual")
        ),
        sa.CheckConstraint(
            "extract(isodow from week) = 1", name=op.f("ck_forecast_values_week_monday")
        ),
        sa.CheckConstraint(
            "length(trim(method)) > 0", name=op.f("ck_forecast_values_method")
        ),
        sa.CheckConstraint(
            "length(trim(stock_code)) > 0 AND stock_code = trim(stock_code)",
            name=op.f("ck_forecast_values_stock_code"),
        ),
        sa.CheckConstraint(
            "length(trim(uncertainty_label)) > 0",
            name=op.f("ck_forecast_values_uncertainty_label"),
        ),
        sa.CheckConstraint(
            "nominal_coverage > 0 AND nominal_coverage < 1",
            name=op.f("ck_forecast_values_nominal_coverage"),
        ),
        sa.ForeignKeyConstraint(
            ["forecast_id"],
            ["forecast_batches.forecast_id"],
            name=op.f("fk_forecast_values_forecast_id_forecast_batches"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "forecast_id",
            "stock_code",
            "week",
            "method",
            name=op.f("pk_forecast_values"),
        ),
    )
    op.create_table(
        "simulation_scenarios",
        sa.Column("scenario_id", sa.String(length=64), nullable=False),
        sa.Column("forecast_id", sa.String(length=64), nullable=False),
        sa.Column("configuration_id", sa.String(length=64), nullable=False),
        sa.Column("artifact_dir", sa.Text(), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(summary) = 'object'",
            name=op.f("ck_simulation_scenarios_summary_object"),
        ),
        sa.CheckConstraint(
            "length(trim(artifact_dir)) > 0 AND artifact_dir = trim(artifact_dir) AND artifact_dir !~ '^/' AND artifact_dir !~ '^[A-Za-z]:' AND artifact_dir !~ '(^|/)[.][.]?(/|$)' AND strpos(artifact_dir, chr(92)) = 0",
            name=op.f("ck_simulation_scenarios_artifact_dir_relative"),
        ),
        sa.CheckConstraint(
            "manifest_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_simulation_scenarios_manifest_sha256_sha256"),
        ),
        sa.CheckConstraint(
            "scenario_id ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_simulation_scenarios_scenario_id_sha256"),
        ),
        sa.ForeignKeyConstraint(
            ["configuration_id"],
            ["inventory_configurations.configuration_id"],
            name=op.f(
                "fk_simulation_scenarios_configuration_id_inventory_configurations"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["forecast_id"],
            ["forecast_batches.forecast_id"],
            name=op.f("fk_simulation_scenarios_forecast_id_forecast_batches"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("scenario_id", name=op.f("pk_simulation_scenarios")),
    )
    op.create_table(
        "simulation_results",
        sa.Column("scenario_id", sa.String(length=64), nullable=False),
        sa.Column("policy", sa.String(length=64), nullable=False),
        sa.Column("stock_code", sa.String(length=128), nullable=False),
        sa.Column("week", sa.Date(), nullable=False),
        sa.Column("actual", sa.BigInteger(), nullable=False),
        sa.Column("fulfilled_units", sa.BigInteger(), nullable=False),
        sa.Column("lost_units", sa.BigInteger(), nullable=False),
        sa.Column("ending_inventory", sa.BigInteger(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "NOT (details ?| ARRAY['scenario_id', 'policy', 'stock_code', 'week', 'actual', 'fulfilled_units', 'lost_units', 'ending_inventory'])",
            name=op.f("ck_simulation_results_details_excludes_columns"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(details) = 'object'",
            name=op.f("ck_simulation_results_details_object"),
        ),
        sa.CheckConstraint(
            "actual >= 0 AND fulfilled_units >= 0 AND lost_units >= 0 AND ending_inventory >= 0",
            name=op.f("ck_simulation_results_nonnegative_units"),
        ),
        sa.CheckConstraint(
            "actual::numeric = fulfilled_units::numeric + lost_units::numeric",
            name=op.f("ck_simulation_results_demand_conservation"),
        ),
        sa.CheckConstraint(
            "extract(isodow from week) = 1",
            name=op.f("ck_simulation_results_week_monday"),
        ),
        sa.CheckConstraint(
            "length(trim(policy)) > 0", name=op.f("ck_simulation_results_policy")
        ),
        sa.CheckConstraint(
            "length(trim(stock_code)) > 0 AND stock_code = trim(stock_code)",
            name=op.f("ck_simulation_results_stock_code"),
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["simulation_scenarios.scenario_id"],
            name=op.f("fk_simulation_results_scenario_id_simulation_scenarios"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "scenario_id",
            "policy",
            "stock_code",
            "week",
            name=op.f("pk_simulation_results"),
        ),
    )


def downgrade() -> None:
    op.drop_table("simulation_results")
    op.drop_table("simulation_scenarios")
    op.drop_table("forecast_values")
    op.drop_table("weekly_demand")
    op.drop_table("model_artifacts")
    op.drop_table("forecast_batches")
    op.drop_table("training_runs")
    op.drop_index(
        "ix_jobs_running_expiry",
        table_name="jobs",
        postgresql_where=sa.text("status = 'running'"),
    )
    op.drop_index(
        "ix_jobs_queued_available",
        table_name="jobs",
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.drop_table("jobs")
    op.drop_table("inventory_configurations")
