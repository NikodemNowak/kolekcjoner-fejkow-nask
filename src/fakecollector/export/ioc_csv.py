"""Flat IOC CSV per campaign (domains, hosts, non-CDN IPs, tracker/kit/advertiser IDs).

Meant for CERT Polska "Lista Ostrzeżeń" triage: `for_warning_list` marks landing domains and
URLs; every row carries a defanged copy for publication next to the raw value.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from collections.abc import Collection
from pathlib import Path
from urllib.parse import urlsplit

from fakecollector.core.schemas import Case
from fakecollector.export._common import campaign_by_case, defang
from fakecollector.graph.analyze import Analysis

# Entity type -> (IOC type, network indicator that needs defanging, warning-list candidate).
IOC_TYPES: dict[str, tuple[str, bool, bool]] = {
    "Domain": ("domain", True, True),
    "OutlinkDomain": ("outlink_domain", True, False),
    "OcrDomain": ("ocr_domain", True, False),
    "ShortLink": ("short_link", True, False),
    "Host": ("hostname", True, False),
    "RedirectHop": ("hostname", True, False),
    "CertSan": ("hostname", True, False),
    "IP": ("ip", True, False),
    "Endpoint": ("endpoint", True, False),
    "Tracker": ("tracker_id", False, False),
    "KitLanding": ("kit_landing_id", False, False),
    "KitTenant": ("kit_tenant_id", False, False),
    "AdParam": ("ad_param", False, False),
    "ClickKey": ("click_key", False, False),
    "Advertiser": ("advertiser_name", False, False),
    "AdvertiserPage": ("advertiser_page", False, False),
    "AdLibraryId": ("ad_library_id", False, False),
}
_ORDER = {
    name: i for i, name in enumerate(["url", *dict.fromkeys(v[0] for v in IOC_TYPES.values())])
}

HEADER = [
    "campaign_id",
    "campaign_label",
    "campaign_size",
    "operator_id",
    "ioc_type",
    "value",
    "value_defanged",
    "tier",
    "case_count",
    "case_ids",
    "for_warning_list",
]


def export_ioc_csv(
    analysis: Analysis, out_dir: Path, cases: Collection[Case] | None = None
) -> Path:
    """Write `iocs.csv`: one row per (campaign, indicator); stop-listed entities are skipped."""
    out_dir.mkdir(parents=True, exist_ok=True)
    by_case = campaign_by_case(analysis)
    entities = {e.id: e for e in analysis.entities if not e.stop and e.type in IOC_TYPES}
    found: dict[tuple[str, str, str], tuple[str, set[str]]] = {}
    for case_id, entity_id, _ in analysis.links:
        entity = entities.get(entity_id)
        campaign = by_case.get(case_id)
        if entity is None or campaign is None:
            continue
        ioc_type = IOC_TYPES[entity.type][0]
        key = (campaign.id, ioc_type, entity.value)
        found.setdefault(key, (entity.tier, set()))[1].add(case_id)
    network = {v[0]: v[1] for v in IOC_TYPES.values()}
    warning = {v[0]: v[2] for v in IOC_TYPES.values()}
    network["url"] = warning["url"] = True
    for case in cases or ():
        campaign = by_case.get(case.id)
        if campaign is None:
            continue
        for url in case.landing_urls:
            if urlsplit(url).hostname:
                found.setdefault((campaign.id, "url", url), ("campaign", set()))[1].add(case.id)

    campaigns = {c.id: c for c in analysis.campaigns}
    rows = []
    grouped: dict[str, list[tuple[str, str, str, set[str]]]] = defaultdict(list)
    for (campaign_id, ioc_type, value), (tier, members) in found.items():
        grouped[campaign_id].append((ioc_type, value, tier, members))
    ranked = sorted(grouped, key=lambda c: (-len(campaigns[c].case_ids), c))
    for campaign_id in ranked:
        campaign = campaigns[campaign_id]
        for ioc_type, value, tier, members in sorted(
            grouped[campaign_id], key=lambda r: (_ORDER[r[0]], r[1])
        ):
            rows.append(
                [
                    campaign.id,
                    campaign.label,
                    len(campaign.case_ids),
                    campaign.operator_id or "",
                    ioc_type,
                    value,
                    defang(value) if network[ioc_type] else value,
                    tier,
                    len(members),
                    "|".join(sorted(members)),
                    str(warning[ioc_type]).lower(),
                ]
            )
    path = out_dir / "iocs.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        writer.writerows(rows)
    return path
