import axios from "axios";

export const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
  headers: { "Content-Type": "application/json" },
});

api.interceptors.request.use(async (config) => {
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const message = err.response?.data?.detail ?? err.message;
    return Promise.reject(new Error(message));
  }
);

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export type ScanStatus = "queued" | "running" | "complete" | "failed";
export type ScanGrade = "PASS" | "WARN" | "FAIL";
export type ResultStatus = "fail" | "warn" | "pass";
export type Severity = "critical" | "error" | "warning" | "info";
export type Layer = "ddex" | "metadata" | "fraud" | "audio" | "artwork" | "enrichment";

export interface Scan {
  id: string;
  release_id: string;
  org_id: string;
  status: ScanStatus;
  readiness_score: number | null;
  grade: ScanGrade | null;
  total_issues: number;
  critical_count: number;
  warning_count: number;
  info_count: number;
  layers_run: string[];
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface ScanResult {
  id: string;
  scan_id: string;
  track_id: string | null;
  layer: Layer;
  rule_id: string;
  severity: Severity;
  status: ResultStatus;
  message: string;
  field_path: string | null;
  actual_value: string | null;
  expected_value: string | null;
  fix_hint: string | null;
  dsp_targets: string[];
  resolved: boolean;
  resolution: string | null;
  resolved_at: string | null;
  resolved_by: string | null;
  created_at: string;
}

export interface ScanDetail extends Scan {
  results: ScanResult[];
}

export interface Release {
  id: string;
  org_id: string;
  external_id: string | null;
  title: string;
  artist: string;
  upc: string | null;
  release_date: string | null;
  submission_format: string;
  raw_package_url: string | null;
  status: string;
  created_at: string;
  // Populated by the list endpoint JOIN — null if no scans yet
  latest_scan_id: string | null;
  latest_scan_grade: string | null;
  latest_scan_score: number | null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Scan API
// ─────────────────────────────────────────────────────────────────────────────

export async function createScan(
  releaseId: string,
  token: string,
  opts?: { dsps?: string[]; layers?: string[] }
): Promise<Scan> {
  const { data } = await api.post<Scan>(
    `/releases/${releaseId}/scan`,
    opts ?? {},
    { headers: { Authorization: `Bearer ${token}` } }
  );
  return data;
}

export async function getScan(scanId: string, token: string): Promise<Scan> {
  const { data } = await api.get<Scan>(`/scans/${scanId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return data;
}

export async function getScanResults(
  scanId: string,
  token: string,
  filters?: { layer?: string; severity?: string; resolved?: boolean }
): Promise<ScanDetail> {
  const params = new URLSearchParams();
  if (filters?.layer) params.set("layer", filters.layer);
  if (filters?.severity) params.set("severity", filters.severity);
  if (filters?.resolved !== undefined)
    params.set("resolved", String(filters.resolved));

  const { data } = await api.get<ScanDetail>(
    `/scans/${scanId}/results?${params.toString()}`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  return data;
}

export async function resolveResult(
  scanId: string,
  resultId: string,
  resolution: string,
  resolvedBy: string,
  token: string
): Promise<ScanResult> {
  const { data } = await api.patch<ScanResult>(
    `/scans/${scanId}/results/${resultId}/resolve`,
    { resolution, resolved_by: resolvedBy },
    { headers: { Authorization: `Bearer ${token}` } }
  );
  return data;
}

export interface ReportURLResponse {
  scan_id: string;
  report_url: string;
  report_generated_at: string | null;
  filename: string;
}

export async function getScanReport(
  scanId: string,
  token: string
): Promise<ReportURLResponse> {
  const { data } = await api.get<ReportURLResponse>(`/scans/${scanId}/report`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return data;
}

export async function regenerateReport(
  scanId: string,
  token: string
): Promise<void> {
  await api.post(`/scans/${scanId}/report/regenerate`, {}, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function listReleaseScanHistory(
  releaseId: string,
  token: string
): Promise<Scan[]> {
  const { data } = await api.get<Scan[]>(`/releases/${releaseId}/scans`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return data;
}

export interface ScanWithRelease extends Scan {
  release_title: string;
  release_artist: string;
}

export async function listOrgScans(
  token: string,
  limit = 50
): Promise<ScanWithRelease[]> {
  const { data } = await api.get<ScanWithRelease[]>(`/scans?limit=${limit}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return data;
}

// ─────────────────────────────────────────────────────────────────────────────
// Dashboard stats API
// ─────────────────────────────────────────────────────────────────────────────

export interface DashboardTopIssue {
  rule_id: string;
  layer: string;
  severity: string;
  count: number;
}

export interface DashboardTrendPoint {
  date: string;
  critical: number;
  warning: number;
  info: number;
}

export interface DashboardStats {
  critical_issues: number;
  scans_this_month: number;
  top_issues: DashboardTopIssue[];
  trend: DashboardTrendPoint[];
}

export async function getDashboardStats(token: string): Promise<DashboardStats> {
  const { data } = await api.get<DashboardStats>("/scans/stats", {
    headers: { Authorization: `Bearer ${token}` },
  });
  return data;
}

// ─────────────────────────────────────────────────────────────────────────────
// Release API
// ─────────────────────────────────────────────────────────────────────────────

export async function listReleases(token: string): Promise<Release[]> {
  const { data } = await api.get<Release[]>("/releases", {
    headers: { Authorization: `Bearer ${token}` },
  });
  return data;
}

export async function getRelease(id: string, token: string): Promise<Release> {
  const { data } = await api.get<Release>(`/releases/${id}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return data;
}

export async function createRelease(
  payload: {
    title: string;
    artist: string;
    submission_format: string;
    upc?: string;
    release_date?: string;
  },
  token: string
): Promise<Release> {
  const { data } = await api.post<Release>("/releases", payload, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return data;
}

// ─────────────────────────────────────────────────────────────────────────────
// Analytics API
// ─────────────────────────────────────────────────────────────────────────────

export interface AggregateStats {
  total_releases_scanned: number;
  total_issues_found: number;
  issues_resolved: number;
  false_positive_rate: number;
}

export interface TopIssueItem {
  rule_id: string;
  rule_label: string;
  layer: string;
  severity: string;
  occurrences: number;
}

export interface DSPMatrixRow {
  dsp: string;
  avg_pass_rate: number;
  trend: number;
  total_scans: number;
  top_failures: string[];
}

export interface FraudSignalItem {
  signal: string;
  rule_id: string;
  total_flags: number;
  confirmed: number;
}

export interface FraudSummary {
  total_flags_this_month: number;
  confirmed: number;
  dismissed: number;
  confirmation_rate: number;
  by_type: FraudSignalItem[];
}

export interface VelocityPoint {
  week: string;
  scans: number;
}

export interface AnalyticsOverview {
  aggregate: AggregateStats;
  top_issues: TopIssueItem[];
  dsp_matrix: DSPMatrixRow[];
  fraud_signals: FraudSummary;
  velocity: VelocityPoint[];
  cached_at: string;
  cache_ttl_seconds: number;
  // Present on shared snapshots
  data_as_of?: string;
  is_sanitized?: boolean;
}

export interface ShareTokenOut {
  token: string;
  expires_at: string;
}

export async function getAnalyticsOverview(token: string): Promise<AnalyticsOverview> {
  const { data } = await api.get<AnalyticsOverview>("/analytics/overview", {
    headers: { Authorization: `Bearer ${token}` },
  });
  return data;
}

export async function refreshAnalyticsOverview(token: string): Promise<AnalyticsOverview> {
  const { data } = await api.post<AnalyticsOverview>(
    "/analytics/overview/refresh",
    {},
    { headers: { Authorization: `Bearer ${token}` } }
  );
  return data;
}

export async function createShareLink(token: string): Promise<ShareTokenOut> {
  const { data } = await api.post<ShareTokenOut>(
    "/analytics/share",
    {},
    { headers: { Authorization: `Bearer ${token}` } }
  );
  return data;
}

export async function getSharedAnalytics(shareToken: string): Promise<AnalyticsOverview> {
  const { data } = await api.get<AnalyticsOverview>(
    `/api/v1/analytics/shared/${shareToken}`
  );
  return data;
}

// ─────────────────────────────────────────────────────────────────────────────
// Billing API
// ─────────────────────────────────────────────────────────────────────────────

export interface PlanInfo {
  id: "starter" | "pro" | "enterprise";
  name: string;
  price_monthly_usd: number;
  scan_limit: number;
  price_id: string | null;
  features: string[];
}

export interface Subscription {
  tier: string;
  plan_name: string;
  status: string | null;
  scan_count: number;
  scan_limit: number;
  period_start: string | null;
  period_end: string | null;
  is_active: boolean;
}

export interface Invoice {
  id: string;
  number: string | null;
  status: string;
  amount_paid_usd: number;
  currency: string;
  period_start: string | null;
  period_end: string | null;
  invoice_pdf: string | null;
  hosted_invoice_url: string | null;
}

export async function getBillingPlans(token: string): Promise<PlanInfo[]> {
  const { data } = await api.get<PlanInfo[]>("/billing/plans", {
    headers: { Authorization: `Bearer ${token}` },
  });
  return data;
}

export async function getSubscription(token: string): Promise<Subscription> {
  const { data } = await api.get<Subscription>("/billing/subscription", {
    headers: { Authorization: `Bearer ${token}` },
  });
  return data;
}

export async function createCheckoutSession(
  priceId: string,
  token: string
): Promise<{ url: string }> {
  const { data } = await api.post<{ url: string }>(
    "/billing/checkout",
    { price_id: priceId },
    { headers: { Authorization: `Bearer ${token}` } }
  );
  return data;
}

export async function createPortalSession(token: string): Promise<{ url: string }> {
  const { data } = await api.post<{ url: string }>(
    "/billing/portal",
    {},
    { headers: { Authorization: `Bearer ${token}` } }
  );
  return data;
}

export async function getInvoices(token: string): Promise<Invoice[]> {
  const { data } = await api.get<Invoice[]>("/billing/invoices", {
    headers: { Authorization: `Bearer ${token}` },
  });
  return data;
}

// ─────────────────────────────────────────────────────────────────────────────
// Admin API
// ─────────────────────────────────────────────────────────────────────────────

export interface AdminOrg {
  id: string;
  clerk_org_id: string;
  name: string;
  tier: string;
  scan_count_current_period: number;
  scan_limit: number;
  is_trial: boolean;
  created_at: string;
  total_scans: number;
  total_releases: number;
}

export interface AdminScanItem {
  id: string;
  release_id: string;
  release_title: string;
  release_artist: string;
  status: string;
  grade: string | null;
  readiness_score: number | null;
  critical_count: number;
  warning_count: number;
  info_count: number;
  created_at: string;
}

export async function adminListOrgs(token: string): Promise<AdminOrg[]> {
  const { data } = await api.get<AdminOrg[]>("/admin/orgs", {
    headers: { Authorization: `Bearer ${token}` },
  });
  return data;
}

export async function adminListOrgScans(
  orgId: string,
  token: string
): Promise<AdminScanItem[]> {
  const { data } = await api.get<AdminScanItem[]>(`/admin/orgs/${orgId}/scans`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return data;
}

export async function adminSetTrial(
  orgId: string,
  scanLimit: number,
  token: string
): Promise<{ org_id: string; is_trial: boolean; scan_limit: number }> {
  const { data } = await api.patch(
    `/admin/orgs/${orgId}/trial`,
    { scan_limit: scanLimit, revoke: false },
    { headers: { Authorization: `Bearer ${token}` } }
  );
  return data;
}

export async function adminRevokeTrial(
  orgId: string,
  token: string
): Promise<{ org_id: string; is_trial: boolean; scan_limit: number }> {
  const { data } = await api.patch(
    `/admin/orgs/${orgId}/trial`,
    { revoke: true },
    { headers: { Authorization: `Bearer ${token}` } }
  );
  return data;
}

export async function adminSetTier(
  orgId: string,
  tier: "starter" | "pro" | "enterprise",
  token: string
): Promise<{ org_id: string; tier: string; is_trial: boolean; scan_limit: number }> {
  const { data } = await api.patch(
    `/admin/orgs/${orgId}/tier`,
    { tier },
    { headers: { Authorization: `Bearer ${token}` } }
  );
  return data;
}
