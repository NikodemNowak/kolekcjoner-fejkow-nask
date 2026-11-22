"""Polish copy returned by the web API (AGENTS.md §1: UI strings live in one module)."""

from __future__ import annotations

from fakecollector.app.pl import ENTITY_KIND, FAMILY_NAMES

# What a shared trace is worth, in words a newcomer understands.
REPORT_TIERS = {
    "campaign": "Ta sama kampania",
    "operator": "Ten sam sprawca",
    "toolkit": "Ten sam program do stron",
    "context": "Kontekst",
}
# The profile says "landing"; the UI says "strona w kreatorze".
PLAIN_WORDS = {
    "landingów": "stron w kreatorze",
    "landingi": "strony w kreatorze",
    "landing": "strona w kreatorze",
    "stosy serwerowe": "rodzaje serwera",
    "stosów serwerowych": "rodzajów serwera",
}

CORPUS_NAMES = {
    "nask_backup": "Kopia NASK",
    "nask_mentor": "Materiały mentora",
    "upload": "Przesłane",
    "U": "Przesłane",
    "fixtures": "Dane testowe",
    "zrodla_publiczne": "Źródła publiczne",
    "collector": "Zbieracz",
}

ENTITY_TYPES: dict[str, str] = {
    **ENTITY_KIND,
    "AdParam": "Parametr reklamy",
    "ClickKey": "Klucz kliknięć",
    "Narrative": "Nagłówek",
    "Topic": "Temat",
    "UrlSchema": "Schemat adresu",
    "OutlinkDomain": "Domena docelowa linków",
    "OcrDomain": "Domena widoczna na obrazie",
    "ShortLink": "Link skrócony",
    "Toolkit": "Plik SDK kreatora",
    "DependencyHost": "Biblioteka zewnętrzna",
    "Favicon": "Ikona strony",
    "ServerStack": "Serwer",
    "CertIssuer": "Wystawca certyfikatu",
    "CertSan": "Nazwa w certyfikacie",
    "BrandLogo": "Logo marki",
    "Advertiser": "Reklamodawca",
    "AdvertiserPage": "Strona reklamodawcy",
    "AdLibraryId": "Biblioteka reklam Meta",
    "Phone": "Numer telefonu",
    "BankAccount": "Numer konta",
    "Messenger": "Konto w komunikatorze",
    "ImageGroup": "Grupa obrazów",
    "RedirectHop": "Przekierowanie",
    "NameServers": "Serwery nazw",
    "ASN": "Hosting (ASN)",
    "Registrar": "Rejestrator",
    "Asset": "Plik",
    "KitLanding": "Strona w kreatorze stron",
    "KitTenant": "Konto w kreatorze stron",
    "Tracker": "Piksel śledzący",
    "Endpoint": "Adres zbierania danych",
    "PathSignature": "Wzorzec ścieżki plików",
}

ASSET_PLURAL = ("wspólny plik", "wspólne pliki", "wspólnych plików")
# Polish noun forms for counts: (1, 2-4, 5+).
REPORTS = ("zgłoszenie", "zgłoszenia", "zgłoszeń")
REPORTS_LOCATIVE = ("zgłoszeniu", "zgłoszeniach", "zgłoszeniach")
POSSIBLE_PAIRS = ("możliwej pary", "możliwych par", "możliwych par")
IDENTICAL_FILES = ("identyczny plik", "identyczne pliki", "identycznych plików")
IDENTICAL_FILES_INSTR = ("identycznym plikiem", "identycznymi plikami", "identycznymi plikami")
IN_REPORTS = "w {count} bazy"
WHY_LINKED = (
    "{reports} łączy {linked} z {pairs} powiązań. Najsilniejsze rodziny dowodów: {families}."
)

