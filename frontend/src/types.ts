export type Role = "admin" | "operator" | "viewer";

export type User = {
  id: number;
  username: string;
  email: string | null;
  role: Role;
  is_active: boolean;
  must_change_password: boolean;
  failed_login_count: number;
  locked_until: string | null;
  last_login_at: string | null;
  created_at: string;
};

export type Platform = "truenas_scale" | "truenas_core" | "proxmox" | "synology";

export type DeviceStatus = "not_configured" | "disabled" | "waiting" | "ok" | "error";

export type Device = {
  id: number;
  name: string;
  platform: Platform;
  platform_label: string;
  host: string;
  ssh_port: number;
  ssh_username: string;
  auth_method: string;
  has_credentials: boolean;
  public_key: string | null;
  host_key_fingerprint: string | null;
  host_key_confirmed_at: string | null;
  host_key_confirmed_by: string | null;
  has_pending_host_key: boolean;
  timezone: string;
  enabled: boolean;
  collection_interval_minutes: number | null;
  effective_interval_minutes: number;
  connect_timeout: number;
  command_timeout: number;
  tags: string[];
  location: string | null;
  note: string | null;
  os_info: string | null;
  created_at: string;
  updated_at: string;
  last_seen_at: string | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_error: string | null;
  next_run_at: string | null;
  running: boolean;
  status: DeviceStatus;
};

export type Capability = {
  capability: string;
  available: boolean;
  details: string | null;
  checked_at: string;
};

export type Run = {
  id: number;
  device_id: number;
  device_name: string | null;
  trigger: "scheduled" | "manual" | "test";
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  status: "running" | "success" | "partial" | "failed";
  disks_found: number | null;
  errors_count: number;
  error_kind: string | null;
  error_message: string | null;
  details: { os_info?: string; warnings?: string[]; errors?: string[]; detected_platform?: string | null; pools_found?: number } | null;
  initiated_by: string | null;
};

export type DeviceDetail = Device & { capabilities: Capability[]; last_runs: Run[] };

export type HostKeyInfo = { fingerprint: string; key_type: string; verify_command: string };

export type DashboardSummary = {
  devices_total: number;
  devices_by_status: Record<DeviceStatus, number>;
  last_collection_at: string | null;
  next_collection_at: string | null;
  recent_runs: Run[];
  scheduler_running: boolean;
  disks_total: number;
  disks_by_state: Record<DiskState, number>;
  pools_total: number;
  pools_problem: number;
  pools_scanning: number;
  max_temperature_c: number | null;
  smart_failed_disks: number;
  hot_disks: number;
  hot_threshold_c: number;
  attention: AttentionItem[];
  health: Record<HealthLevel, number>;
  alarms: Record<Severity, number>;
  recent_events: { id: number; severity: Severity; status: AlarmStatus | "pending"; title: string; last_seen_at: string; first_seen_at: string }[];
};

export type SystemStatus = {
  version: string;
  scheduler_running: boolean;
  scheduler_heartbeat_at: string | null;
  collection_jobs: number;
  database_ok: boolean;
  database_size_bytes: number;
  disk_total_bytes: number;
  disk_free_bytes: number;
  memory_total_bytes: number | null;
  memory_used_bytes: number | null;
  cpu_percent: number | null;
  cpu_cores: number | null;
  last_successful_collection_at: string | null;
};

export type AuditEntry = {
  id: number;
  username: string | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  source_ip: string | null;
  created_at: string;
  details: Record<string, unknown> | null;
};

export type DiskState = "ok" | "warning" | "critical" | "unknown";
export type SmartHealth = "passed" | "failed" | "unknown" | "unavailable" | "standby";
export type DiskType = "hdd" | "ssd" | "nvme" | "sas" | "usb" | "unknown";

export type DiskSample = {
  id: number;
  collected_at: string;
  device_path: string | null;
  smart_available: boolean;
  smart_health: SmartHealth;
  smart_message: string | null;
  temperature_c: number | null;
  power_on_hours: number | null;
  power_cycles: number | null;
  reallocated_sectors: number | null;
  pending_sectors: number | null;
  uncorrectable_sectors: number | null;
  crc_errors: number | null;
  reported_uncorrect: number | null;
  load_cycles: number | null;
  start_stop_count: number | null;
  ssd_life_left: number | null;
  total_lbas_written: number | null;
  percentage_used: number | null;
  available_spare: number | null;
  available_spare_threshold: number | null;
  media_errors: number | null;
  critical_warning: number | null;
  unsafe_shutdowns: number | null;
  data_units_read: number | null;
  data_units_written: number | null;
  host_read_commands: number | null;
  host_write_commands: number | null;
  controller_busy_time: number | null;
  error_log_entries: number | null;
  warning_temp_time: number | null;
  critical_temp_time: number | null;
  error_log_count: number | null;
  self_test_running: boolean;
  self_test_status: string | null;
  attributes?: SmartAttribute[];
};

