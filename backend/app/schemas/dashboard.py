"""Bounded dashboard queries and stateless, assumption-driven planner inputs."""

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.schemas.requests import Digest, StrictRequest
from ml.inventory.planning import MAX_UNITS, InventoryParameters, InventoryState

Units = Annotated[int, Field(strict=True, ge=0, le=MAX_UNITS)]
PositiveUnits = Annotated[int, Field(strict=True, ge=1, le=MAX_UNITS)]
Nonnegative = Annotated[float, Field(strict=True, ge=0, le=1e12, allow_inf_nan=False)]
StockCode = Annotated[str, Field(min_length=1, max_length=128)]


class PreviewParameters(StrictRequest):
    lead_time_weeks: Annotated[int, Field(strict=True, ge=1, le=104)] = 1
    review_period_weeks: Annotated[int, Field(strict=True, ge=1, le=104)] = 1
    service_level: Annotated[float, Field(strict=True, gt=0, lt=1)] = 0.95
    unit_purchase_cost: Nonnegative = 1.0
    unit_selling_price: Nonnegative = 2.0
    holding_cost_per_unit_week: Nonnegative = 0.02
    stockout_penalty_per_unit: Nonnegative = 3.0
    order_cost: Nonnegative = 5.0
    min_order_quantity: Units = 0
    case_pack_size: PositiveUnits = 1
    max_inventory_capacity: Units | None = None

    def inventory_parameters(self) -> InventoryParameters:
        return InventoryParameters(**self.model_dump())


class InventoryPreviewRequest(StrictRequest):
    forecast_id: Digest
    stock_code: StockCode
    on_hand: Units
    on_order: Units = 0
    backordered_units: Units = 0
    parameters: PreviewParameters = Field(default_factory=PreviewParameters)

    @model_validator(mode="after")
    def feasible_state(self):
        if self.stock_code != self.stock_code.strip():
            raise ValueError("stock_code must be normalized")
        state = self.inventory_state()
        parameters = self.parameters.inventory_parameters()
        capacity = parameters.max_inventory_capacity
        if capacity is not None and state.on_hand + state.on_order > capacity:
            raise ValueError("On-hand plus on-order inventory exceeds capacity")
        return self

    def inventory_state(self) -> InventoryState:
        return InventoryState(self.on_hand, self.on_order, self.backordered_units)


class Projection(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class CohortProduct(Projection):
    stock_code: str
    description: str | None
    training_units: int
    active_training_weeks: int


class DashboardContext(Projection):
    dataset: dict[str, Any] | None
    run: dict[str, Any] | None
    one_week_forecast: dict[str, Any] | None
    retrospective_forecast: dict[str, Any] | None
    scenario: dict[str, Any] | None
    products: list[CohortProduct]
    overview: dict[str, Any] | None
    scope: dict[str, str]


class DashboardRun(Projection):
    run_id: str
    dataset_id: str
    plan: dict[str, Any]
    cohort: list[dict[str, Any]]
    importance: dict[str, list[dict[str, Any]]]
    metrics: dict[str, Any]
    interval_metrics: dict[str, Any] | None
    training_metadata: dict[str, Any]
    test_status: str


class DashboardForecast(Projection):
    forecast_id: str
    run_id: str
    dataset_id: str
    scope: str
    selected_ml_family: str
    product: dict[str, Any]
    history: list[dict[str, Any]]
    forecasts: list[dict[str, Any]]
    features: dict[str, Any]
    product_errors: list[dict[str, Any]]
    planner_defaults: dict[str, Any]


class DashboardScenario(Projection):
    scenario_id: str
    forecast_id: str
    configuration_id: str
    config: dict[str, Any]
    summary: dict[str, Any]
    weekly: list[dict[str, Any]]
    risk_products: list[dict[str, Any]]
    recommendations: list[dict[str, Any]]
    scope: str


class InventoryPreview(Projection):
    forecast_id: str
    stock_code: str
    method: str
    week: str
    scope: str
    state: dict[str, int]
    parameters: dict[str, Any]
    recommendation: dict[str, Any]
    risk: dict[str, Any]
    cost_preview: dict[str, Any]
    error_estimate: dict[str, Any]
