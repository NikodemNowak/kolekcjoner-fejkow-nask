"""Common-traits profiles (Task 4b): what a campaign's members share and what they rotate."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Mapping

from fakecollector.core.registry import FEATURES, FeatureSpec
from fakecollector.core.schemas import Campaign, Entity, Tier, Trait
from fakecollector.graph.analyze import Analysis
from fakecollector.graph.entities import EntityLink, entity_type_for

CONSTANT_COVERAGE = 0.8
TIER_ORDER: dict[Tier, int] = {"campaign": 0, "operator": 1, "toolkit": 2, "context": 3}

# Constant traits: why an analyst should care that every member shares this value.
WHY_CONSTANT: dict[str, str] = {
    "KitLanding": (
        "Ten sam identyfikator landingu w panelu kreatora stron: strona wdrożona z jednego konta."
    ),
    "KitTenant": (
        "To samo konto (tenant) w kreatorze stron: wspólny operator, "
        "nawet jeśli historie reklam się różnią."
    ),
    "Tracker": (
        "Ten sam piksel lub tag śledzący: konwersje trafiają na jedno konto reklamowe operatora."
    ),
    "AdParam": "Ten sam parametr reklamy w adresie: ruch z tej samej kampanii reklamowej.",
    "ClickKey": (
        "Ten sam klucz kliknięć trackera: ruch kierowany przez jedno konto "
        "w systemie śledzenia kliknięć."
    ),
    "Asset": "Identyczny plik (sha256) na stronach: skopiowany szablon i te same grafiki.",
    "ImageGroup": "Ten sam obraz (zgodny hash percepcyjny): ponownie użyta kreacja.",
    "Narrative": "Ten sam wzorzec nagłówka pojawia się w kilku zgłoszeniach.",
    "Topic": "Ten sam temat oszustwa: wskazówka kontekstowa, nie dowód.",
    "Host": (
        "Strony łączą się z tym samym hostem zewnętrznym (kolektor danych, tracker): "
        "wspólna infrastruktura operatora."
    ),
    "Endpoint": "Ten sam endpoint zbierający dane: formularze wysyłają dane w jedno miejsce.",
    "RedirectHop": "Ten sam punkt przekierowania: wspólny system dystrybucji ruchu.",
    "UrlSchema": (
        "Ten sam schemat adresu (ścieżka i nazwy parametrów): ten sam zestaw narzędzi lub tracker."
    ),
    "OutlinkDomain": (
        "Linki i formularze prowadzą do tej samej domeny: wspólny cel (sklep, formularz)."
    ),
    "OcrDomain": (
        "Ta sama domena widoczna na obrazach (OCR): może to być podrabiany serwis, "
        "a nie strona docelowa; tylko kontekst."
    ),
    "PathSignature": "Ta sama sygnatura ścieżek: strony zbudowane tym samym zestawem.",
    "Toolkit": (
        "Ten sam plik SDK kreatora stron: wspólne narzędzie, samo w sobie "
        "nie dowodzi tej samej kampanii."
    ),
    "Favicon": "Ta sama ikona strony (favicon): skopiowany szablon lub wspólny operator.",
    "ServerStack": "Ten sam stos serwerowy: słaba wskazówka kontekstowa.",
    "IP": "Ten sam adres IP poza CDN: wspólny serwer operatora.",
    "CertIssuer": "Ten sam wystawca certyfikatu TLS: kontekst, wielu niezwiązanych klientów.",
    "CertSan": "Ta sama nazwa w certyfikacie TLS: domeny obsługiwane jednym certyfikatem.",
    "Brand": "Ta sama marka pojawia się w materiałach.",
    "BrandLogo": "Logo tej samej marki na stronie (np. znaczek „znane z”): tylko kontekst.",
    "Person": "Ten sam wizerunek osoby publicznej: kampania wykorzystuje tę samą twarz.",
    "Advertiser": "Ta sama nazwa reklamodawcy w reklamie: jedno konto reklamowe.",
    "AdvertiserPage": "Ta sama strona reklamodawcy na Facebooku: jedno konto publikuje reklamy.",
    "AdLibraryId": "Ten sam identyfikator w Bibliotece reklam Meta: ta sama reklama.",
    "Domain": "Ta sama domena docelowa: reklamy prowadzą na tę samą stronę.",
    "NameServers": "Ta sama para serwerów nazw: domeny obsługiwane z jednego konta DNS.",
    "ASN": "Ten sam system autonomiczny (hosting): kontekst, wielu niezwiązanych klientów.",
    "Registrar": "Ten sam rejestrator domen: słaba wskazówka kontekstowa.",
}
WHY_CONSTANT_DEFAULT = "Wspólna cecha większości zgłoszeń w kampanii."

# Rotating traits: what the operator changes between ads, and what that means for blocking.
WHY_ROTATING: dict[str, str] = {
    "Domain": (
        "Domeny rotują między reklamami ({values}): blokada jednej domeny nie zatrzyma "
        "kampanii, blokujcie po cechach stałych."
    ),
    "Tracker": (
        "Piksele rotują ({values}): operator używa wielu kont reklamowych, "
        "piksel nie wyznacza granic kampanii."
    ),
    "KitLanding": (
        "Kampania korzysta z kilku landingów kreatora ({values}): strona była "
        "wdrażana wielokrotnie."
    ),
    "KitTenant": "Kilka kont kreatora stron ({values}): kampania rozproszona między konta.",
    "IP": "Adresy IP rotują ({values}): hosting zmienia się między reklamami.",
    "Advertiser": "Nazwy reklamodawców rotują ({values}): wiele kont reklamowych.",
    "AdvertiserPage": "Strony reklamodawców rotują ({values}): wiele kont reklamowych.",
    "Person": "W materiałach kampanii występują różne osoby ({values}).",
    "Narrative": "Różne nagłówki ({values}): operator testuje warianty historii.",
    "Brand": "W materiałach pojawiają się różne marki ({values}).",
}
WHY_ROTATING_DEFAULT = "Wartości tej cechy różnią się między zgłoszeniami ({values})."

# Polish plural forms: (1, 2-4, 5+).
PLURALS: dict[str, tuple[str, str, str]] = {
    "Domain": ("domena", "domeny", "domen"),
    "OcrDomain": ("domena z obrazu", "domeny z obrazów", "domen z obrazów"),
    "ShortLink": ("link skrócony", "linki skrócone", "linków skróconych"),
    "Tracker": ("piksel", "piksele", "pikseli"),
    "KitLanding": ("landing", "landingi", "landingów"),
    "KitTenant": ("konto kreatora", "konta kreatora", "kont kreatora"),
    "AdParam": ("parametr reklamy", "parametry reklamy", "parametrów reklamy"),
    "ClickKey": ("klucz kliknięć", "klucze kliknięć", "kluczy kliknięć"),
    "IP": ("adres IP", "adresy IP", "adresów IP"),
    "Advertiser": ("reklamodawca", "reklamodawcy", "reklamodawców"),
    "AdvertiserPage": ("strona reklamodawcy", "strony reklamodawcy", "stron reklamodawcy"),
    "AdLibraryId": ("reklama w Bibliotece", "reklamy w Bibliotece", "reklam w Bibliotece"),
    "Person": ("osoba", "osoby", "osób"),
    "Brand": ("marka", "marki", "marek"),
    "BrandLogo": ("logo marki", "loga marek", "logo marek"),
    "Narrative": ("nagłówek", "nagłówki", "nagłówków"),
    "NameServers": ("para serwerów nazw", "pary serwerów nazw", "par serwerów nazw"),
    "Favicon": ("favicon", "favicony", "faviconów"),
    "Topic": ("temat", "tematy", "tematów"),
    "ServerStack": ("stos serwerowy", "stosy serwerowe", "stosów serwerowych"),
    "ASN": ("ASN", "ASN", "ASN"),
    "Registrar": ("rejestrator", "rejestratory", "rejestratorów"),
    "CertIssuer": ("wystawca certyfikatu", "wystawcy certyfikatu", "wystawców certyfikatu"),
    "UrlSchema": ("schemat URL", "schematy URL", "schematów URL"),
    "Toolkit": ("SDK", "SDK", "SDK"),
    "Endpoint": ("endpoint", "endpointy", "endpointów"),
}

# Per-image hashes rotate trivially; set-valued types (assets, hosts) are many values per case.
_NOT_ROTATING = {"ImageGroup"}
_MAX_LISTED = 4


def plural(n: int, entity_type: str) -> str:
    """Return a Polish count label such as "5 domen" or "2 piksele"."""
    one, few, many = PLURALS.get(entity_type, ("wartość", "wartości", "wartości"))
    if n == 1:
        word = one
    elif n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        word = few
    else:
        word = many
    return f"{n} {word}"


def _key_types(registry: Mapping[str, FeatureSpec]) -> set[str]:
    """Entity types fed only by single-valued ("key") features."""
    kinds: dict[str, set[str]] = defaultdict(set)
    for name, spec in registry.items():
        entity_type = entity_type_for(name, spec)
        if entity_type is not None:
            kinds[entity_type].add(spec.kind)
    return {t for t, k in kinds.items() if k == {"key"} and t not in _NOT_ROTATING}


def _type_weights(registry: Mapping[str, FeatureSpec]) -> dict[str, float]:
    """Strongest registry weight per entity type, to break lift ties by evidential value."""
    weights: dict[str, float] = defaultdict(float)
    for name, spec in registry.items():
        entity_type = entity_type_for(name, spec)
        if entity_type is not None:
            weights[entity_type] = max(weights[entity_type], spec.weight)
    return weights


def traits(
    campaign: Campaign,
    entities: Collection[Entity],
    links: Collection[EntityLink],
    n_cases: int,
    *,
    limit_per_type: int | None = 10,
    registry: Mapping[str, FeatureSpec] = FEATURES,
) -> list[Trait]:
    """Profile a campaign: constant shared entities first, then rotating entity types.

    Args:
        campaign: The campaign to profile.
        entities: All entities of the run.
        links: All (case, entity, artifact) links of the run.
        n_cases: Number of cases in the run (the corpus for lift).
        limit_per_type: Keep at most this many constant traits per entity type (by lift);
            singletons and asset-heavy campaigns would otherwise list every file.
        registry: Feature registry used to decide which types can rotate.

    Returns:
        Constant traits sorted by tier then lift, followed by rotating traits.
    """
    members = set(campaign.case_ids)
    if not members:
        return []
    size = len(members)
    by_id = {entity.id: entity for entity in entities}
    cases_by_entity: dict[str, set[str]] = defaultdict(set)
    corpus_by_type: dict[str, set[str]] = defaultdict(set)
    for case, entity_id, _ in links:
        entity = by_id.get(entity_id)
        if entity is None:
            continue
        corpus_by_type[entity.type].add(case)
        if case in members:
            cases_by_entity[entity_id].add(case)

    n = max(n_cases, size, 1)
    constant: list[Trait] = []
    values_by_type: dict[str, dict[str, set[str]]] = defaultdict(dict)
    for entity_id, cases in cases_by_entity.items():
        entity = by_id[entity_id]
        if entity.stop:
            continue
        values_by_type[entity.type][entity.value] = cases
        coverage = len(cases) / size
        if coverage >= CONSTANT_COVERAGE:
            constant.append(
                Trait(
                    entity_type=entity.type,
                    value=entity.value,
                    tier=entity.tier,
                    coverage=round(coverage, 4),
                    lift=round(coverage / (max(entity.df, 1) / n), 4),
                    kind="constant",
                    why=WHY_CONSTANT.get(
                        entity.type, WHY_CONSTANT_DEFAULT.format(type=entity.type)
                    ),
                )
            )
    weights = _type_weights(registry)
    constant.sort(
        key=lambda t: (
            TIER_ORDER[t.tier],
            -t.lift,
            -weights.get(t.entity_type, 0.0),
            -t.coverage,
            t.entity_type,
            t.value,
        )
    )
    if limit_per_type is not None:
        kept: dict[str, int] = defaultdict(int)
        trimmed = []
        for trait in constant:
            if kept[trait.entity_type] < limit_per_type:
                kept[trait.entity_type] += 1
                trimmed.append(trait)
        constant = trimmed

    rotating: list[tuple[int, int, Trait]] = []
    tiers = {entity.type: entity.tier for entity in by_id.values()}
    for entity_type in sorted(values_by_type.keys() & _key_types(registry)):
        values = values_by_type[entity_type]
        having = set().union(*values.values())
        top = max(len(cases) for cases in values.values())
        # "Mostly different": several values, none shared by most members, about one per member.
        if (
            len(having) < 2
            or len(values) < 2
            or top / size >= CONSTANT_COVERAGE
            or len(values) * 2 < len(having)
        ):
            continue
        listed = sorted(values, key=lambda v: (-len(values[v]), v))
        shown = ", ".join(listed[:_MAX_LISTED]) + (", …" if len(listed) > _MAX_LISTED else "")
        coverage = len(having) / size
        corpus = len(corpus_by_type[entity_type]) / n
        template = WHY_ROTATING.get(entity_type, WHY_ROTATING_DEFAULT)
        trait = Trait(
            entity_type=entity_type,
            value=plural(len(values), entity_type),
            tier=tiers[entity_type],
            coverage=round(coverage, 4),
            lift=round(coverage / corpus, 4) if corpus else 0.0,
            kind="rotating",
            why=template.format(type=entity_type, values=shown),
        )
        rotating.append((TIER_ORDER[trait.tier], -len(values), trait))
    rotating.sort(key=lambda item: (item[0], item[1], item[2].entity_type))
    return constant + [trait for _, _, trait in rotating]


def rotating_summary(campaign_traits: Collection[Trait]) -> str:
    """Join rotating traits into one line, e.g. "5 domen, 2 piksele"."""
    return ", ".join(t.value for t in campaign_traits if t.kind == "rotating")


def fill_traits(analysis: Analysis, *, limit_per_type: int | None = 10) -> Analysis:
    """Return a copy of the analysis with every campaign's traits filled; ids are unchanged."""
    result = analysis.model_copy(deep=True)
    n = len(result.case_ids)
    for campaign in result.campaigns:
        campaign.traits = traits(
            campaign, result.entities, result.links, n, limit_per_type=limit_per_type
        )
    return result
