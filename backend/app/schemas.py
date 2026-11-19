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


class ProposalRejectRequest(BaseModel):
    reason: str = Field(default="", max_length=500)


class PositionModifyRequest(BaseModel):
    sl: float | None = Field(default=None, ge=0)
    tp: float | None = Field(default=None, ge=0)
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
    risk_pct: float = Field(default=15.0, gt=0, le=50)
    auto_queue: bool = Field(default=False)


class WatchdogConfigPatchRequest(BaseModel):
    enabled: bool | None = None
    interval_sec: int | None = Field(default=None, ge=30, le=3600)
    timeframe: str | None = None
    risk_pct: float | None = Field(default=None, gt=0, le=50)
    auto_propose: bool | None = None
    cooldown_min: int | None = Field(default=None, ge=1, le=1440)


class SheetsConfigRequest(BaseModel):
    enabled: bool | None = None
    webhook_url: str | None = None
    service_account_file: str | None = None
    sheet_id: str | None = None
