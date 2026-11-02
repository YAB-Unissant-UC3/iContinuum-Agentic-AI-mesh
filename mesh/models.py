from dataclasses import dataclass, field


@dataclass(frozen=True)
class Document:
    id: str
    text: str
    allowed_roles: frozenset[str]


@dataclass(frozen=True)
class Passage:
    document_id: str
    number: int
    text: str


@dataclass(frozen=True)
class Citation:
    document_id: str
    passage: int
    quote: str


@dataclass(frozen=True)
class Finding:
    claim: str
    citations: tuple[Citation, ...]


@dataclass
class Analysis:
    findings: list[Finding] = field(default_factory=list)
    unmet_requirements: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AuditResult:
    passed: bool
    issues: tuple[str, ...]
