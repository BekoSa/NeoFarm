import axios, { AxiosInstance } from "axios";
import { useMemo } from "react";

export interface Profile {
  url: string;
  token: string;
}

const STORAGE_KEY = "farm.profile";

export function loadProfile(): Profile | null {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Profile;
  } catch {
    return null;
  }
}

export function saveProfile(p: Profile) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(p));
}

export function clearProfile() {
  localStorage.removeItem(STORAGE_KEY);
}

export function defaultUrl(): string {
  // Vite injects this at build time; falls back to current origin so a
  // single-origin deploy "just works".
  const fromEnv = (import.meta.env.VITE_API_BASE as string) || "";
  if (fromEnv) return fromEnv;
  return window.location.origin.replace(/:\d+$/, ":5000");
}

export function buildApi(profile: Profile): AxiosInstance {
  return axios.create({
    baseURL: profile.url.replace(/\/$/, ""),
    headers: { "X-Farm-Token": profile.token },
    timeout: 15_000,
  });
}

/** Stable axios instance per (url, token) — avoids re-creating one per render. */
export function useApi(profile: Profile): AxiosInstance {
  return useMemo(() => buildApi(profile), [profile.url, profile.token]);
}

export interface FlagOut {
  id: number;
  flag: string;
  status: string;
  sploit: string | null;
  team: string | null;
  target_ip: string | null;
  response: string | null;
  captured_at: string;
  submitted_at: string | null;
}

export interface ExploitOut {
  id: number;
  name: string;
  host: string | null;
  enabled: boolean;
  last_seen: string | null;
  notes: string | null;
  created_at: string;
}

export interface RunOut {
  id: number;
  sploit: string;
  team: string | null;
  target_ip: string | null;
  host: string | null;
  flags_found: number;
  duration_ms: number | null;
  exit_code: number | null;
  stdout_tail: string | null;
  stderr_tail: string | null;
  started_at: string;
}

export interface StatsBucket {
  label: string;
  accepted: number;
  rejected: number;
  queued: number;
  expired: number;
  duplicate: number;
  error: number;
}

export interface StatsOut {
  totals: StatsBucket;
  by_sploit: StatsBucket[];
  by_team: StatsBucket[];
  last_minute: StatsBucket;
  last_hour: StatsBucket;
}

export interface TeamOut {
  alias: string;
  ip: string;
}

export interface TeamRange {
  from: number;
  to: number;
  alias?: string;
  ip?: string;
}

export type TeamEntry = TeamOut | TeamRange;

export interface FarmConfig {
  flag_format: string;
  flag_lifetime: number;
  round_length: number;
  protocol: string;
  protocols: Record<string, Record<string, unknown>>;
  submitter: { period: number; batch_size: number };
  // Mixed list: explicit {alias, ip} entries and/or {from, to, alias?, ip?}
  // ranges. Use /api/teams if you want a flat, expanded list.
  teams: TeamEntry[];
}
