from pydantic import BaseModel, Field


class TickerSentiment(BaseModel):
    ticker: str = Field(
        description="The stock ticker symbol discussed in the article. Should correspond to a ticker in the covered list."
    )
    score: float = Field(
        ge=-1.0,
        le=1.0,
        description="Sentiment score for this ticker based on news-coverage tone, from -1.0 (very negative) to 1.0 (very positive).",
    )


class ConceptSentiment(BaseModel):
    concept: str = Field(
        description="The macro or sector concept discussed in the article. Should correspond to a concept in the covered taxonomy."
    )
    score: float = Field(
        ge=-1.0,
        le=1.0,
        description="Sentiment score for this concept based on news-coverage tone, from -1.0 (very negative) to 1.0 (very positive).",
    )


class ExtractionOutput(BaseModel):
    ticker_sentiments: list[TickerSentiment] = Field(
        description="One entry per covered ticker discussed in the article. Return an empty list if no covered ticker is discussed."
    )
    concept_sentiments: list[ConceptSentiment] = Field(
        description="One entry per covered macro/sector concept discussed in the article. Return an empty list if no covered concept is discussed."
    )
    ai_confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Your confidence in the overall correctness of this extraction, from 0.0 (not confident) to 1.0 (very confident).",
    )
