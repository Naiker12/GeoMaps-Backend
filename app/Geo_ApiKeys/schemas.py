import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.Geo_ApiKeys.model import APIKeyRole, APIKeyStatus, APIKeyVisibility

# ─── API KEY SCHEMAS ──────────────────────────────────────────────


class APIKeyBase(BaseModel):
    name: str = "Primary Key"
    description: Optional[str] = None
    role: APIKeyRole = APIKeyRole.CLIENT
    visibility: APIKeyVisibility = APIKeyVisibility.PRIVATE
    expires_at: Optional[datetime] = None
    rate_limit_rpm: Optional[int] = None


class APIKeyCreate(APIKeyBase):
    user_id: Optional[uuid.UUID] = None  # Si es Admin, puede asignar a otro usuario


class APIKeyUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[APIKeyStatus] = None
    role: Optional[APIKeyRole] = None
    visibility: Optional[APIKeyVisibility] = None
    expires_at: Optional[datetime] = None
    rate_limit_rpm: Optional[int] = None


class APIKeyResponse(APIKeyBase):
    id: uuid.UUID
    user_id: uuid.UUID
    key_prefix: str
    hint: str
    created_at: datetime
    last_used: Optional[datetime] = None
    status: APIKeyStatus

    total_requests: int
    total_tokens: int

    # Distribución de tokens por módulo si aplica (solo en admin o resumen)
    token_distribution: Optional[Dict[str, int]] = None

    # Solo en la respuesta inicial de creación
    key: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class APIKeyAdminResponse(APIKeyResponse):
    user_email: Optional[str] = None  # Para facilitar la vista de admin


# ─── METRICS & STATS SCHEMAS ──────────────────────────────────────


class TrafficDataPoint(BaseModel):
    date: str
    requests: int
    errors: int
    tokens: Any  # Puede ser int o Dict[str, int] según el endpoint


class EndpointDistribution(BaseModel):
    endpoint: str
    requests: int


class APIKeyStatsOverview(BaseModel):
    total_requests: int
    total_tokens: int
    active_keys: int
    revoked_keys: int
    error_rate: float
    avg_latency_ms: Optional[float]
    daily_requests: int = 0
    traffic_by_day: List[TrafficDataPoint]
    endpoint_distribution: Dict[str, int]
    token_distribution: Optional[Dict[str, int]] = None


# ─── CONFIGURATION SCHEMAS ────────────────────────────────────────


class IPWhitelistBase(BaseModel):
    cidr_block: str
    label: Optional[str] = None
    api_key_id: Optional[uuid.UUID] = None


class IPWhitelistResponse(IPWhitelistBase):
    id: uuid.UUID
    created_at: datetime


class RateLimitConfigBase(BaseModel):
    rpm_limit: int = 1000
    daily_limit: Optional[int] = None
    monthly_quota: int = 500000


class RateLimitConfigResponse(RateLimitConfigBase):
    user_id: uuid.UUID
    traffic_paused: bool
    paused_at: Optional[datetime]
    updated_at: datetime


class EmergencyPauseRequest(BaseModel):
    pause: bool


class PaginatedAPIKeyAdminResponse(BaseModel):
    items: List[APIKeyAdminResponse]
    total: int
    page: int
    limit: int

    model_config = ConfigDict(from_attributes=True)