# "Dlaczego to jedna kampania": sentences built from the strongest evidence.
STORY_BOTH = "obie prowadzą"
STORY_ALL = "wszystkie ({count}) prowadzą"
AT_LEAST = "co najmniej "
STORY_TEXT = "tekstem zgodnym w {prefix}{percent}%"
STORY_TEXT_IDENTICAL = "identycznym tekstem"
STORY_LEAD_DIFFERENT = "Różne reklamy, ta sama strona docelowa: {who} na strony z {traces}."
STORY_LEAD_SAME = "Ta sama strona docelowa: {who} na strony z {traces}."
STORY_LEAD_IDS = "Zgłoszenia mają {traces}."
STORY_LEAD_OTHER = "Zgłoszenia łączy: {traces}."
STORY_CREATIVES_DIFFERENT = (
    "Kreacje reklamowe są różne. To typowa rotacja: oszuści wymieniają obraz i nagłówek "
    "reklamy, a stronę docelową zostawiają bez zmian."
)
STORY_CREATIVES_MIXED = (
    "Część kreacji reklamowych się powtarza, część jest inna. To typowa rotacja: reklama "
    "się zmienia, strona docelowa zostaje."
)
STORY_CREATIVES_SAME = "Kreacje reklamowe też się powtarzają: ten sam obraz w kilku zgłoszeniach."
STORY_IDS_EXTRA = "Dodatkowo mają {traces}."
STORY_ROTATING = "Zmienia się: {values}."
STORY_IDS = {
    "ids.kit_landing": "tę samą stronę w kreatorze stron",
    "ids.kit_tenant": "to samo konto w kreatorze stron",
    "ids.fb_pixel": "ten sam piksel Meta",
    "ids.gtag": "ten sam tag Google",
    "ids.advertiser_page": "tę samą stronę reklamodawcy",
}
# Plain-language lines for newcomers (overview rows, campaign verdict, side-by-side rows).
ADS = ("reklama", "reklamy", "reklam")
DIFFERENT_DOMAINS = ("adres strony", "różne adresy stron", "różnych adresów stron")
SAME_FILES = ("ten sam plik", "te same pliki", "tych samych plików")
PLAIN_SINGLE = "Pojedyncza reklama, na razie bez mocnych powiązań z innymi"
PLAIN_SAME_KIT_PAGE = "ta sama strona z kreatora"
PLAIN_SAME_FILES = "{files} na stronie docelowej"
PLAIN_SAME_HEADLINE = "ten sam nagłówek"
PLAIN_SIMILAR_PAGE = "bardzo podobna strona docelowa"
VERDICT_SINGLE = "Ta reklama na razie nie ma mocnych powiązań z innymi w bazie."
VERDICT_SUBJECT_FEW = "Te {count} {ads} prowadzą"
VERDICT_SUBJECT = "Tych {count} {ads} prowadzi"
VERDICT_SAME_PAGE = "{subject} do tej samej fałszywej strony{tail}."
VERDICT_LOOK_DIFFERENT = ", choć wyglądają inaczej"
VERDICT_LOOK_SAME = " i wyglądają tak samo"
VERDICT_TRACES = "{subject} do stron tego samego sprawcy: mają wspólne ślady techniczne."
COMPARE_FILES = "Te same pliki na stronie docelowej"
COMPARE_FILES_HINT = "{files} co do bajta, na przykład te zdjęcia. Tak wygląda skopiowana strona."
COMPARE_TEXT = "Ten sam tekst na stronie docelowej"
COMPARE_TEXT_HINT = "Teksty stron są zgodne w {percent}%. Wyróżnione zdanie jest na każdej z nich."
COMPARE_TEXT_HINT_PLAIN = "Wyróżnione zdanie jest na każdej ze stron."
COMPARE_TITLE = "Ten sam tytuł strony"
COMPARE_TITLE_HINT = "Tytuł, który przeglądarka pokazuje na karcie."
COMPARE_IDS = {
    "KitLanding": (
        "Ten sam numer strony w kreatorze",
        "Strony zbudowano w programie do tworzenia stron. Ten sam numer oznacza tę samą stronę.",
    ),
    "KitTenant": (
        "To samo konto w kreatorze stron",
        "Strony założono z jednego konta w programie do tworzenia stron.",
    ),
    "Tracker": (
        "Ten sam piksel śledzący",
        "Kod, który zlicza wejścia z reklam. Ten sam numer oznacza to samo konto reklamowe.",
    ),
}
COMPARE_HEADLINE = "Ten sam nagłówek"
COMPARE_HEADLINE_HINT = "Ten sam wzór nagłówka w reklamach lub na stronach."
COMPARE_RECOGNISED = {
    "Person": (
        "Ta sama osoba: {name}",
        "Twarz rozpoznana przez porównanie z bazą osób publicznych (zdjęcia z Wikimedia Commons). "
        "To tylko wskazówka: sama twarz nie łączy kampanii.",
    ),
    "Brand": (
        "Ta sama marka: {name}",
        "Marka, pod którą podszywa się strona, rozpoznana po nazwie lub logo. To tylko wskazówka.",
    ),
}
COMPARE_CREATIVE = "Obraz reklamy"
COMPARE_CREATIVE_HINT = "Każda reklama pokazuje coś innego (patrz obrazy na górze)."
COMPARE_CREATIVE_HINT_MIXED = (
    "Część reklam pokazuje ten sam obraz, część inny (patrz obrazy na górze)."
)
COMPARE_DOMAIN = "Adres strony (domena)"
COMPARE_DOMAIN_HINT = "Oszuści często zmieniają adres, bo łatwo go zablokować."
COMPARE_ROTATING = {
    "Narrative": ("Nagłówek", "Ta sama historia opowiedziana innymi słowami."),
    "Advertiser": ("Konto reklamodawcy", "Reklamy wykupiono z różnych kont."),
    "Person": ("Rozpoznane osoby", "Wizerunki znanych osób użyte bez ich zgody."),
}
# First plain line of an analysis verdict.
PLAIN_VERDICT_EXISTING = "To wygląda na kolejną odsłonę kampanii „{campaign}”, bo ma {reasons}."
PLAIN_VERDICT_EXISTING_BARE = "To wygląda na kolejną odsłonę kampanii „{campaign}”."
PLAIN_VERDICT_NEW = (
    "To wygląda na coś nowego: nie ma mocnych wspólnych śladów z żadną znaną kampanią."
)
PLAIN_VERDICT_REVIEW = (
    "To może być kolejna odsłona kampanii „{campaign}”, ale dowody są za słabe, "
    "by mieć pewność. Powinien na to spojrzeć analityk."
)
PLAIN_VERDICT_REVIEW_BARE = (
    "Są wspólne ślady ze znanymi kampaniami, ale za słabe, by mieć pewność. "
    "Powinien na to spojrzeć analityk."
)
PLAIN_VERDICT_INSUFFICIENT = (
    "Z samego adresu nic nie da się stwierdzić: tej strony nie ma w bazie, a linków nie otwieramy."
)
# What was recognised in analysed material (Verdict.found / Verdict.similar).
FOUND_METHODS = {
    "face": "twarz",
    "text": "wzmianka w tekście",
    "logo": "logo",
    "brand": "marka",
}
PLAIN_FOUND = " Rozpoznano: {items}."
PLAIN_FOUND_FACE = "{name} (twarz, podobieństwo {similarity})"
PLAIN_FOUND_TEXT = "{name} (wzmianka w tekście)"
PLAIN_SAME_PERSON = (
    " {name} występuje też w kampanii „{campaign}”: to trop do sprawdzenia, nie dowód, "
    "bo te same znane osoby pojawiają się w wielu niezwiązanych kampaniach."
)
TRACE_PERSON = "ta sama osoba: {name} ({method})"
TRACE_BRAND = "ta sama marka: {name}"
TRACE_DOMAIN = "ta sama domena: {domain}"
TRACE_EVIDENCE = "{label}: {text}"
# Short reasons shown per pair of reports.
SIMILARITY_REASONS = {
    "text.minhash": "tekst zgodny w {percent}%",
    "text.bge": "treść podobna w {percent}%",
    "html.dom_minhash": "struktura strony zgodna w {percent}%",
    "html.css_minhash": "style strony zgodne w {percent}%",
    "img.siglip": "treść obrazu podobna w {percent}%",
}
SAME_IMAGE_ON_LANDING = "identyczny obraz na stronie docelowej"
PAIR_REASONS = {
    "img.pdq": "identyczny obraz",
    "img.phash": "identyczny obraz",
    "ids.kit_landing": "ta sama strona w kreatorze stron",
    "ids.kit_tenant": "to samo konto w kreatorze stron",
    "ids.fb_pixel": "ten sam piksel Meta",
    "text.headline_tpl": "ten sam wzorzec nagłówka",
}

