"""Pydantic v2 request and response schemas for the MT5 Trading Bridge API."""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field, model_validator


OrderSide = Literal["BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"]


class OrderCheckRequest(BaseModel):
    symbol: str = Field(default="XAUUSD")
    side: OrderSide
    lots: float | None = Field(default=None, gt=0)
    risk_pct: float | None = Field(default=None, gt=0, le=100)
    entry_price: float | None = Field(default=None, gt=0)
    sl: float | None = Field(default=None, gt=0)
    tp: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_sizing(self) -> "OrderCheckRequest":
        if self.lots is None and self.risk_pct is None:
            raise ValueError("Provide either lots or risk_pct.")
        if self.risk_pct is not None and self.sl is None:
            raise ValueError("sl is required when sizing by risk_pct.")
        return self


class ProposalCreateRequest(OrderCheckRequest):
    source: str = Field(default="WEB", max_length=32)
    timeframe: str = Field(default="M15", max_length=16)
    rationale: str = Field(default="", max_length=1000)


class ProposalConfirmRequest(BaseModel):
    deviation: int = Field(default=30, ge=0, le=500)
    comment: str | None = Field(default=None, max_length=31)
    allow_real: bool = Field(default=False)
    force: bool = Field(default=False)


class ProposalRejectRequest(BaseModel):
    reason: str = Field(default="", max_length=500)


class PositionModifyRequest(BaseModel):
    sl: float | None = Field(default=None, ge=0)
    tp: float | None = Field(default=None, ge=0)
    price_open: float | None = Field(default=None, ge=0)
    allow_real: bool = Field(default=False)


class PositionCloseRequest(BaseModel):
    lots: float | None = Field(default=None, gt=0)
    deviation: int = Field(default=30, ge=0, le=500)
    allow_real: bool = Field(default=False)


class TradeLogUpdateRequest(BaseModel):
    strategy_tag: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=1000)


class WatchlistUpdateRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=30)


class GauntletEvaluateRequest(BaseModel):
    symbol: str = Field(default="XAUUSD")
    tf: str = Field(default="M15")
    risk_pct: float = Field(default=2.0, gt=0, le=50)
    min_confidence_pct: float = Field(default=75.0, ge=50.0, le=95.0)
    sl_atr_mult: float = Field(default=1.5, ge=0.4, le=6.0)
    tp_atr_mult: float = Field(default=2.5, ge=0.5, le=10.0)
    min_rr_ratio: float = Field(default=1.5, ge=0.8, le=6.0)
    auto_queue: bool = Field(default=False)


class WatchdogConfigPatchRequest(BaseModel):
    enabled: bool | None = None
    interval_sec: int | None = Field(default=None, ge=30, le=3600)
    timeframe: str | None = None
    risk_pct: float | None = Field(default=None, gt=0, le=50)
    min_confidence_pct: float | None = Field(default=None, ge=50.0, le=95.0)
    auto_propose: bool | None = None
    auto_accept_proposals: bool | None = None
    cooldown_min: int | None = Field(default=None, ge=1, le=1440)
    autopilot_enabled: bool | None = None
    autopilot_min_confidence_pct: float | None = Field(default=None, ge=55.0, le=95.0)
    autopilot_sizing_mode: Literal["FIXED_LOT", "RISK_PCT"] | None = None
    autopilot_fixed_lots: float | None = Field(default=None, ge=0.01, le=5.0)
    autopilot_risk_pct: float | None = Field(default=None, gt=0, le=50)
    autopilot_max_open_positions: int | None = Field(default=None, ge=1, le=10)
    proposal_ttl_min: int | None = Field(default=None, ge=5, le=1440)
    max_drift_atr: float | None = Field(default=None, ge=0.1, le=5.0)
    max_daily_loss_pct: float | None = Field(default=None, ge=0.5, le=50.0)
    max_open_risk_pct: float | None = Field(default=None, ge=1.0, le=100.0)
    sl_atr_mult: float | None = Field(default=None, ge=0.4, le=6.0)
    tp_atr_mult: float | None = Field(default=None, ge=0.5, le=10.0)
    min_rr_ratio: float | None = Field(default=None, ge=0.8, le=6.0)


class PositionManagerConfigPatchRequest(BaseModel):
    enabled: bool | None = None
    poll_interval_sec: int | None = Field(default=None, ge=2, le=120)
    auto_breakeven: bool | None = None
    be_trigger_r: float | None = Field(default=None, ge=0.3, le=5.0)
    be_offset_points: int | None = Field(default=None, ge=0, le=100)
    auto_partial_tp: bool | None = None
    partial_trigger_r: float | None = Field(default=None, ge=0.5, le=10.0)
    partial_close_pct: float | None = Field(default=None, ge=10.0, le=90.0)
    auto_trailing_sl: bool | None = None
    trail_start_r: float | None = Field(default=None, ge=0.5, le=10.0)
    trail_distance_r: float | None = Field(default=None, ge=0.2, le=5.0)


class DiscordConfigRequest(BaseModel):
    enabled: bool | None = None
    webhook_url: str | None = None
    public_base_url: str | None = None
    notify_proposals: bool | None = None
    notify_autopilot: bool | None = None
    notify_position_manager: bool | None = None


class SheetsConfigRequest(BaseModel):
    enabled: bool | None = None
    webhook_url: str | None = None
    service_account_file: str | None = None
    sheet_id: str | None = None


class MLTrainRequest(BaseModel):
    symbol: str = Field(default="XAUUSD")
    tf: str = Field(default="M30")
    bars: int = Field(default=8000, ge=1500, le=12000)
    tp_atr: float = Field(default=2.5, ge=0.5, le=10.0)
    sl_atr: float = Field(default=1.5, ge=0.4, le=6.0)
    champion_guard: bool = Field(default=True)
    force_promote: bool = Field(default=False)


class MLRetrainConfigPatchRequest(BaseModel):
    enabled: bool | None = None
    interval_hours: float | None = Field(default=None, ge=1.0, le=336.0)
    timeframe: str | None = None
    champion_guard: bool | None = None


class MLBenchmarkRequest(BaseModel):
    symbol: str = Field(default="XAUUSD")
    timeframes: list[str] = Field(default_factory=lambda: ["M15", "M30", "H1"])
    tp_atr: float = Field(default=2.5, ge=0.5, le=10.0)
    sl_atr: float = Field(default=1.5, ge=0.4, le=6.0)
