from pydantic import BaseModel, Field

from backend.core.enums import Concept, Ticker


class TickerSentiment(BaseModel):
    ticker: Ticker
    score: float = Field(ge=-1.0, le=1.0)


class ConceptSentiment(BaseModel):
    concept: Concept
    score: float = Field(ge=-1.0, le=1.0)

class AIResponse(BaseModel):
    ticker_sentiments: list[TickerSentiment] = Field(default_factory=list)
    concept_sentiments: list[ConceptSentiment] = Field(default_factory=list)
    ai_confidence: float = Field(ge=0.0, le=1.0)
    model_version: str
    prompt_version: str


class AggregatedAnalysis(BaseModel):
    ticker_sentiments: list[TickerSentiment] = Field(default_factory=list)
    concept_sentiments: list[ConceptSentiment] = Field(default_factory=list)