TOPICS = {
    "investment": "inwestycje",
    "health_product": "produkt zdrowotny",
    "gambling": "hazard",
    "fake_news": "fałszywy artykuł prasowy",
}

FEATURE_KINDS: dict[str, str] = {
    "ids.kit_landing": "Ta sama strona w kreatorze stron",
    "ids.kit_tenant": "To samo konto w kreatorze stron",
    "ids.fb_pixel": "Ten sam piksel Meta",
    "ids.gtag": "Ten sam tag Google",
    "ids.ad_param": "Ten sam parametr reklamy",
    "ids.click_key": "Ten sam klucz kliknięć",
    "ids.ad_library": "Ta sama reklama w Bibliotece Meta",
    "ids.advertiser_page": "Ta sama strona reklamodawcy",
    "asset.sha256": "Identyczne pliki na stronach",
    "text.raw": "Ten sam tekst",
    "html.title": "Ten sam tytuł strony",
    "text.minhash": "Prawie identyczny tekst",
    "text.headline_tpl": "Ten sam wzorzec nagłówka",
    "text.headline_fuzzy": "Bardzo podobny nagłówek",
    "text.lang": "Ten sam język",
    "img.face_share": "Podobny układ twarzy na obrazie",
    "infra.registered": "Podobna data rejestracji domeny",
    "text.bge": "Podobna treść (znaczenie)",
    "text.topic": "Ten sam temat",
    "text.ocr": "Ten sam tekst na obrazie",
    "text.asr": "Ten sam tekst w nagraniu",
    "ocr.headline": "Ten sam nagłówek na obrazie",
    "infra.host_3p": "Ten sam host zewnętrzny",
    "infra.endpoint": "Ten sam punkt zbierania danych",
    "infra.redirect_hop": "To samo przekierowanie",
    "infra.favicon_mmh3": "Ta sama ikona strony",
    "infra.server_stack": "Ten sam stos serwerowy",
    "infra.ip": "Ten sam adres IP",
    "infra.cert_issuer": "Ten sam wystawca certyfikatu",
    "infra.cert_san": "Ta sama nazwa w certyfikacie",
    "infra.ns": "Te same serwery nazw",
    "infra.asn": "Ten sam hosting",
    "infra.registrar": "Ten sam rejestrator",
    "url.schema": "Ten sam schemat adresu",
    "url.outlink_domain": "Linki do tej samej domeny",
    "url.domain": "Ta sama domena",
    "ocr.domain": "Ta sama domena na obrazie",
    "ocr.short_link": "Ten sam link skrócony na obrazie",
    "html.dom_minhash": "Podobna struktura strony",
    "html.css_minhash": "Podobne style strony",
    "kit.path_sig": "Te same ścieżki plików",
    "kit.sdk": "Ten sam plik SDK kreatora",
    "kit.dep_host": "Ta sama biblioteka zewnętrzna",
    "img.phash": "Prawie identyczny obraz",
    "img.pdq": "Prawie identyczny obraz",
    "img.siglip": "Podobna treść obrazu",
    "brand.impersonated": "Ta sama podszywana marka",
    "brand.logo": "To samo logo marki",
    "person.public_figure": "Ta sama osoba publiczna",
    "person.mentioned": "Ta sama osoba wymieniona w tekście",
    "ad.advertiser": "Ten sam reklamodawca",
    "ids.short_link": "Ten sam skrócony link",
    "ids.phone": "Ten sam numer telefonu",
    "ids.bank_account": "Ten sam numer konta",
    "ids.messenger": "To samo konto w komunikatorze",
    "meta.ns": "Te same serwery nazw (wg rejestru)",
    "meta.cert_san": "Ta sama nazwa w certyfikacie (rejestr certyfikatów)",
    "meta.ip": "Ten sam adres IP (DNS)",
    "meta.asn": "Ten sam hosting (DNS)",
    "meta.registrar": "Ten sam rejestrator (RDAP)",
    "meta.cert_issuer": "Ten sam wystawca certyfikatu (rejestr certyfikatów)",
}

