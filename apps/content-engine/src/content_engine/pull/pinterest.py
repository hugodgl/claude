"""Pinterest API v5 : GET /v5/pins/{pin_id}/analytics (IMPRESSION, PIN_CLICK, OUTBOUND_CLICK, SAVE).

Une épingle n'a pas de « vues » : on stocke les impressions dans `views` (et `impressions`), les
clics sortants dans `clicks`, les enregistrements (SAVE) dans `shares`, le CTR sortant dans `ctr`
et les clics sur l'épingle (PIN_CLICK) dans `extra_json`. Les métriques « lifetime » sont
préférées quand l'API les renvoie, sinon le cumul de la fenêtre (90 jours au plus)."""

from __future__ import annotations

from datetime import timedelta

from ..publish.base import require_token
from .base import (
    PublishedItem,
    PullContext,
    Snapshot,
    SourceResult,
    http_error,
    to_int,
)

METRIC_TYPES = "IMPRESSION,PIN_CLICK,OUTBOUND_CLICK,SAVE"
MAX_WINDOW_DAYS = 90  # l'API refuse une date de début à plus de 90 jours


def pin_metrics(data: dict) -> tuple[dict, str]:
    """Extrait les compteurs d'une réponse pins/analytics : `all.lifetime_metrics` de préférence,
    sinon `summary_metrics`, sinon la somme des `daily_metrics`. Retourne (compteurs, portée)."""
    block = data.get("all") if isinstance(data, dict) else None
    if not isinstance(block, dict):
        block = next((v for v in (data or {}).values() if isinstance(v, dict)), {})
    for key, scope in (("lifetime_metrics", "lifetime"), ("summary_metrics", "window")):
        if isinstance(block.get(key), dict) and block[key]:
            return block[key], scope
    total: dict[str, float] = {}
    for day in block.get("daily_metrics") or []:
        for k, v in (day.get("metrics") or {}).items():
            total[k] = total.get(k, 0) + (v or 0)
    return total, "window"


class PinterestMetricsSource:
    platform = "pinterest"

    def fetch(self, ctx: PullContext, items: list[PublishedItem]) -> SourceResult:
        s = ctx.settings
        token = require_token(s.pinterest_access_token, "PINTEREST_ACCESS_TOKEN")
        headers = {"Authorization": f"Bearer {token}"}
        start = max(ctx.start, ctx.end - timedelta(days=MAX_WINDOW_DAYS))
        res = SourceResult()
        for it in items:
            r = ctx.client.get(
                f"{s.pinterest_api_base}/v5/pins/{it.remote_id}/analytics",
                params={
                    "start_date": start.isoformat(),
                    "end_date": ctx.end.isoformat(),
                    "metric_types": METRIC_TYPES,
                },
                headers=headers,
            )
            if r.status_code in (401, 429):  # jeton invalide ou quota : inutile d'insister
                raise http_error("Pinterest", r)
            if r.status_code >= 400:  # épingle supprimée, trop récente… : on passe à la suivante
                res.notes.append(
                    f"Pinterest : épingle {it.remote_id} (brouillon #{it.draft_id}) : "
                    f"HTTP {r.status_code} — {r.text[:120]}"
                )
                continue
            metrics, scope = pin_metrics(r.json())
            impressions = to_int(metrics.get("IMPRESSION"))
            outbound = to_int(metrics.get("OUTBOUND_CLICK"))
            res.snapshots.append(
                Snapshot(
                    item=it,
                    views=impressions,
                    shares=to_int(metrics.get("SAVE")),
                    impressions=impressions,
                    clicks=outbound,
                    ctr=round(100 * outbound / impressions, 2) if impressions else None,
                    extra={
                        "PIN_CLICK": to_int(metrics.get("PIN_CLICK")),
                        "scope": scope,
                        "window": [start.isoformat(), ctx.end.isoformat()],
                    },
                )
            )
        return res
