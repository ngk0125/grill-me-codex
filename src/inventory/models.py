from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class InventoryRecord(BaseModel):
    sku: str
    available_qty: int
    warehouse_locations: list[str]
    allocation_status: str  # e.g. "AVAILABLE", "RESERVED", "ALLOCATED"
    backorder_status: bool
    as_of: datetime


class InventoryResponse(BaseModel):
    records: dict[str, InventoryRecord]  # keyed by SKU
    queried_at: datetime
    is_degraded: bool
