"""LinkedIn : stub documenté. Les statistiques de posts (organizationalEntityShareStatistics pour
une page, memberCreatorPostAnalytics pour un profil) sont réservées à la Marketing API (programme
partenaire Community Management) : rien n'est relevé, la source journalise « non disponible »."""

from __future__ import annotations

from .base import PublishedItem, PullContext, SourceResult


class LinkedInMetricsSource:
    platform = "linkedin"

    def fetch(self, ctx: PullContext, items: list[PublishedItem]) -> SourceResult:
        return SourceResult(
            available=False,
            notes=[
                f"LinkedIn : non disponible ({len(items)} post(s) ignoré(s)) — les statistiques "
                "de posts sont réservées à la Marketing API (accès partenaire Community "
                "Management) ; relever à la main dans l'onglet Statistiques si besoin"
            ],
        )
