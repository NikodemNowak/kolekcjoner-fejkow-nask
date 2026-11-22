"""Polish UI copy for the Streamlit app (AGENTS.md §1: never hard-code strings in pages)."""

from __future__ import annotations

TITLE = "Kolekcjoner Fejków"
REPORT_SUMMARY = (
    "{cases} zgłoszeń → {unique} unikatowych → {campaigns} kampanii → {operators} operatorów"
)
REPORT_MEMBERS = "Zgłoszenia"
REPORT_EVIDENCE = "Dowody powiązań"
REPORT_PROFILE = "Wspólne cechy"
SINGLETON_PROFILE = "Cechy zgłoszenia"
SINGLETON_TRAIT = "Cecha zgłoszenia"
SINGLETON_NO_TRAITS = "Brak cech do pokazania."
REPORT_NO_TRAITS = "Brak wspólnych cech do pokazania."
REPORT_NO_EVIDENCE = "Brak dowodów powiązań między zgłoszeniami."
REPORT_CASE_GRAPH = "Graf zgłoszeń"
REPORT_ENTITY_GRAPH = "Graf encji"
REPORT_OPERATORS = "Operatorzy"
REPORT_TOOLKITS = "Zestawy narzędzi"
REPORT_DUPLICATE = "Duplikat zgłoszenia: {case}"
REPORT_COVERAGE = "Pokrycie"
REPORT_LIFT = "Wyróżnienie"
REPORT_CONFIDENCE = "Waga dowodu"
REPORT_ARTIFACTS = "Źródła"
REPORT_THUMBNAIL = "Miniatura zgłoszenia {case}"
REPORT_NO_GROUPS = "Brak danych."
GROUP_EVIDENCE = "Wspólne ślady operatorów i zestawów narzędzi"
GROUP_TRACE = "Wspólny ślad"
GROUP_CASES = "Zgłoszenia i źródła"
GROUP_LABELS = {"operator": "Operator", "toolkit": "Zestaw narzędzi"}
GROUP_ENTITY_NAMES = {
    "Tracker": "Identyfikator śledzący",
    "KitTenant": "Konto w zestawie stron",
    "Host": "Host",
    "Endpoint": "Punkt sieciowy",
    "PathSignature": "Wzorzec ścieżki",
    "KitSDK": "Składnik zestawu",
}
REPORT_DATA_NOTICE = "Raport może zawierać materiały organizatora. Nie udostępniaj go publicznie."
REPORT_TRAIT_CONSTANT = "Stała"
REPORT_TRAIT_ROTATING = "Zmienna"
REPORT_TIERS = {
    "campaign": "Kampania",
    "operator": "Operator",
    "toolkit": "Zestaw narzędzi",
    "context": "Kontekst",
}
ASSIGNMENT_DECISIONS = {
    "existing": "Wariant znanej kampanii",
    "new": "Nowy wzorzec",
    "review": "Do weryfikacji",
}
SUBTITLE = "Łączenie reklam-oszustw w kampanie na podstawie wspólnych śladów."
NO_RUN = "Brak wczytanej analizy. Uruchom: fakecollector run <katalog> --out runs/<nazwa>."
CERT_LIST_LINE = "Lista Ostrzeżeń CERT Polska: {known} domen już na liście, {new} nowych."
CERT_LIST_UNAVAILABLE = (
    "Lista Ostrzeżeń CERT Polska: niedostępna "
    "(wzbogacanie wyłączone lub lista nie została pobrana)."
)

