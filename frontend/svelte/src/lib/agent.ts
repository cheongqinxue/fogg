import type {
  ChatMessage,
  LayoutCache,
  LayoutDocument,
  MessageHistoryPage,
  StreamEvent,
  SyncStatus,
  Viewport,
} from "./types";
import { layoutHash } from "./layout";

const API_BASE = (
  import.meta.env.VITE_AGENT_API_BASE_URL || "http://127.0.0.1:18080"
).replace(/\/$/, "");
export const USER_ID = import.meta.env.VITE_AGENT_USER_ID || "default";
const userPath = `/v1/users/${encodeURIComponent(USER_ID)}`;

export class AgentError extends Error {}

async function requestJson(
  path: string,
  init?: RequestInit,
): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { Accept: "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const detail = (await response.text()).slice(0, 180);
    throw new AgentError(
      `Agent request failed (${response.status})${detail ? `: ${detail}` : ""}`,
    );
  }
  const body: unknown = await response.json();
  if (!body || typeof body !== "object")
    throw new AgentError("Agent returned an invalid response.");
  return body as Record<string, unknown>;
}

export async function fetchHistory(cursor?: string): Promise<MessageHistoryPage> {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
  const body = await requestJson(`${userPath}/messages${query}`);
  if (!Array.isArray(body.messages))
    return { messages: [], has_more: false, next_cursor: null };
  const messages = body.messages.flatMap((item: unknown): ChatMessage[] => {
    if (!item || typeof item !== "object") return [];
    const row = item as {
      id?: unknown;
      role?: unknown;
      text?: unknown;
      timestamp?: unknown;
    };
    if (
      typeof row.id !== "string" ||
      (row.role !== "user" && row.role !== "assistant") ||
      typeof row.text !== "string" ||
      typeof row.timestamp !== "string"
    )
      return [];
    return [{
      id: row.id,
      role: row.role,
      text: row.text,
      timestamp: row.timestamp,
      source: "history",
    }];
  });
  return {
    messages,
    has_more: body.has_more === true,
    next_cursor: typeof body.next_cursor === "string" ? body.next_cursor : null,
  };
}

export async function* streamChat(
  message: string,
  clientContext: Record<string, unknown>,
): AsyncGenerator<StreamEvent> {
  const response = await fetch(`${API_BASE}${userPath}/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      Accept: "text/event-stream",
    },
    body: JSON.stringify({ message, client_context: clientContext }),
  });
  if (!response.ok || !response.body) {
    const detail = (await response.text()).slice(0, 180);
    throw new AgentError(
      `Chat request failed (${response.status})${detail ? `: ${detail}` : ""}`,
    );
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, "\n");
      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const data = frame
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart())
          .join("\n");
        if (data) {
          try {
            const parsed = JSON.parse(data) as StreamEvent;
            if (parsed && typeof parsed.type === "string") yield parsed;
          } catch {
            // Ignore malformed SSE frames and continue consuming the stream.
          }
        }
        boundary = buffer.indexOf("\n\n");
      }
      if (done) break;
    }
  } finally {
    reader.releaseLock();
  }
}

export async function syncLayout(
  body: Record<string, unknown>,
): Promise<LayoutCache> {
  return (await requestJson(`${userPath}/layout/sync`, {
    method: "POST",
    headers: { "Content-Type": "application/json; charset=utf-8" },
    body: JSON.stringify(body),
  })) as unknown as LayoutCache;
}

export async function postUserAction(
  body: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE}${userPath}/user-actions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      Accept: "application/json",
    },
    body: JSON.stringify(body),
  });
  if (response.status === 404) throw new AgentError("USER_ACTIONS_UNAVAILABLE");
  if (!response.ok)
    throw new AgentError(`User action failed (${response.status}).`);
  return (await response.json()) as Record<string, unknown>;
}

export function viewportFromLayout(layout: LayoutDocument): Viewport {
  const { center, zoom, label } = layout.map.viewport;
  return {
    latitude: center.lat,
    longitude: center.lng,
    zoom,
    label:
      label ??
      (Math.abs(center.lat - 1.3521) < 0.0001 &&
      Math.abs(center.lng - 103.8198) < 0.0001
        ? "Singapore"
        : undefined),
  };
}

export function viewportPayload(viewport: Viewport) {
  return {
    center: { lat: viewport.latitude, lng: viewport.longitude },
    zoom: viewport.zoom,
    ...(viewport.label ? { label: viewport.label } : {}),
  };
}

export async function chatContext(
  cache: LayoutCache,
  viewport: Viewport,
  status: SyncStatus,
  chatMode: "preview" | "expanded",
) {
  const layout: LayoutDocument = {
    ...cache.layout,
    chrome: { chat: { mode: chatMode } },
  };
  return {
    schema_version: cache.layout.schema_version,
    revision: cache.revision,
    layout_hash: await layoutHash(layout),
    sync_status: status,
    viewport_summary: viewportPayload(viewport),
    chat: { mode: chatMode },
    capabilities: ["map.set_viewport"],
  };
}

export type { LayoutDocument, Viewport };
