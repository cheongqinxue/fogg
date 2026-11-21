export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  timestamp: string;
  source?: "history" | "current";
}

export interface MessageHistoryPage {
  messages: ChatMessage[];
  has_more: boolean;
  next_cursor: string | null;
}

export interface Viewport {
  latitude: number;
  longitude: number;
  zoom: number;
  label?: string;
}

export interface MapPlace {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
  address?: string;
}

export interface MapRoute {
  points: [number, number][];
  distanceMeters?: number;
  duration?: string;
  originName?: string;
  destinationName?: string;
}

export interface ToolActivity {
  id: string;
  name: string;
  done: boolean;
}

export interface EvaluationProgress {
  waveId: string;
  phase: "criteria_generation" | "judging";
}

export interface ToolReadiness {
  name: string;
  description: string;
  active: boolean;
  status: "ready" | "needs_configuration";
  message?: string;
  credentials: { provider: string; label: string; configured: boolean }[];
}

export interface LayoutDocument {
  schema_version: number;
  map: {
    viewport: {
      center: { lat: number; lng: number };
      zoom: number;
      label?: string;
    };
  };
  chrome: { chat: { mode: "preview" | "expanded" } };
  workspace: { slots: Record<string, unknown>[] };
}

export type StreamEvent =
  | { type: "assistant_delta"; delta: string }
  | { type: "evaluation_progress"; wave_id: string; phase: "criteria_generation" | "judging"; status: "started" | "completed" | "failed" }
  | { type: "evaluation_comment"; wave_id: string; comment: string }
  | { type: "assistant_done"; layout_revision?: number; layout_hash?: string }
  | {
      type: "client_command";
      command_id: string;
      base_revision?: number;
      command: string;
      payload: Record<string, unknown>;
    }
  | {
      type: "tool_call_start";
      name: string;
      arguments: Record<string, unknown>;
      run_id?: string | null;
    }
  | { type: "tool_call_end"; name: string; output?: unknown; arguments?: Record<string, unknown>; run_id?: string | null };

export type SyncStatus = "ok" | "pending" | "offline" | "conflict";

export interface LayoutCache {
  revision: number;
  layout_hash: string;
  layout: LayoutDocument;
}

export interface LayoutSyncResult extends LayoutCache {
  accepted: boolean;
  reject_reason?: string | null;
}

export const DEFAULT_VIEWPORT: Viewport = {
  latitude: 1.3521,
  longitude: 103.8198,
  zoom: 11.5,
  label: "Singapore",
};

export function defaultLayout(): LayoutDocument {
  return {
    schema_version: 1,
    map: {
      viewport: {
        center: {
          lat: DEFAULT_VIEWPORT.latitude,
          lng: DEFAULT_VIEWPORT.longitude,
        },
        zoom: DEFAULT_VIEWPORT.zoom,
      },
    },
    chrome: { chat: { mode: "preview" } },
    workspace: { slots: [] },
  };
}
