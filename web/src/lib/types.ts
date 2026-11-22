export type Ref = { id: string; label: string };
export type Thumb = {
  case_id: string;
  artifact_id: string;
  url: string;
  name: string;
  kind: "ad" | "screenshot" | "landing";
  kind_label: string;
  /** Set when the image is a failed capture (error page, blank), not ad material. */
  issue: string | null;
};
export type Value = { text: string; raw: string | null; mono: boolean };

export type TraitRow = {
  entity_type: string;
  type_label: string;
  family: string;
  family_label: string;
  tier: string;
  tier_label: string;
  kind: "constant" | "rotating";
  headline: string;
  values: Value[];
  coverage: number;
  lift: number;
  why: string;
};

export type EvidenceKind = {
  kind: string;
  label: string;
  tier: string;
  tier_label: string;
  pairs: number;
  strength: number;
  values: Value[];
};

export type FamilyEvidence = {
  family: string;
  label: string;
  pairs: number;
  total_pairs: number;
  mean: number;
  kinds: EvidenceKind[];
};

export type GroupLink = {
  kind: "operator" | "toolkit";
  id: string;
  label: string;
  campaigns: Ref[];
  traces: Value[];
};

export type Member = {
  id: string;
  title: string;
  corpus: string;
  domain: string | null;
  duplicate_of: string | null;
  flags: string[];
  thumb: Thumb | null;
};

export type CampaignSummary = {
  id: string;
  label: string;
  size: number;
  operator: Ref | null;
  operator_index: number | null;
  toolkits: Ref[];
  chips: string[];
  rotating: string[];
  persons: string[];
  cohesion: number;
  thumbs: Thumb[];
  flags: string[];
  domains: string[];
  /** One plain line: how many ads, how many addresses, what they share. */
  plain: string;
};

export type PairLink = {
  a: Ref;
  b: Ref;
  score: number;
  reasons: string[];
  creatives: "same" | "different" | "unknown";
};

export type MatrixCell = {
  /** Times the trace was seen in the ad itself / on the landing page. */
  ad: number;
  page: number;
  thumb: string | null;
  confidence: number | null;
};

export type MatrixRow = {
  label: string;
  raw: string | null;
  mono: boolean;
  group: string;
  entity_type: string;
  tier: string;
  technical: boolean;
  cells: MatrixCell[];
  count: number;
};

export type Matrix = { columns: Ref[]; rows: MatrixRow[]; hidden: number };

export type SharedRow = {
  key: string;
  label: string;
  hint: string;
  style: "text" | "badge" | "snippet" | "images" | "person";
  text: string | null;
  mono: boolean;
  before: string;
  after: string;
  images: Thumb[];
  thumb: string | null;
  /** Indices into `members`. */
  members: number[];
  ad: number;
  page: number;
  confidence: number | null;
  context: boolean;
};
export type DiffValue = { text: string; mono: boolean; members: number[] };
export type DiffRow = { key: string; label: string; hint: string; values: DiffValue[] };
export type Variant = { thumb: Thumb | null; members: number[] };
export type Comparison = { same: SharedRow[]; different: DiffRow[]; variants: Variant[] };
export type FaceRef = { url: string; author: string; license: string; source_url: string };
export type Recognised = {
  key: string;
  kind: "person" | "brand";
  name: string;
  thumb: string | null;
  reference: FaceRef | null;
  /** Cosine similarity 0..1 of the face (or logo) to the reference; not a probability. */
  similarity: number | null;
  threshold: number | null;
  /** Persons: "face" (picture) or "text" (named in the text only). */
  method?: string | null;
  /** Method "text": the words that named the person. */
  matched?: string | null;
  members: number[];
  ad: number[];
  page: number[];
};

export type CampaignDetail = CampaignSummary & {
  verdict: string;
  comparison: Comparison;
  recognised: Recognised[];
  summary: string[];
  pairs: PairLink[];
  pairs_total: number;
  matrix: Matrix;
  members: Member[];
  constant: TraitRow[];
  rotating_rows: TraitRow[];
  evidence: FamilyEvidence[];
  links: GroupLink[];
  why: string;
};

export type FeatureFamily = {
  family: string;
  label: string;
  rows: { kind: string; label: string; style: "value" | "text" | "ocr"; values: Value[]; total: number }[];
};

export type Neighbour = {
  id: string;
  title: string;
  campaign: Ref | null;
  score: number;
  operator_link: boolean;
  families: Record<string, number | null>;
  evidence: string[];
};

export type CaseDetail = {
  /** Persons and brands seen in this report (newer API). */
  recognised?: Recognised[];
  id: string;
  title: string;
  corpus: string;
  campaign: Ref | null;
  operator: Ref | null;
  domain: string | null;
  captured_at: string | null;
  duplicate_of: string | null;
  flags: string[];
  headline: string | null;
  inputs: { role: string; label: string; count: number; names: string[] }[];
  thumbs: Thumb[];
  features: FeatureFamily[];
  neighbours: Neighbour[];
};