# Pages "Dodaj reklamę" and "Powiązania" (Task 4, priority 1).
PAGE_ADD = "Dodaj reklamę"
PAGE_LINKS = "Powiązania"
PAGE_OVERVIEW = "Przegląd"
PAGE_CAMPAIGN = "Kampania"
PAGE_ENTITY = "Wyszukiwanie śladów"
ENTITY_SELECT = "Wybierz ślad"
ENTITY_NONE = "Brak śladów do pokazania."
ENTITY_STOPPED = (
    "Ten ślad jest zbyt częsty lub znajduje się na liście wykluczeń i nie służy do łączenia."
)
ENTITY_LOCATORS = "Położenie w źródle"
ENTITY_KIND = {
    "Domain": "Domena",
    "Host": "Host",
    "Tracker": "Identyfikator śledzący",
    "Asset": "Plik",
    "Person": "Osoba",
    "Brand": "Marka",
    "IP": "Adres IP",
    "KitLanding": "Identyfikator strony",
    "KitTenant": "Konto w zestawie stron",
    "Endpoint": "Punkt sieciowy",
    "PathSignature": "Wzorzec ścieżki",
}
ENTITY_OTHER = "Ślad"
PAGE_EXPORT = "Eksport"
EXPORT_FORMAT = "Format"
EXPORT_PREPARE = "Przygotuj plik"
EXPORT_DOWNLOAD = "Pobierz plik"
EXPORT_RUNNING = "Przygotowywanie eksportu…"
EXPORT_FAILED = "Nie udało się przygotować eksportu. Sprawdź dziennik aplikacji."
EXPORT_DATA_NOTICE = "Eksport może zawierać materiały organizatora. Nie udostępniaj go publicznie."
EXPORT_FORMAT_NAMES = {
    "report": "Raport HTML",
    "json": "Graf JSON",
    "neo4j": "Neo4j (ZIP)",
    "gexf": "Graf GEXF (ZIP)",
    "graphml": "Graf GraphML (ZIP)",
    "ioc-csv": "Wskaźniki IOC CSV (ZIP)",
    "dataset": "Zbiór danych (ZIP)",
}
CAMPAIGN_SELECT = "Wybierz kampanię"
CAMPAIGN_CASE = "Zgłoszenie"
CAMPAIGN_DUPLICATE = "Duplikat zgłoszenia"
CAMPAIGN_TRAIT = "Cecha"
CAMPAIGN_TYPE = "Rodzaj"
CAMPAIGN_WHY = "Znaczenie"
CAMPAIGN_FROM = "Zgłoszenie 1"
CAMPAIGN_TO = "Zgłoszenie 2"
CAMPAIGN_FAMILY = "Rodzina"
CAMPAIGN_NO_CAMPAIGNS = "Brak kampanii do pokazania."
OVERVIEW_CASES = "Zgłoszenia"
OVERVIEW_UNIQUE = "Unikatowe zgłoszenia"
OVERVIEW_CAMPAIGNS = "Kampanie"
OVERVIEW_OPERATORS = "Operatorzy"
OVERVIEW_FILTER_OPERATOR = "Filtruj według operatora"
OVERVIEW_FILTER_TOOLKIT = "Filtruj według zestawu narzędzi"
OVERVIEW_FILTER_PERSON = "Filtruj według osoby"
OVERVIEW_TABLE = {
    "id": "Identyfikator",
    "label": "Kampania",
    "members": "Zgłoszenia",
    "operator": "Operator",
    "toolkits": "Zestawy narzędzi",
}
OVERVIEW_FOLDER = "Folder ze zgłoszeniami na serwerze"
OVERVIEW_RUN = "Analizuj folder"
OVERVIEW_INVALID = "Podaj istniejący folder ze zgłoszeniami."
OVERVIEW_RUNNING = "Trwa analiza folderu…"
OVERVIEW_FAILED = "Nie udało się przeanalizować folderu. Sprawdź dziennik aplikacji."
OVERVIEW_ACTIVE_RUN = "Katalog analizy: {path}"
ADD_INTRO = (
    "Dodaj jedną reklamę: link, nazwę produktu albo plik (zrzut ekranu, HAR, zapisana strona, "
    "wideo). Zostanie porównana z resztą bazy i dopisana do niej. Link jest tylko analizowany, "
    "nigdy nie jest otwierany."
)
ADD_URL = "Link do reklamy lub strony, albo nazwa produktu"
ADD_FILE = "albo plik z reklamą"
ADD_SUBMIT = "Analizuj i dodaj do bazy"
ADD_EMPTY = "Podaj link, nazwę produktu albo plik."
ADD_RUNNING = "Analiza: wyodrębnianie cech i porównanie z bazą…"
ADD_CAMPAIGN = "Kampania"
ADD_SCORE = "Wynik dopasowania"
ADD_MARGIN = "Przewaga nad kolejną kampanią"
ADD_OPERATOR = "Znany operator: {operator}"
ADD_TOOLKITS = "Znane zestawy narzędzi: {toolkits}"
ADD_DUPLICATE = "Duplikat zgłoszenia {case}."
ADD_COMPARABLE = "Porównano rodziny cech"
ADD_MISSING = "Brak danych (nie liczone na niekorzyść)"
ADD_EVIDENCE = "Dlaczego"
ADD_NO_EVIDENCE = "Brak wspólnych śladów z istniejącymi kampaniami."
ADD_INSUFFICIENT_DATA = "Za mało danych"
ADD_INSUFFICIENT_EXPLANATION = (
    "Sam adres nie wystarcza do ustalenia, czy to nowy wzorzec. Dodaj plik lub zrzut ekranu."
)
ADD_HINTS = "Wskazówki do sprawdzenia"
ADD_SEE_LINKS = "Zgłoszenie {case} jest już w bazie: zobacz je na stronie „Powiązania”."
LINKS_INTRO = (
    "Jedno zgłoszenie może łączyć się z innymi na kilka sposobów naraz (wygląd, postać, tekst, "
    "domena lub infrastruktura), a z inną tylko na jeden. Każda rodzina cech ma własną krawędź."
)
LINKS_CASE = "Zgłoszenie"
LINKS_FAMILIES = "Pokaż tylko powiązania przez rodziny"
FILTER_ALL = "Wszystkie"
YES = "tak"
LINKS_MIN = "Minimalna liczba rodzin cech"
LINKS_NONE = "Brak powiązań spełniających filtry."
LINKS_NO_DATA = "brak danych"
LINKS_COLUMNS = {
    "case": "Zgłoszenie",
    "campaign": "Kampania",
    "score": "Wynik",
    "families": "Liczba rodzin",
    "operator": "Ten sam operator",
    "evidence": "Najmocniejsze dowody",
}
FAMILY_NAMES = {
    "ids": "identyfikatory",
    "infra": "infrastruktura",
    "asset": "wspólne pliki",
    "template": "szablon strony",
    "image": "wygląd (obraz)",
    "text": "tekst i język",
    "person": "postać i marka",
    "meta": "fakty z artykułu źródłowego",
}