export type SmartAttribute = {
  id: number;
  name: string;
  value: number | null;
  worst: number | null;
  thresh: number | null;
  raw: number | null;
  raw_string: string | null;
  prefail: boolean;
  when_failed: string | null;
};

export type Disk = {
  id: number;
  device_id: number;
  device_name: string;
  platform: Platform;
  stable_identifier: string;
  device_path: string;
  model: string | null;
  vendor: string | null;
  serial_number: string | null;
  wwn: string | null;
  firmware: string | null;
  disk_type: DiskType;
  interface_type: string | null;
  capacity_bytes: number | null;
  rotation_rate: number | null;
  form_factor: string | null;
  first_seen_at: string;
  last_seen_at: string;
  is_present: boolean;
  state: DiskState;
  reasons: string[];
  pools: string[];
  latest: DiskSample | null;
  /** Poslednje očitavanje sa SMART podacima kada je disk trenutno u standby-ju. */
  last_smart: DiskSample | null;
  health: DiskHealthInfo;
};

export type SelfTestEntry = {
  test_type: string;
  status: string;
  passed: boolean | null;
  lifetime_hours: number | null;
  remaining_percent: number | null;
  first_seen_at: string;
};

export type DiskDetail = Disk & { self_tests: SelfTestEntry[] };

export type PoolMember = {
  name: string;
  state: string | null;
  read_errors: number | null;
  write_errors: number | null;
  checksum_errors: number | null;
  disk_path: string | null;
  disk_id: number | null;
  kind: "disk" | "vdev" | "group";
  depth: number;
  note: string | null;
};

export type Pool = {
  id: number;
  device_id: number;
  device_name: string;
  name: string;
  technology: "zfs" | "lvm_thin" | "lvm_vg" | "mdadm" | "pve_storage" | "synology_volume";
  status: string;
  healthy: boolean | null;
  redundancy: string | null;
  capacity_bytes: number | null;
  used_bytes: number | null;
  free_bytes: number | null;
  read_errors: number | null;
  write_errors: number | null;
  checksum_errors: number | null;
  message: string | null;
  data_errors: string | null;
  scan_type: string | null;
  scan_state: string | null;
  scan_progress: number | null;
  scan_errors: number | null;
  scan_finished_at: string | null;
  scan_text: string | null;
  members: PoolMember[];
  details: Record<string, unknown>;
  first_seen_at: string;
  last_seen_at: string;
  is_present: boolean;
};

export type AttentionItem = {
  kind: "disk" | "pool";
  id: number;
  device_name: string | null;
  name: string;
  state: DiskState;
  reasons: string[];
};

export type PrivilegeProfile = {
  platform: Platform;
  sudo_commands: string[];
  sudoers: string;
  unprivileged: string[];
  notes: string[];
};

export type MetricStats = {
  metric: string;
  label: string;
  unit: string;
  kind: "gauge" | "counter";
  min: number | null;
  max: number | null;
  avg: number | null;
  n: number;
  first: number | null;
  first_at: string | null;
  last: number | null;
  last_at: string | null;
  previous: number | null;
  delta: number | null;
  rate_per_day: number | null;
};

export type SeriesResponse = {
  metric: string;
  label: string;
  unit: string;
  kind: "gauge" | "counter";
  bucket: "raw" | "hour" | "day" | "week";
  from: string;
  to: string;
  series: { id: number; label: string; points: { t: string; value: number | null; min: number | null; max: number | null; n: number }[]; stats: MetricStats }[];
};

export type MetricCatalog = {
  disk: Record<string, { label: string; unit: string; kind: string }>;
  pool: Record<string, { label: string; unit: string; kind: string }>;
  max_series: number;
};

export type TrendWindow = { delta: number | null; first: number | null; last: number | null; first_at: string | null; covered_hours: number | null };
export type DiskTrends = Record<string, { label: string; unit: string; kind: string; "24h": TrendWindow; "7d": TrendWindow; "30d": TrendWindow }>;