FLAGS = {
    "capture_error": "Błąd przechwycenia",
    "cloaking_suspected": "Podejrzenie cloakingu",
    "video_only": "Tylko wideo",
    "insufficient_data": "Za mało danych",
    "needs_review": "Do weryfikacji",
    "low_cohesion": "Niska spójność",
}

ROLES = {
    "network": "Ruch sieciowy (HAR)",
    "landing_page": "Strona docelowa (HTML)",
    "landing_asset": "Pliki strony",
    "screenshot": "Zrzuty ekranu",
    "ad_creative": "Kreacja reklamy",
    "ad_video": "Wideo reklamy",
    "screen_recording": "Nagranie ekranu",
    "ad_library_meta": "Biblioteka reklam Meta",
    "capture_meta": "Metadane przechwycenia",
    "dns_tls": "DNS i TLS",
    "source_meta": "Fakty z artykułu źródłowego",
    "other": "Inne",
}

DECISIONS = {
    "existing": "Wariant znanej kampanii",
    "new": "Nowy wzorzec",
    "review": "Do weryfikacji",
    "insufficient": "Za mało danych",
}

DECISION_TEXT = {
    "existing": "Materiał pasuje do istniejącej kampanii z wyraźną przewagą nad kolejną.",
    "new": "Brak wystarczająco silnych śladów wspólnych z którąkolwiek znaną kampanią.",
    "review": (
        "Są wspólne ślady z kampanią, ale za słabe lub zbyt bliskie innej kampanii, "
        "by przypisać materiał automatycznie. Potrzebna ocena analityka."
    ),
    "insufficient": (
        "Nigdy nie otwieramy linków, więc sam adres nieznanej strony nie daje nam nic do "
        "porównania. Wgraj zrzut ekranu reklamy albo zapisaną stronę (plik HTML, MHTML lub HAR), "
        "a porównamy je z kampaniami w bazie."
    ),
}

