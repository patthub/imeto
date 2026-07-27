"""Scholarly work types. A human picks the type at import; the type decides the
source's FaBiO class and which extraction skill (`knowledge/extraction/<type>.md`)
gets appended to the prompt."""

from enum import StrEnum


class WorkType(StrEnum):
    article = "article"
    report = "report"
    proposal = "proposal"
    book = "book"
    poster = "poster"
    presentation = "presentation"


# work type -> FaBiO class (URI), stored as Source.fabio_type
FABIO: dict[WorkType, str] = {
    WorkType.article: "http://purl.org/spar/fabio/JournalArticle",
    WorkType.report: "http://purl.org/spar/fabio/Report",
    WorkType.proposal: "http://purl.org/spar/fabio/ResearchProposal",
    WorkType.book: "http://purl.org/spar/fabio/Book",
    WorkType.poster: "http://purl.org/spar/fabio/ConferencePoster",
    WorkType.presentation: "http://purl.org/spar/fabio/Presentation",
}