export type Summary = {
  reports: number;
  unique: number;
  campaigns: number;
  multi_campaigns: number;
  operators: number;
  toolkits: number;
  corpora: Record<string, number>;
  profile: string | null;
  timings: Record<string, number>;
  extractors: number;
  features: number;
  artifacts: number;
};

export type GraphNode = {
  id: string;
  kind: "campaign" | "case" | "entity";
  label: string;
  size: number;
  group: string | null;
  group_index: number | null;
  campaign: string | null;
  tier: string | null;
  entity_type: string | null;
  detail: string | null;
  thumb: string | null;
};

export type GraphLink = {
  source: string;
  target: string;
  kind: string;
  weight: number;
  label: string;
};

export type GraphData = { level: string; nodes: GraphNode[]; links: GraphLink[]; hidden: number };

export type Reason = {
  family: string;
  family_label: string;
  tier: string;
  tier_label: string;
  label: string;
  text: Value;
  weight: number;
  matched: string[];
};

export type Verdict = {
  case_id: string;
  decision: "existing" | "new" | "review" | "insufficient";
  title: string;
  /** First line of the verdict in plain words. */
  plain: string;
  explanation: string;
  score: number;
  margin: number;
  threshold: number;
  min_margin: number;
  strong_link: number;
  campaign: Ref | null;
  closest: Ref | null;
  closest_score: number;
  operator: Ref | null;
  toolkits: Ref[];
  duplicate_of: string | null;
  reasons: Reason[];
  hints: string[];
  comparable: Ref[];
  missing: Ref[];
  flags: string[];
  /** Newer API: what was recognised in the material (persons, brands, domains, headline). */
  found?: Found | null;
  /** Newer API: closest known reports or campaigns with the traces they share. */
  similar?: SimilarItem[] | null;
};

export type NetKind = "report" | "person" | "brand" | "infra" | "template" | "operator";
export type NetNode = {
  id: string;
  kind: NetKind;
  label: string;
  detail: string | null;
  campaign: string | null;
  group_index: number | null;
  image: string | null;
  count: number;
  mono: boolean;
  tier: string | null;
  tier_label: string | null;
};
export type NetLink = {
  source: string;
  target: string;
  /** pair: report-report; trace: report-trace; operator: report-operator. */
  kind: "pair" | "trace" | "operator";
  tier: string | null;
  strength: number;
  reasons: string[];
  where: string | null;
  confidence: number | null;
};
export type NetCampaign = { id: string; label: string; size: number; group_index: number | null; operator: string | null };
export type Network = {
  nodes: NetNode[];
  links: NetLink[];
  campaigns: NetCampaign[];
  hidden: Record<string, number>;
};

/** A person or brand recognised in analysed material (optional, newer API). */
export type FoundItem = {
  kind?: string;
  name?: string;
  label?: string;
  slug?: string;
  similarity?: number | null;
  confidence?: number | null;
  method?: string | null;
  method_label?: string | null;
  similarity_text?: string | null;
  matched?: string | null;
  crop?: string | null;
  reports?: number | null;
  thumb?: string | null;
  reference?: string | FaceRef | null;
  campaigns?: (Ref | string)[];
  count?: number | null;
};
export type Found = {
  persons?: FoundItem[];
  brands?: FoundItem[];
  domains?: (FoundItem | string)[];
  headline?: string | null;
};
/** A known report or campaign close to analysed material, with the traces they share. */
export type SimilarItem = {
  kind?: string;
  id?: string;
  case_id?: string | null;
  campaign_id?: string | null;
  label?: string;
  title?: string;
  campaign?: Ref | null;
  score?: number | null;
  shared?: (string | { label?: string; text?: string; tier?: string | null })[];
  traces?: string[];
  reports?: number | null;
  thumb?: string | null;
  size?: number | null;
};

/** One ad screenshot the automatic collector took from a public article (`fakecollector collect`). */
export type CollectedItem = {
  id: string;
  source?: string;
  publisher?: string;
  article_url?: string;
  article_title?: string;
  published?: string | null;
  image_url?: string;
  alt?: string;
  caption?: string;
  persons?: string[];
  brands?: string[];
  story?: string;
};
export type CollectorResult = {
  item: CollectedItem;
  decision?: string;
  campaign_id?: string | null;
  score?: number;
  margin?: number;
  evidence?: string[];
};
/** `<run>/collector/last.json`; an empty object when the collector has not run. */
export type CollectorReport = {
  started_at?: string;
  finished_at?: string | null;
  sources?: string[];
  since?: string | null;
  committed?: boolean;
  offline?: boolean;
  articles_seen?: number;
  articles_matched?: number;
  items?: CollectorResult[];
  errors?: string[];
};