CASE_FEATURES: dict[str, str] = {
    "ids.kit_tenant": "Konto w kreatorze stron",
    "ids.kit_landing": "Strona w kreatorze stron",
    "ids.fb_pixel": "Piksel Meta",
    "ids.gtag": "Tag Google",
    "ids.ad_param": "Parametry reklamy",
    "ids.click_key": "Klucze kliknięć",
    "ids.ad_library": "Reklama w Bibliotece Meta",
    "ids.advertiser_page": "Strona reklamodawcy",
    "ad.advertiser": "Nazwa strony reklamodawcy",
    "ad.sponsored": "Oznaczenie reklamy",
    "ad.cta": "Przycisk reklamy",
    "ad.page_category": "Kategoria strony",
    "ad.card_domain": "Domena w karcie linku",
    "url.domain": "Domena docelowa",
    "ocr.domain": "Domena widoczna na obrazie",
    "ocr.short_link": "Link skrócony",
    "asset.sha256": "Pliki strony",
    "html.title": "Tytuł strony",
    "text.raw": "Tekst strony",
    "text.ocr": "Tekst odczytany z obrazów (OCR)",
    "text.asr": "Transkrypcja nagrania",
    "ocr.headline": "Nagłówki odczytane z obrazów",
    "text.headline_tpl": "Wzorce nagłówków",
    "text.topic": "Temat",
    "infra.host_3p": "Hosty zewnętrzne",
    "infra.endpoint": "Punkt zbierania danych",
    "infra.redirect_hop": "Przekierowania",
    "infra.favicon_mmh3": "Ikona strony (skrót)",
    "infra.server_stack": "Serwer",
    "infra.ip": "Adres IP",
    "infra.cert_issuer": "Wystawca certyfikatu",
    "infra.cert_san": "Nazwa w certyfikacie",
    "infra.ns": "Serwery nazw",
    "infra.asn": "Hosting (ASN)",
    "infra.registrar": "Rejestrator",
    "url.schema": "Schemat adresu",
    "url.outlink_domain": "Linki wychodzące do",
    "kit.path_sig": "Ścieżki plików",
    "kit.sdk": "Plik SDK kreatora",
    "kit.dep_host": "Biblioteki zewnętrzne",
    "brand.impersonated": "Podszywana marka",
    "brand.logo": "Logo marki",
    "person.public_figure": "Osoba publiczna",
    "person.mentioned": "Osoba wymieniona w tekście",
    "ids.short_link": "Skrócone linki",
    "ids.phone": "Numery telefonów",
    "ids.bank_account": "Numery kont",
    "ids.messenger": "Konta w komunikatorach",
    "meta.platform": "Platforma (wg artykułu)",
    "meta.ad_date": "Data publikacji reklamy (wg artykułu)",
    "meta.person": "Wykorzystana osoba (wg artykułu)",
    "meta.brand": "Podszywana marka (wg artykułu)",
    "meta.narrative": "Narracja (wg artykułu)",
    "meta.cert_pl_listed": "Domena na liście ostrzeżeń CERT Polska",
    "meta.ns": "Serwery nazw (DNS)",
    "meta.cert_san": "Nazwy w certyfikatach (rejestr certyfikatów)",
    "meta.ip": "Adresy IP (DNS)",
    "meta.asn": "Hosting (ASN)",
    "meta.registrar": "Rejestrator (RDAP)",
    "meta.cert_issuer": "Wystawca certyfikatu (rejestr certyfikatów)",
    "meta.registered": "Data rejestracji domeny (RDAP)",
}

