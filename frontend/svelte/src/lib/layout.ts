import type { LayoutCache, LayoutDocument, Viewport } from "./types";
import { defaultLayout } from "./types";
import { sha256 } from "@noble/hashes/sha256";
import { bytesToHex } from "@noble/hashes/utils";

const keyFor = (accountId: string) => `fogg.layout.v1.${accountId}`;

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    const object = value as Record<string, unknown>;
    return `{${Object.keys(object)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonical(object[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

export async function layoutHash(layout: LayoutDocument): Promise<string> {
  const bytes = new TextEncoder().encode(canonical(layout));
  return bytesToHex(sha256(bytes));
}

export async function loadLayout(accountId: string): Promise<LayoutCache> {
  try {
    const cached = localStorage.getItem(keyFor(accountId));
    if (cached) {
      const decoded = JSON.parse(cached) as LayoutCache;
      if (decoded.layout?.schema_version === 1) return decoded;
    }
  } catch {
    // Start from defaults if local storage is unavailable or malformed.
  }
  const layout = defaultLayout();
  return { revision: 0, layout_hash: await layoutHash(layout), layout };
}

export function saveLayout(accountId: string, cache: LayoutCache): void {
  try {
    localStorage.setItem(keyFor(accountId), JSON.stringify(cache));
  } catch {
    // Browser storage may be disabled; keep the session usable in memory.
  }
}

export async function withViewport(
  cache: LayoutCache,
  viewport: Viewport,
): Promise<LayoutCache> {
  const layout: LayoutDocument = {
    ...cache.layout,
    map: {
      viewport: {
        center: { lat: viewport.latitude, lng: viewport.longitude },
        zoom: viewport.zoom,
        ...(viewport.label ? { label: viewport.label } : {}),
      },
    },
  };
  return { ...cache, layout, layout_hash: await layoutHash(layout) };
}

export function withChatMode(
  cache: LayoutCache,
  mode: "preview" | "expanded",
): LayoutCache {
  return {
    ...cache,
    layout: { ...cache.layout, chrome: { chat: { mode } } },
  };
}
