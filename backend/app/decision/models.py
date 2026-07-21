from enum import StrEnum
from pydantic import BaseModel, Field
from app.models.routes import RouteOption

class DecisionReasonKind(StrEnum):
    ADVANTAGE = "advantage"
    DISADVANTAGE = "disadvantage"
    WARNING = "warning"
    RECOMMENDATION = "recommendation"

class DecisionReason(BaseModel):
    code: str
    message: str
    kind: DecisionReasonKind
    weight: float = 0

class DecisionPolicy(BaseModel):
    fastest_bonus: float = 18
    direct_bonus: float = 14
    availability_bonus: float = 22
    seat_reserve_bonus: float = 10
    balanced_bonus: float = 12
    transfer_penalty: float = 8
    short_transfer_penalty: float = 18
    long_wait_penalty: float = 10
    unavailable_penalty: float = 45
    short_transfer_minutes: int = 45
    long_wait_minutes: int = 180
    good_seat_reserve: int = 6
    group_size: int = Field(default=1, ge=1)

class DecisionSummary(BaseModel):
    route_id: str
    total_duration_minutes: int
    transfer_wait_minutes: int
    transfers_count: int
    has_available_seats: bool
    minimum_available_seats: int
    score: float
    rating: int
    explanation: str
    advantages: list[DecisionReason] = Field(default_factory=list)
    disadvantages: list[DecisionReason] = Field(default_factory=list)
    warnings: list[DecisionReason] = Field(default_factory=list)
    recommendations: list[DecisionReason] = Field(default_factory=list)

class AnalyzeRequest(BaseModel):
    routes: list[RouteOption]
    passengers: int = Field(default=1, ge=1)

class AnalyzeResponse(BaseModel):
    summaries: list[DecisionSummary]
    best_route_id: str | None = None

class CompareRequest(BaseModel):
    left: RouteOption
    right: RouteOption
    passengers: int = Field(default=1, ge=1)

class ComparisonCriterion(BaseModel):
    name: str
    left: str
    right: str
    winner: str | None
    difference: str

class CompareResponse(BaseModel):
    winner_route_id: str | None
    criteria: list[ComparisonCriterion]
    differences: list[str]
    recommendations: list[DecisionReason]
    left_summary: DecisionSummary
    right_summary: DecisionSummary
