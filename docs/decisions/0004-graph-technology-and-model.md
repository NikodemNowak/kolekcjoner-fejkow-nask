# 0004: Graph technology and graph model

**Status:** accepted Sat 21.11.

**Context:** Linking ads into campaigns is a graph problem; the task (v2) names a graph database such as Neo4j as one possible direction and scores method quality 30 %, features and sources 30 %, interpretability 15 %, portability 10 %. A hidden test set checks assignment of new material and the ability not to link. The tool must run for the jury with one install, and should stay useful to CERT analysts who already work with Gephi, Maltego, MISP and Neo4j. Measurements on the 25 real cases (`docs/DATA.md` §4) show that most links run through shared *things* (a kit landing ID, a pixel, a collector host, an asset hash), and that these things sit at three different levels: campaign, operator, toolkit.

**Technology options:**
| Option | Verdict |
|---|---|
| In-memory: NetworkX (BSD) for the model, igraph + leidenalg for Leiden | **Chosen for compute.** Zero services, deterministic with a seed, fast far beyond our scale. Note: python-igraph and leidenalg are GPL; `CLUSTER_ALGO=louvain` (NetworkX, BSD) is the permissive fallback. |
| DuckDB + Parquet node/edge tables | **Chosen for persistence and ad-hoc SQL.** Already our store; a run directory is the snapshot. The DuckPGQ property-graph extension is a community extension and adds nothing we need today. |
| Neo4j Community (GPLv3 server, Cypher, Browser) | **Export target, not a runtime dependency.** Analysts get Cypher and Browser; the jury does not have to start a server. Bloom is not part of Community. |
| Kùzu (embedded graph DB) | **Rejected.** The repository was archived in October 2025; the LadybugDB fork is active but too young to build on in 21 hours. |
| GraphQL | **Rejected as a distraction.** It is an API query language for client applications, not a graph store or a graph algorithm. With no HTTP API (ADR 0003) and no external client, it adds a schema and a server without adding any linking capability. If NASK later needs programmatic access, Cypher on the Neo4j export or SQL on the Parquet tables covers it. |

**Exchange formats:** MVP: Neo4j (`nodes_*.csv`, `rels_*.csv` + `import.cypher` with constraints and `MERGE`), GEXF and GraphML (Gephi, yEd), flat IOC CSV (domains, hosts, IDs per campaign), JSON. Stretch: STIX 2.1 bundle (`stix2`, BSD: `campaign`, `infrastructure`, `domain-name`, `ipv4-addr`, `url`, `file`, `x509-certificate`, `identity`, `relationship`, evidence in `x_fakecollector_*` properties), which MISP imports directly; Maltego entity-pair CSV; `--push bolt://` into the compose Neo4j profile.

**Graph model decision:** a heterogeneous **entity graph is the source of truth**; ad-to-ad similarity edges are derived from it.
- Nodes: `Case` (one report; the clustered unit), `Page` (capture variant), and typed entities: `Domain`, `Host`, `IP`, `ASN`, `Cert`, `Tracker`, `Endpoint`, `KitTenant`, `KitLanding`, `Toolkit`, `UrlSchema`, `Asset` (sha256), `ImageGroup` (perceptual), `Person`, `Narrative` (masked headline template), `TextGroup`, `Advertiser`, `AdLibraryId`.
- `Case -[HAS]-> Entity` edges carry provenance (artifact, locator, raw value), so every later claim can be traced to a file.
- Every entity type has a **tier**: `campaign` (landing ID, asset set, text, narrative, image group), `operator` (pixel, tenant, collector host, advertiser, cert), `toolkit` (SDK hash, URL schema, DOM/CSS template), `context` (person, ASN, CDN). Tiers decide what a shared entity may prove.
- `Case -[SIMILAR {score, signals, evidence}]- Case` = projection through shared entities (IDF-weighted, stop-listed) + vector similarity (image, text, DOM), fused by noisy-OR over families.
- Campaigns = Leiden over campaign-tier `SIMILAR` edges. Operators = union-find over rare operator-tier entities. Toolkits = groups by toolkit-tier entity. A campaign has at most one operator; an operator may run several campaigns (measured: A and B).
- **New material is assigned, not re-clustered:** `assign` scores a new case against each campaign (mean of its top-k edges), returns `existing` / `new` / `review` with a calibrated reject threshold and margin, and reports operator and toolkit separately ("new story, known operator"). Existing campaign IDs never change. A family that one side lacks is "not comparable", never a zero.
- Each campaign gets a **common-traits profile** computed from the entity graph: per entity type, the values shared by all or most members (coverage, corpus lift), the values that rotate (for example five domains, two pixels), and a one-line "why it matters" per trait.

**Consequences:** shared-entity evidence is a first-class object rather than a string on an edge, so exports, profiles and pivots ("show every case that loads this collector host") fall out of the model. Hub entities (Cloudflare, `fbevents.js`, a celebrity) are handled in one place (document-frequency cap + tier). The cost is one extra table (`entities`, `case_entities`) and a projection step, both small.
