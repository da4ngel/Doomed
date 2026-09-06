"""Model output is a proposal: source references must validate before becoming claims."""

from pydantic import Field

from src.api.schemas import Frozen


class SourceQuote(Frozen):
    chunk_id: str
    quote: str = Field(min_length=1, max_length=12000)


class ProposedClaim(Frozen):
    text: str = Field(min_length=1, max_length=12000)
    sources: list[SourceQuote] = Field(min_length=1, max_length=12)
    asset_ids: list[str] = Field(default_factory=list, max_length=4)
    confidence: float = Field(default=0.6, ge=0, le=1)


class Draft(Frozen):
    claims: list[ProposedClaim] = Field(default_factory=list, max_length=20)
    missing_information: list[str] = Field(default_factory=list, max_length=20)
