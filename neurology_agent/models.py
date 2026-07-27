from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Publication:
    title: str
    url: str
    doi: Optional[str] = None
    journal: str = "Neurology"
    article_type: str = "article"
    published: Optional[str] = None
    abstract: str = ""
    pmid: Optional[str] = None
    pmid_source: str = "none"
    pdf_url: Optional[str] = None
    local_pdf: Optional[str] = None
    audio_url: Optional[str] = None
    is_podcast: bool = False


@dataclass
class ReviewResult:
    publication: Publication
    review: str = ""
    error: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0


@dataclass
class RunStats:
    discovered: int = 0
    processed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
