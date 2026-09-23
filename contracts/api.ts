// contracts/api.ts — API-контракт v1. ЗАМОРОЖЕН с T+0:20.
// Изменения — только владелец C, с объявлением в чате команды и правкой examples/*.json.
// Бэкенд генерирует pydantic-модели по этому файлу (ekt_api/schemas.py), фронтенд импортирует типы напрямую (@contracts/api).
// Даты — ISO 8601 (YYYY-MM-DD), месяцы — "YYYY-MM", время — ISO с таймзоной. Количества — в единицах продажи, если не указано иное.

export type Locale = "ru" | "kk";
export interface I18nText { ru: string; kk: string }

export type SupplierId = string; // "SE" | "IEK" | пользовательские
export type Role = "buyer" | "approver" | "admin";
export type Urgency = "critical" | "high" | "medium" | "low" | "none";
export type DemandClass = "smooth" | "erratic" | "intermittent" | "lumpy" | "new" | "dead";
export type Lifecycle = "active" | "new" | "eol" | "discontinued" | "made_to_order";
export type Abc = "A" | "B" | "C" | "N";
export type LineFlag =
  | "EXCESS" | "STOCK_ESTIMATED" | "UOM_CHECK" | "DATA_WARNING" | "ONE_OFF" | "STOCKOUT_HISTORY"
  | "CHANNEL_SPLIT" | "NEW" | "EOL" | "MTO" | "DISCONTINUED_SUSPECT";

// ---------- ошибки (RFC 7807) ----------
export interface Problem { type: string; title: string; status: number; detail?: string; code?: string }

// ---------- auth ----------
export interface LoginRequest { username: string; password: string }
export interface User { username: string; display_name: string; role: Role; csrf_token: string; locale: Locale }

// ---------- датасеты и качество ----------
export type FileKind = "sales_lines" | "sales_monthly" | "stock_opening" | "master" | "moq" | "inbound" | "season" | "custom";
export interface DetectedFile {
  filename: string; sha256: string; profile: string | null; supplier_id: SupplierId | null; kind: FileKind | null;
  rows: number; status: "ok" | "unknown" | "rejected"; message?: I18nText;
}
export interface QualityIssue {
  code: string; severity: "info" | "warn" | "error"; supplier_id?: SupplierId; file?: string;
  count: number; message: I18nText; examples?: string[];
}
export interface Reconciliation { supplier_id: SupplierId; month: string; qty_monthly: number; qty_lines: number; ratio: number | null }
export interface QualityReport {
  dataset_id: string; as_of: string; issues: QualityIssue[]; reconciliation: Reconciliation[];
  counts: Record<string, number>; // skus, sales_lines, months, inbound_docs, quarantine, pii_scrubbed ...
}
export interface Dataset {
  dataset_id: string; created_at: string; as_of: string; files: DetectedFile[];
  suppliers: SupplierId[]; sku_count: number; quality: QualityReport;
}

// ---------- расчёт ----------
export interface GrowthOverride { scope: "supplier" | "category" | "line"; key: string; pct: number; note?: string }
export interface RunParams {
  as_of?: string;
  suppliers?: SupplierId[];
  categories?: Abc[];
  service_levels?: Partial<Record<Abc | "NEW", number>>;
  lead_time_days?: Record<string, number>;   // channel_id -> дни
  review_days?: Record<SupplierId, number>;
  cover_max_months?: Partial<Record<Abc, number>>;
  growth_overrides?: GrowthOverride[];
  include_rc?: boolean;
}
export interface ChannelSummary {
  channel_id: string; supplier_id: SupplierId; name: string; lead_time_days: number;
  lead_time_source: "data" | "default" | "user"; is_fast: boolean; lines_to_order: number; value_kzt: number | null;
}
export interface SupplierSummary {
  supplier_id: SupplierId; name: string; lines: number; lines_to_order: number; value_kzt: number | null;
  critical: number; high: number; excess_value_kzt: number | null; stock_estimated: boolean; channels: ChannelSummary[];
}
export interface RunSummary {
  run_id: string; dataset_id: string; as_of: string; engine_version: string; created_at: string; params: RunParams;
  totals: { lines: number; lines_to_order: number; value_kzt: number | null; critical: number; high: number; excess_value_kzt: number | null };
  suppliers: SupplierSummary[]; quality_warnings: number;
}