# Fallbacks, so an internal id (a feature kind, an entity type, a flag) never reaches the screen.
UNKNOWN_KIND = "Wspólny ślad"
UNKNOWN_TYPE = "Ślad"
UNKNOWN_FAMILY = "inne ślady"
UNKNOWN_FLAG = "Uwaga"
UNKNOWN_ROLE = "Inne pliki"


def kind_label(kind: str) -> str:
    """Polish label of a feature / evidence kind; never the raw `family.name` id."""
    return FEATURE_KINDS.get(kind, UNKNOWN_KIND)


def type_label(entity_type: str) -> str:
    """Polish name of an entity type."""
    return ENTITY_TYPES.get(entity_type, UNKNOWN_TYPE)


def family_label(family: str) -> str:
    """Polish name of a feature family."""
    return FAMILY_NAMES.get(family, UNKNOWN_FAMILY)


def flag_label(flag: str) -> str:
    """Polish name of a case or campaign flag."""
    return FLAGS.get(flag, UNKNOWN_FLAG)


THUMB_KINDS = {
    "ad": "Kreacja reklamy",
    "screenshot": "Zrzut ekranu",
    "landing": "Zrzut strony docelowej",
}
CAPTURE_ERROR_PAGE = "Błąd przechwycenia strony"
BLANK_SCREENSHOT = "Pusty zrzut ekranu"

OPERATOR = "Sprawca {letter}"
TOOLKIT = "Program do stron: {name}"
TOOLKIT_SHARED = "Ten sam program do tworzenia stron w {count} kampaniach"
UNKNOWN_PERSON = "[osoba]"
FILE_FALLBACK = "plik {short}"
NUMBER_TOKEN = "N"

