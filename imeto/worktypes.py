"""Typy wytworów naukowych. Człowiek wybiera typ przy imporcie; typ decyduje o
klasie FaBiO źródła oraz o tym, który skill ekstrakcji (`knowledge/extraction/<typ>.md`)
zostanie doklejony do promptu."""

from enum import StrEnum


class WorkType(StrEnum):
    article = "article"
    report = "report"
    proposal = "proposal"


# typ wytworu -> klasa FaBiO (URI), zapisywana jako Source.fabio_type
FABIO: dict[WorkType, str] = {
    WorkType.article: "http://purl.org/spar/fabio/JournalArticle",
    WorkType.report: "http://purl.org/spar/fabio/Report",
    WorkType.proposal: "http://purl.org/spar/fabio/ResearchProposal",
}
