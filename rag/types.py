from dataclasses import dataclass, field
from pydantic import BaseModel, Field, ConfigDict


@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str
    version: str
    mime_type: str
    url: str
    size: int = 0
    source_kind: str = "drive"
    source_group: str | None = None


@dataclass(frozen=True)
class WebsiteSource:
    id: str
    start_url: str
    max_pages: int
    enabled: bool = True


@dataclass(frozen=True)
class WebsitePage:
    file: DriveFile
    text: str


@dataclass
class Chunk:
    text: str
    metadata: dict = field(default_factory=dict)


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: int
    file_id: str
    file_name: str
    version: str
    url: str
    text: str
    page: int | None = None
    score: float


class AnswerDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(min_length=1, max_length=6000)
    citation_ids: list[int] = Field(
        max_length=5,
        description="Numbers of evidence passages used for the answer. Empty only when the documents cannot answer the question.",
    )


class SearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=1200)


@dataclass
class Answer:
    text: str
    sources: list[Source]
    search_query: str
    timings: dict[str, float] = field(default_factory=dict)