__all__ = [
    "ADS",
    "ASSET_PLURAL",
    "AT_LEAST",
    "BLANK_SCREENSHOT",
    "CAPTURE_ERROR_PAGE",
    "CASE_FEATURES",
    "COMPARE_CREATIVE",
    "COMPARE_CREATIVE_HINT",
    "COMPARE_CREATIVE_HINT_MIXED",
    "COMPARE_DOMAIN",
    "COMPARE_DOMAIN_HINT",
    "COMPARE_FILES",
    "COMPARE_FILES_HINT",
    "COMPARE_HEADLINE",
    "COMPARE_HEADLINE_HINT",
    "COMPARE_IDS",
    "COMPARE_RECOGNISED",
    "COMPARE_ROTATING",
    "COMPARE_TEXT",
    "COMPARE_TEXT_HINT",
    "COMPARE_TEXT_HINT_PLAIN",
    "COMPARE_TITLE",
    "COMPARE_TITLE_HINT",
    "CORPUS_NAMES",
    "DECISIONS",
    "DECISION_TEXT",
    "DIFFERENT_DOMAINS",
    "ENTITY_TYPES",
    "FAMILY_NAMES",
    "FEATURE_KINDS",
    "FILE_FALLBACK",
    "FLAGS",
    "FOUND_METHODS",
    "IDENTICAL_FILES",
    "IDENTICAL_FILES_INSTR",
    "IN_REPORTS",
    "NUMBER_TOKEN",
    "OPERATOR",
    "PAIR_REASONS",
    "PLAIN_FOUND",
    "PLAIN_FOUND_FACE",
    "PLAIN_FOUND_TEXT",
    "PLAIN_SAME_FILES",
    "PLAIN_SAME_HEADLINE",
    "PLAIN_SAME_KIT_PAGE",
    "PLAIN_SAME_PERSON",
    "PLAIN_SIMILAR_PAGE",
    "PLAIN_SINGLE",
    "PLAIN_VERDICT_EXISTING",
    "PLAIN_VERDICT_EXISTING_BARE",
    "PLAIN_VERDICT_INSUFFICIENT",
    "PLAIN_VERDICT_NEW",
    "PLAIN_VERDICT_REVIEW",
    "PLAIN_VERDICT_REVIEW_BARE",
    "PLAIN_WORDS",
    "POSSIBLE_PAIRS",
    "REPORTS",
    "REPORTS_LOCATIVE",
    "REPORT_TIERS",
    "ROLES",
    "SAME_FILES",
    "SAME_IMAGE_ON_LANDING",
    "SIMILARITY_REASONS",
    "STORY_ALL",
    "STORY_BOTH",
    "STORY_CREATIVES_DIFFERENT",
    "STORY_CREATIVES_MIXED",
    "STORY_CREATIVES_SAME",
    "STORY_IDS",
    "STORY_IDS_EXTRA",
    "STORY_LEAD_DIFFERENT",
    "STORY_LEAD_IDS",
    "STORY_LEAD_OTHER",
    "STORY_LEAD_SAME",
    "STORY_ROTATING",
    "STORY_TEXT",
    "STORY_TEXT_IDENTICAL",
    "THUMB_KINDS",
    "TOOLKIT",
    "TOOLKIT_SHARED",
    "TOPICS",
    "TRACE_BRAND",
    "TRACE_DOMAIN",
    "TRACE_EVIDENCE",
    "TRACE_PERSON",
    "UNKNOWN_FAMILY",
    "UNKNOWN_FLAG",
    "UNKNOWN_KIND",
    "UNKNOWN_PERSON",
    "UNKNOWN_ROLE",
    "UNKNOWN_TYPE",
    "VERDICT_LOOK_DIFFERENT",
    "VERDICT_LOOK_SAME",
    "VERDICT_SAME_PAGE",
    "VERDICT_SINGLE",
    "VERDICT_SUBJECT",
    "VERDICT_SUBJECT_FEW",
    "VERDICT_TRACES",
    "WHY_LINKED",
    "family_label",
    "flag_label",
    "kind_label",
    "type_label",
]