# Public-figure names corresponding to the existing reference set.
PERSON_DISPLAY_NAMES = {
    "adam-glapinski": "Adam Glapiński",
    "adam-malysz": "Adam Małysz",
    "agata-mlynarska": "Agata Młynarska",
    "andrzej-duda": "Andrzej Duda",
    "anna-lewandowska": "Anna Lewandowska",
    "barbara-nowacka": "Barbara Nowacka",
    "borys-szyc": "Borys Szyc",
    "cezary-pazura": "Cezary Pazura",
    "cristiano-ronaldo": "Cristiano Ronaldo",
    "daniel-obajtek": "Daniel Obajtek",
    "donald-tusk": "Donald Tusk",
    "dorota-wellman": "Dorota Wellman",
    "elon-musk": "Elon Musk",
    "hubert-urbanski": "Hubert Urbański",
    "iga-swiatek": "Iga Świątek",
    "izabela-leszczyna": "Izabela Leszczyna",
    "janina-ochojska": "Janina Ochojska",
    "jaroslaw-kaczynski": "Jarosław Kaczyński",
    "jerzy-owsiak": "Jerzy Owsiak",
    "karol-nawrocki": "Karol Nawrocki",
    "katarzyna-bosacka": "Katarzyna Bosacka",
    "krystyna-janda": "Krystyna Janda",
    "krzysztof-cugowski": "Krzysztof Cugowski",
    "krzysztof-gawkowski": "Krzysztof Gawkowski",
    "krzysztof-stanowski": "Krzysztof Stanowski",
    "kuba-wojewodzki": "Kuba Wojewódzki",
    "magda-gessler": "Magda Gessler",
    "malgorzata-rozenek-majdan": "Małgorzata Rozenek",
    "marcin-prokop": "Marcin Prokop",
    "marek-belka": "Marek Belka",
    "mark-zuckerberg": "Mark Zuckerberg",
    "mateusz-morawiecki": "Mateusz Morawiecki",
    "monika-olejnik": "Monika Olejnik",
    "piotr-gasowski": "Piotr Gąsowski",
    "piotr-krasko": "Piotr Kraśko",
    "radoslaw-sikorski": "Radosław Sikorski",
    "rafal-brzoska": "Rafał Brzoska",
    "rafal-trzaskowski": "Rafał Trzaskowski",
    "robert-kubica": "Robert Kubica",
    "robert-lewandowski": "Robert Lewandowski",
    "slawomir-mentzen": "Sławomir Mentzen",
    "szymon-holownia": "Szymon Hołownia",
    "tomasz-lis": "Tomasz Lis",
    "tomasz-sekielski": "Tomasz Sekielski",
    "ursula-von-der-leyen": "Ursula von der Leyen",
    "volodymyr-zelensky": "Volodymyr Zelensky",
    "wojciech-cejrowski": "Wojciech Cejrowski",
    "zbigniew-ziobro": "Zbigniew Ziobro",
}