export interface ChannelSuggestion { channel_id: string; qty: number; arrival: string }
export interface Line {
  sku_id: string; supplier_id: SupplierId; supplier_name: string; channel_id: string; supplier_article: string | null;
  name: string; group: string | null; abc: Abc | null; demand_class: DemandClass; lifecycle: Lifecycle;
  uom_sales: string; uom_purchase: string; purchase_factor: number;
  stock_now: number; stock_is_estimate: boolean; inbound_qty: number; next_eta: string | null;
  forecast_month: number; cover_months_now: number | null;
  recommended_qty: number;           // ед. продажи
  recommended_qty_purchase: number;  // ед. закупки (кратно order_multiple)
  order_multiple: number; min_order_qty: number;
  value_kzt: number | null; urgency: Urgency; stockout_date: string | null; order_by: string | null;
  reason_short: I18nText; reason_codes: string[]; flags: LineFlag[];
  channel_suggestion: ChannelSuggestion | null;
}
export interface LinesResponse { run_id: string; total: number; items: Line[] }

export interface SeriesPoint {
  month: string; is_future: boolean;
  sales_raw: number | null; sales_clean: number | null; demand_restored: number | null;
  availability: number | null; stock_opening: number | null; one_off_qty: number;
  forecast: number | null; forecast_lo: number | null; forecast_hi: number | null;
}
export type WaterfallKey =
  | "base" | "season" | "trend" | "manual_growth" | "safety_stock" | "stock_now" | "inbound"
  | "floor" | "block" | "cap" | "rounding" | "result";
export interface WaterfallStep { key: WaterfallKey; label: I18nText; value: number }
export interface Reason { code: string; params: Record<string, number | string | null>; text: I18nText; impact_qty: number | null }
export interface OneOffLine { date: string; doc_key: string; qty: number; cap: number; excess: number; removed: number; rule: string; client_hash: string | null }
export interface Inbound { doc_id: string; channel_id: string; order_date: string | null; eta: string; qty: number; source: "doc" | "comment" | "column" | "default"; in_horizon: boolean }
export interface Analog { sku_id: string; name: string; similarity: number; level_month: number }
export interface Note { kind: "comment" | "name_suffix" | "section" | "marker" | "color"; text: string; suggestion_id?: string }
export interface ProjectionPoint { date: string; stock: number; arrivals: number }
export interface SkuDetail {
  line: Line;
  series: SeriesPoint[];
  projection: ProjectionPoint[];               // по дням, 0..180 (UI может прореживать)
  waterfall: WaterfallStep[];
  reasons: Reason[];
  counterfactuals: { without_stockout_restore: number; without_one_off_exclusion: number; raw_average_method: number };
  one_off_lines: OneOffLine[];
  inbound: Inbound[];
  analogs: Analog[];
  notes: Note[];
  params: {
    lead_time_days: number; review_days: number; horizon_days: number; service_level: number; z: number;
    sigma_month: number; safety_stock: number; level_month: number; trend_pct_year: number;
    season_coefs: number[]; season_source: "sku" | "group" | "supplier";
  };
  stock: { free: number; reserved: number; retail: number; showcase: number; tz: number; rc: number; is_estimate: boolean };
}

// ---------- what-if ----------
export interface WhatIfRequest {
  scope: { sku_ids?: string[]; supplier_id?: SupplierId; channel_id?: string };
  changes: {
    inbound_delta?: number; stock_delta?: number; lead_time_delta_days?: number;
    inbound_delay_days?: number; growth_pct?: number; service_level?: number;
  };
}
export interface WhatIfItem {
  sku_id: string; name: string; qty_before: number; qty_after: number;
  urgency_before: Urgency; urgency_after: Urgency; stockout_date_before: string | null; stockout_date_after: string | null;
}
export interface WhatIfResponse { changed: number; value_delta_kzt: number | null; items: WhatIfItem[] }