export type Outage = { start: string; end: string | null; failed_runs: number; reason: string | null; duration_seconds: number };
export type AvailabilityTotals = {
  runs: number;
  ok: number;
  failed: number;
  availability_percent: number | null;
  outages: number;
  outage_seconds: number;
  longest_outage_seconds: number;
};
export type AvailabilityResponse = {
  bucket: string;
  devices: { id: number; name: string; buckets: { t: string; ok: number; failed: number }[]; outages: Outage[]; totals: AvailabilityTotals }[];
};

export type StatsOverview = {
  from: string;
  to: string;
  disk_states: Record<DiskState, number>;
  smart_failed_disks: number;
  temperature: { id: number; label: string; min: number; max: number; avg: number }[];
  power_on_hours: { id: number; label: string; value: number }[];
  wear: { id: number; label: string; value: number; source: string }[];
  pools: {
    id: number;
    label: string;
    technology: string;
    capacity_bytes: number | null;
    used_bytes: number | null;
    delta_bytes: number | null;
    rate_bytes_per_day: number | null;
    days_to_full: number | null;
  }[];
  availability: ({ id: number; name: string } & AvailabilityTotals)[];
};

export type ReportData = {
  title: string;
  subtitle: string | null;
  notes: string[];
  columns: { key: string; label: string; kind: string }[];
  rows: Record<string, unknown>[];
};

export type Severity = "info" | "warning" | "high" | "critical";
export type HealthLevel = "excellent" | "good" | "attention" | "endangered" | "critical" | "unknown";
export type AlarmStatus = "open" | "acknowledged" | "resolved";

export type DiskHealthInfo = {
  level: HealthLevel;
  score: number | null;
  reasons: { severity: Severity; rule: string; text: string }[];
  updated_at: string | null;
};

export type Alarm = {
  id: number;
  severity: Severity;
  max_severity: Severity;
  status: AlarmStatus;
  category: string;
  rule: string;
  title: string;
  message: string;
  metric: string | null;
  previous_value: number | null;
  current_value: number | null;
  period: string | null;
  details: Record<string, unknown> | null;
  device_id: number | null;
  device_name: string | null;
  disk_id: number | null;
  disk_name: string | null;
  pool_id: number | null;
  pool_name: string | null;
  first_seen_at: string;
  last_seen_at: string;
  occurrence_count: number;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  resolved_at: string | null;
  resolved_by: string | null;
  last_notified_at: string | null;
};

export type AlarmDetail = Alarm & {
  history: { created_at: string; action: string; username: string | null; severity: Severity | null; comment: string | null }[];
  notifications: NotificationLogEntry[];
};

export type AlarmSummary = {
  active: Record<Severity, number>;
  unacknowledged: Record<Severity, number>;
  total_active: number;
};

export type NotificationLogEntry = {
  id?: number;
  event_id?: number | null;
  channel: string;
  target: string | null;
  sent_at: string;
  status: string;
  error_message: string | null;
};

export type EmailSettings = {
  enabled: boolean;
  host: string;
  port: number;
  security: "starttls" | "ssl" | "none";
  username: string;
  has_password: boolean;
  from_addr: string;
  recipients: string[];
  min_severity: Severity;
};

export type MqttSettings = {
  enabled: boolean;
  host: string;
  port: number;
  tls: boolean;
  tls_insecure: boolean;
  username: string;
  has_password: boolean;
  client_id: string;
  prefix: string;
  qos: number;
  retain: boolean;
  heartbeat_seconds: number;
  discovery: boolean;
  discovery_prefix: string;
  entities: string[];
  status: { running: boolean; connected: boolean; last_publish_at: string | null; last_error: string | null };
};

export type Thresholds = {
  temperature: Record<"hdd" | "ssd" | "nvme", { info: number; warning: number; critical: number }>;
  percentage_used: { warning: number; high: number; critical: number };
  pool_usage: { warning: number; high: number; critical: number };
  ssd_life_left: { warning: number; high: number };
} & Record<string, number | Record<string, unknown>>;

export type NotificationSettings = {
  email: EmailSettings;
  mqtt: MqttSettings;
  general: { base_url: string; notify_resolved: boolean };
  thresholds: Thresholds;
  threshold_defaults: Thresholds;
  mqtt_entities: string[];
};

export type PushSub = {
  id: number;
  endpoint_host: string;
  endpoint_hash: string;
  user_agent: string | null;
  min_severity: Severity;
  device_ids: number[] | null;
  muted_until: string | null;
  created_at: string;
  last_success_at: string | null;
  last_error: string | null;
};
