"""Feature registry (Task 0): the only place feature names are defined.

Adding a signal = one extractor + one row here. Weights and caps are starting values;
workstream C calibrates them in Task 8.
"""

from __future__ import annotations

from dataclasses import KW_ONLY, dataclass
from typing import Literal

from fakecollector.core.schemas import Family, Tier


@dataclass(frozen=True)
class FeatureSpec:
    """How a feature takes part in the entity graph and fusion."""

    family: Family
    tier: Tier
    entity_type: str | None  # None = vector/similarity-only or informational feature
    weight: float  # probability contribution when shared, 0..1 (0 = never evidence alone)
    max_df: float  # document-frequency cap as a share of cases

    _: KW_ONLY
    kind: Literal["key", "set", "minhash", "vector", "hash", "fuzzy", "info"] = "key"
    lo: float | None = None
    hi: float | None = None
    detail_pl: str = "Wspólna cecha {kind}: {value}"
    source: str | None = None  # kind "fuzzy": the feature whose values are compared


IMAGE_HASH_IDENTICAL_DETAIL = "Identyczny skrót obrazu (odległość {value})"
IMAGE_HASH_SIMILAR_DETAIL = "Podobny skrót obrazu (odległość {value})"

FEATURES: dict[str, FeatureSpec] = {
    # Row 1: kit and tracker IDs (A). Tenant and trackers link operators, not campaigns.
    "ids.kit_landing": FeatureSpec(
        "ids",
        "campaign",
        "KitLanding",
        0.97,
        0.3,
        kind="key",
        detail_pl="Wspólny identyfikator strony zestawu: {value}",
    ),
    "ids.kit_tenant": FeatureSpec(
        "ids",
        "operator",
        "KitTenant",
        0.4,
        0.5,
        kind="key",
        detail_pl="Wspólne konto w zestawie stron: {value} ({df}/{n} zgłoszeń)",
    ),
    # Keep a shared pixel active even in a small operator-focused batch.
    "ids.fb_pixel": FeatureSpec(
        "ids",
        "operator",
        "Tracker",
        0.4,
        1.0,
        kind="key",
        detail_pl="Wspólny piksel Meta: {value} ({df}/{n} zgłoszeń)",
    ),
    "ids.gtag": FeatureSpec(
        "ids",
        "operator",
        "Tracker",
        0.4,
        0.3,
        kind="key",
        detail_pl="Wspólny identyfikator Google Tag: {value} ({df}/{n} zgłoszeń)",
    ),
    "ids.ad_param": FeatureSpec(
        "ids",
        "campaign",
        "AdParam",
        0.8,
        0.2,
        kind="key",
        detail_pl="Wspólny parametr reklamy: {value} ({df}/{n} zgłoszeń)",
    ),
    "ids.click_key": FeatureSpec(
        "ids",
        "campaign",
        "ClickKey",
        0.8,
        0.2,
        kind="key",
        detail_pl="Wspólny klucz kliknięcia: {value} ({df}/{n} zgłoszeń)",
    ),
    # Row 2: shared file hashes (A).
    "asset.sha256": FeatureSpec(
        "asset",
        "campaign",
        "Asset",
        0.9,
        0.3,
        kind="set",
        lo=0.15,
        hi=0.6,
        detail_pl="Wspólny plik SHA-256: {value} (pokrycie zasobów {sim:.0%})",
    ),
    # Row 3 and 8: text (C); text.raw / html.title are inputs for C, not evidence.
    "text.raw": FeatureSpec(
        "text",
        "campaign",
        None,
        0.0,
        1.0,
        kind="info",
        detail_pl="",
    ),
    "html.title": FeatureSpec(
        "text",
        "campaign",
        None,
        0.0,
        1.0,
        kind="info",
        detail_pl="",
    ),
    "text.minhash": FeatureSpec(
        "text",
        "campaign",
        None,
        0.85,
        1.0,
        kind="minhash",
        lo=0.3,
        hi=0.7,
        detail_pl="Podobny fragment tekstu (podobieństwo {sim:.0%})",
    ),
    "text.headline_tpl": FeatureSpec(
        "text",
        "campaign",
        "Narrative",
        0.6,
        0.3,
        kind="key",
        detail_pl="Wspólny wzorzec nagłówka: {value}",
    ),
    # Fuzzy twin of the exact template key: a re-worded or OCR-garbled copy of a known
    # headline (token-set ratio of the {PERSON}-masked templates, graph/signals.py). Never a
    # feature row itself; the threshold is EdgeConfig.headline_fuzzy_threshold.
    "text.headline_fuzzy": FeatureSpec(
        "text",
        "campaign",
        None,
        0.6,
        1.0,
        kind="fuzzy",
        source="text.headline_tpl",
        detail_pl="Zbliżony nagłówek (podobieństwo {sim:.0%}): {value}",
    ),
    "text.bge": FeatureSpec(
        "text",
        "campaign",
        None,
        0.5,
        1.0,
        kind="vector",
        detail_pl="Podobne znaczenie tekstu (podobieństwo {sim:.0%})",
    ),
    "text.topic": FeatureSpec(
        "text",
        "context",
        "Topic",
        0.1,
        1.0,
        kind="key",
        detail_pl="Wspólny temat tekstu: {value} ({df}/{n} zgłoszeń)",
    ),
    # Row 4: request graph (A).
    "infra.host_3p": FeatureSpec(
        "infra",
        "operator",
        "Host",
        0.4,
        0.3,
        kind="set",
        detail_pl="Wspólny host zewnętrzny: {value} (pokrycie hostów {sim:.0%})",
    ),
    "infra.endpoint": FeatureSpec(
        "infra",
        "operator",
        "Endpoint",
        0.4,
        0.3,
        kind="key",
        detail_pl="Wspólny punkt odbioru danych: {value} ({df}/{n} zgłoszeń)",
    ),
    "infra.redirect_hop": FeatureSpec(
        "infra",
        "operator",
        "Host",
        0.4,
        0.3,
        kind="set",
        detail_pl="Wspólny etap przekierowania: {value} (pokrycie {sim:.0%})",
    ),
    "url.schema": FeatureSpec(
        "infra",
        "toolkit",
        "UrlSchema",
        0.25,
        0.5,
        kind="key",
        detail_pl="Wspólny schemat adresu URL: {value} ({df}/{n} zgłoszeń)",
    ),
    "url.outlink_domain": FeatureSpec(
        "infra",
        "operator",
        "Domain",
        0.4,
        0.3,
        kind="set",
        detail_pl="Wspólna domena docelowa odnośnika: {value} (pokrycie {sim:.0%})",
    ),
    # Row 5: page structure (A).
    "html.dom_minhash": FeatureSpec(
        "template",
        "toolkit",
        None,
        0.5,
        1.0,
        kind="minhash",
        lo=0.5,
        hi=0.9,
        detail_pl="Podobna struktura HTML (podobieństwo {sim:.0%})",
    ),
    "html.css_minhash": FeatureSpec(
        "template",
        "toolkit",
        None,
        0.5,
        1.0,
        kind="minhash",
        lo=0.5,
        hi=0.9,
        detail_pl="Podobne klasy CSS (podobieństwo {sim:.0%})",
    ),
    "kit.path_sig": FeatureSpec(
        "template",
        "toolkit",
        "PathSignature",
        0.25,
        0.5,
        kind="set",
        detail_pl="Wspólna sygnatura ścieżki: {value} (pokrycie {sim:.0%})",
    ),
    "kit.sdk": FeatureSpec(
        "template",
        "toolkit",
        "Toolkit",
        0.25,
        1.0,
        kind="key",
        detail_pl="Wspólny plik zestawu narzędzi: {value} ({df}/{n} zgłoszeń)",
    ),
    # A1 (plan v2): a third-party host the page only downloads code from (GET of a script,
    # style or font, never data sent to it) is a dependency of the kit, not an operator.
    "kit.dep_host": FeatureSpec(
        "infra",
        "toolkit",
        "DependencyHost",
        0.25,
        1.0,
        kind="key",
        detail_pl="Wspólna zewnętrzna biblioteka zestawu z hosta: {value} ({df}/{n} spraw)",
    ),
    # Row 11: infrastructure metadata (A).
    "infra.favicon_mmh3": FeatureSpec(
        "infra",
        "operator",
        "Favicon",
        0.4,
        0.3,
        kind="key",
        detail_pl="Wspólna sygnatura ikony witryny: {value} ({df}/{n} zgłoszeń)",
    ),
    "infra.server_stack": FeatureSpec(
        "infra",
        "context",
        "ServerStack",
        0.25,
        1.0,
        kind="key",
        detail_pl="Wspólny zestaw technologii serwera: {value} ({df}/{n} zgłoszeń)",
    ),
    "infra.ip": FeatureSpec(
        "infra",
        "operator",
        "IP",
        0.25,
        0.3,
        kind="key",
        detail_pl="Wspólny adres IP: {value} ({df}/{n} zgłoszeń)",
    ),
    "infra.cert_issuer": FeatureSpec(
        "infra",
        "context",
        "CertIssuer",
        0.1,
        1.0,
        kind="key",
        detail_pl="Wspólny wystawca certyfikatu: {value} ({df}/{n} zgłoszeń)",
    ),
    "infra.cert_san": FeatureSpec(
        "infra",
        "operator",
        "CertSan",
        0.4,
        0.3,
        kind="set",
        detail_pl="Wspólna nazwa w certyfikacie: {value} (pokrycie {sim:.0%})",
    ),
    # Rows 6, 7, 9, 10: vision, faces, OCR, video (B; copied from PR #4 unchanged).
    "img.phash": FeatureSpec(
        "image",
        "campaign",
        None,
        0.8,
        0.3,
        kind="hash",
        lo=0.86,
        hi=0.97,
        detail_pl=IMAGE_HASH_SIMILAR_DETAIL,
    ),
    "img.pdq": FeatureSpec(
        "image",
        "campaign",
        None,
        0.8,
        0.3,
        kind="hash",
        lo=0.85,
        hi=0.95,
        detail_pl=IMAGE_HASH_SIMILAR_DETAIL,
    ),
    "img.siglip": FeatureSpec(
        "image",
        "campaign",
        None,
        0.45,
        1.0,
        kind="vector",
        detail_pl="Podobna treść obrazu (podobieństwo {sim:.0%})",
    ),
    # Area share of the largest detected face (any face, matched or not; geometry only, no
    # identity): gates SigLIP comparisons of portrait-like images (graph/signals.py).
    "img.face_share": FeatureSpec("image", "context", None, 0.0, 1.0, kind="info", detail_pl=""),
    "brand.impersonated": FeatureSpec(
        "person",
        "context",
        "Brand",
        0.35,
        0.5,
        kind="key",
        detail_pl="Wspólna marka w materiałach: {value} ({df}/{n} zgłoszeń)",
    ),
    # A brand logo that may be an "as seen on" trust badge: unrelated landers share them.
    "brand.logo": FeatureSpec(
        "person",
        "context",
        "BrandLogo",
        0.1,
        0.5,
        kind="key",
        detail_pl="Logo tej samej marki na stronie: {value} (kontekst, {df}/{n} zgłoszeń)",
    ),
    "person.public_figure": FeatureSpec(
        "person",
        "context",
        "Person",
        0.35,
        0.5,
        kind="key",
        detail_pl="Wspólna osoba publiczna: {value} ({df}/{n} zgłoszeń)",
    ),
    # A public figure named in the text (extractors/person_text.py). Informational only:
    # one celebrity is reused by many unrelated campaigns, so a name never links cases.
    "person.mentioned": FeatureSpec("person", "context", None, 0.0, 1.0, kind="info", detail_pl=""),
    "text.ocr": FeatureSpec(
        "text",
        "campaign",
        None,
        0.0,
        1.0,
        kind="info",
        detail_pl="",
    ),
    "text.asr": FeatureSpec(
        "text",
        "campaign",
        None,
        0.0,
        1.0,
        kind="info",
        detail_pl="",
    ),
    # Title-like OCR line (extractors/ocr.py); input to text.headline_tpl, never evidence.
    "ocr.headline": FeatureSpec(
        "text",
        "campaign",
        None,
        0.0,
        1.0,
        kind="info",
        detail_pl="",
    ),
    "ad.advertiser": FeatureSpec(
        "ids",
        "operator",
        "Advertiser",
        0.4,
        0.3,
        kind="key",
        detail_pl="Wspólna nazwa reklamodawcy: {value} ({df}/{n} zgłoszeń)",
    ),
    "ids.ad_library": FeatureSpec(
        "ids",
        "campaign",
        "AdLibraryId",
        0.97,
        0.1,
        kind="key",
        detail_pl="Wspólny identyfikator reklamy w bibliotece: {value}",
    ),
    "ids.advertiser_page": FeatureSpec(
        "ids",
        "operator",
        "AdvertiserPage",
        0.4,
        0.3,
        kind="key",
        detail_pl="Wspólny identyfikator strony reklamodawcy: {value} ({df}/{n} zgłoszeń)",
    ),
    # Publisher facts about a public case (extractors/source_meta.py), in their own family:
    # screenshot-only public cases must not raise the document-frequency base of the
    # capture families (ids/infra), or a shared organizer kit would stop looking common.
    # A full short link is one campaign's link; a phone, bank account or messenger handle
    # is the operator's.
    "ids.short_link": FeatureSpec(
        "meta", "campaign", "ShortLink", 0.9, 0.1, detail_pl="Ten sam skrócony link: {value}"
    ),
    "ids.phone": FeatureSpec(
        "meta",
        "operator",
        "Phone",
        0.4,
        0.1,
        detail_pl="Ten sam numer telefonu: {value} ({df}/{n} zgłoszeń)",
    ),
    "ids.bank_account": FeatureSpec(
        "meta",
        "operator",
        "BankAccount",
        0.6,
        0.1,
        detail_pl="Ten sam numer konta: {value} ({df}/{n} zgłoszeń)",
    ),
    "ids.messenger": FeatureSpec(
        "meta",
        "operator",
        "Messenger",
        0.4,
        0.1,
        detail_pl="To samo konto w komunikatorze: {value} ({df}/{n} zgłoszeń)",
    ),
    # Passive lookups cached with a public case (same tiers as the opt-in infra.* rows:
    # a name-server pair or a small certificate is an operator trace, the rest is context).
    "meta.ns": FeatureSpec(
        "meta",
        "operator",
        "NameServers",
        0.4,
        0.3,
        detail_pl="Ta sama para serwerów nazw: {value} ({df}/{n} zgłoszeń)",
    ),
    "meta.cert_san": FeatureSpec(
        "meta",
        "operator",
        "CertSan",
        0.4,
        0.3,
        kind="set",
        detail_pl="Wspólna nazwa w certyfikacie: {value} (pokrycie {sim:.0%})",
    ),
    "meta.ip": FeatureSpec(
        "meta",
        "operator",
        "IP",
        0.25,
        0.3,
        detail_pl="Wspólny adres IP: {value} ({df}/{n} zgłoszeń)",
    ),
    "meta.asn": FeatureSpec(
        "meta",
        "context",
        "ASN",
        0.2,
        0.5,
        detail_pl="Wspólny system autonomiczny: {value} ({df}/{n} zgłoszeń)",
    ),
    "meta.registrar": FeatureSpec(
        "meta",
        "context",
        "Registrar",
        0.1,
        1.0,
        detail_pl="Ten sam rejestrator domeny: {value} ({df}/{n} zgłoszeń)",
    ),
    "meta.cert_issuer": FeatureSpec(
        "meta",
        "context",
        "CertIssuer",
        0.1,
        1.0,
        detail_pl="Wspólny wystawca certyfikatu: {value} ({df}/{n} zgłoszeń)",
    ),
    # The publisher's own labels: shown, never evidence (they are the story labels).
    **{
        name: FeatureSpec("meta", "context", None, 0.0, 1.0, kind="info", detail_pl="")
        for name in (
            "meta.registered",
            "meta.platform",
            "meta.ad_date",
            "meta.person",
            "meta.brand",
            "meta.narrative",
            "meta.cert_pl_listed",
        )
    },
    "url.domain": FeatureSpec(
        "ids", "campaign", "Domain", 0.9, 0.3, detail_pl="Wspólna domena: {value}"
    ),
    # A domain printed in a screenshot or ad (OCR) may be the imitated portal, not the
    # landing: context only, and its own graph type (OcrDomain) so it never joins url.domain.
    "ocr.domain": FeatureSpec(
        "ids",
        "context",
        "Domain",
        0.2,
        0.3,
        kind="key",
        detail_pl="Ta sama domena widoczna na obrazie (OCR): {value} ({df}/{n} zgłoszeń)",
    ),
    # A "host/token" short link typed in an ad: an exact generated token is as specific as
    # an ad parameter, so it is campaign evidence; the DF cap drops a shared shortener page.
    "ocr.short_link": FeatureSpec(
        "ids",
        "campaign",
        "ShortLink",
        0.8,
        0.2,
        kind="key",
        detail_pl="Ten sam link skrócony widoczny na obrazie: {value} ({df}/{n} zgłoszeń)",
    ),
    # Feed-ad layout read from a screenshot: shown on the case page, never evidence
    # (every ad has a button and many pages share a category).
    "ad.sponsored": FeatureSpec("ids", "context", None, 0.0, 1.0, kind="info", detail_pl=""),
    "ad.cta": FeatureSpec("ids", "context", None, 0.0, 1.0, kind="info", detail_pl=""),
    "ad.page_category": FeatureSpec("ids", "context", None, 0.0, 1.0, kind="info", detail_pl=""),
    "ad.card_domain": FeatureSpec("ids", "context", None, 0.0, 1.0, kind="info", detail_pl=""),
    # Task 3 [S1] opt-in public metadata (rows match PR #14, enrich/): a per-account NS pair
    # is an operator trace; ASN, registrar and registration month are context (hosters are hubs).
    "infra.ns": FeatureSpec(
        "infra",
        "operator",
        "NameServers",
        0.4,
        0.3,
        kind="key",
        detail_pl="Ta sama para serwerów nazw: {value} ({df}/{n} zgłoszeń)",
    ),
    "infra.asn": FeatureSpec(
        "infra",
        "context",
        "ASN",
        0.2,
        0.5,
        kind="key",
        detail_pl="Wspólny system autonomiczny: {value} ({df}/{n} zgłoszeń)",
    ),
    "infra.registrar": FeatureSpec(
        "infra",
        "context",
        "Registrar",
        0.1,
        1.0,
        kind="key",
        detail_pl="Ten sam rejestrator domeny: {value} ({df}/{n} zgłoszeń)",
    ),
    "infra.registered": FeatureSpec("infra", "context", None, 0.0, 1.0, kind="info"),
    "text.lang": FeatureSpec(
        "text",
        "context",
        None,
        0.0,
        1.0,
        kind="info",
        detail_pl="",
    ),
}