// ---------- заказы ----------
export type OrderStatus = "draft" | "submitted" | "approved" | "rejected" | "exported";
export interface OrderLine {
  sku_id: string; name: string; recommended_qty: number; final_qty: number; final_qty_purchase: number;
  uom_sales: string; uom_purchase: string; value_kzt: number | null; edit_reason: string | null; urgency: Urgency;
}
export interface OrderEvent { ts: string; actor: string; action: "create" | "edit" | "submit" | "approve" | "reject" | "export"; comment?: string }
export interface Order {
  order_id: string; run_id: string; supplier_id: SupplierId; channel_id: string | null; status: OrderStatus;
  created_by: string; created_at: string; lines: OrderLine[]; total_value_kzt: number | null; events: OrderEvent[];
}
export interface CreateOrderRequest { run_id: string; supplier_id: SupplierId; channel_id?: string; sku_ids?: string[] }
export interface EditOrderLineRequest { final_qty: number; reason?: string } // reason обязателен при |Δ| > 20%
export interface RejectRequest { comment: string }
export type ExportFormat = "1c_xlsx" | "manager_xlsx" | "csv";

// ---------- аудит ----------
export interface AuditEntry { id: number; ts: string; actor: string; action: string; entity: string; entity_id: string; payload: Record<string, unknown>; prev_hash: string; hash: string }
export interface AuditVerify { ok: boolean; checked: number; broken_at: number | null }

// ---------- ИИ ----------
export interface ChatMessage { role: "user" | "assistant"; content: string }
export interface ChatRequest { run_id: string; locale: Locale; messages: ChatMessage[] }
export interface Grounding { ok: boolean; unmatched: string[] }
export type ChatEvent =
  | { type: "intent"; name: string }                          // сработал детерминированный роутер
  | { type: "tool_call"; name: string; args: Record<string, unknown> }
  | { type: "tool_result"; name: string; summary: string }
  | { type: "token"; text: string }
  | { type: "final"; text: string; citations: string[]; grounding: Grounding; generated_by: "llm" | "template" }
  | { type: "error"; message: I18nText };
// В тексте ссылки на SKU — [[sku:КОД]], UI превращает в ссылки на карточку.

export interface BriefingFact { key: string; value: number | string; sku_id?: string }
export interface Briefing { run_id: string; locale: Locale; text: string; facts: BriefingFact[]; grounding: Grounding; generated_by: "llm" | "template" }

export interface SearchRequest { q: string; locale: Locale; supplier_id?: SupplierId; limit?: number }
export interface SearchResult {
  sku_id: string; name: string; supplier_id: SupplierId; score: number;
  match: "code" | "article" | "bm25" | "semantic" | "hybrid"; attrs?: Record<string, string | number | boolean>;
}

export type SuggestionType = "successor" | "eol" | "made_to_order" | "uom" | "pack" | "launch_wave" | "discontinued" | "new";
export interface Suggestion {
  id: string; dataset_id: string; sku_id: string; sku_name: string; type: SuggestionType;
  payload: Record<string, unknown>;  // successor: {from_sku, to_sku}; uom: {uom_purchase, factor}; launch_wave: {launch_date} ...
  source: { kind: "comment" | "name_suffix" | "section" | "marker"; ref: string };
  source_text: string; confidence: number; method: "rule" | "llm";
  status: "pending" | "accepted" | "rejected"; rationale: I18nText; decided_by?: string; decided_at?: string;
}

export interface ImportColumnProposal { index: number; header: string; samples: string[]; target: string | null; confidence: number; reason?: string }
export interface ShipmentHeaderParsed { index: number; header: string; doc_id: string | null; channel: string | null; order_date: string | null; eta: string | null }
export interface ImportMappingProposal {
  upload_id: string; filename: string; sheet: string; header_row: number; supplier_guess: string | null;
  columns: ImportColumnProposal[]; shipment_columns: ShipmentHeaderParsed[]; month_columns: number[];
}
export interface ImportMappingConfirm { upload_id: string; profile_name: string; supplier_id: SupplierId; columns: { index: number; target: string | null }[] }

export interface VoiceResult { text: string; locale: Locale; duration_s: number }
export interface LetterDraft { order_id: string; locale: Locale; subject: string; body: string; generated_by: "llm" | "template" }
export interface AiHealth {
  llm: { ok: boolean; model: string | null; tokens_per_s?: number }; embedder: { ok: boolean; model: string | null };
  stt: { ok: boolean; model: string | null }; pii: { ok: boolean; ner: boolean };
}
