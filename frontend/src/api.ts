import type { SpecDetail, VaultResponse, ViewResponse, ViewsListResponse } from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export function openVault(root: string) {
  return request<{ root: string; file_count: number }>("/vault/open", {
    method: "POST",
    body: JSON.stringify({ root }),
  });
}

export function listVault() {
  return request<VaultResponse>("/vault");
}

export function getSpec(path: string) {
  return request<SpecDetail>(`/spec?path=${encodeURIComponent(path)}`);
}

export function listViews() {
  return request<ViewsListResponse>("/views");
}

export function getView(section: string) {
  return request<ViewResponse>(`/views/${encodeURIComponent(section)}`);
}

export function writeCell(path: string, section: string, row: number, col: number, value: string) {
  return request<{ ok: boolean }>("/spec/cell", {
    method: "PUT",
    body: JSON.stringify({ path, section, row, col, value }),
  });
}

export function writeField(path: string, section: string, label: string, value: string) {
  return request<{ ok: boolean }>("/spec/field", {
    method: "PUT",
    body: JSON.stringify({ path, section, label, value }),
  });
}

export function appendRevision(path: string, who: string, revision_text: string) {
  return request<{ ok: boolean; revision_number: string }>("/spec/revision", {
    method: "POST",
    body: JSON.stringify({ path, who, revision_text }),
  });
}

export function connectLiveUpdates(onChanged: (path: string) => void): () => void {
  const wsBase = BASE.replace(/^http/, "ws");
  const ws = new WebSocket(`${wsBase}/ws`);
  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === "changed") onChanged(msg.path);
    } catch {
      // ignore malformed frames
    }
  };
  return () => ws.close();
}
