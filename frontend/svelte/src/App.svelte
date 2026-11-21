<script lang="ts">
  import { onMount } from "svelte";
  import { Compass, LocateFixed, LogOut, Map, Navigation } from "@lucide/svelte";
  import ChatPanel from "./components/ChatPanel.svelte";
  import MapView from "./components/MapView.svelte";
  import {
    chatContext,
    clearHistory,
    fetchHistory,
    fetchToolReadiness,
    streamChat,
    syncLayout,
    viewportFromLayout,
    viewportPayload,
  } from "./lib/agent";
  import { loadLayout, saveLayout, withViewport } from "./lib/layout";
  import { parseRoutes } from "./lib/routes";
  import { DEFAULT_VIEWPORT, defaultLayout } from "./lib/types";
  import type {
    ChatMessage,
    EvaluationProgress,
    LayoutCache,
    MapPlace,
    MapRoute,
    ToolActivity,
    ToolReadiness,
    SyncStatus,
    Viewport,
  } from "./lib/types";

  let { accountId, onLogout }: { accountId: string; onLogout: () => Promise<void> } = $props();

  let messages = $state<ChatMessage[]>([]);
  let confirmSignOut = $state(false);
  let places = $state<MapPlace[]>([]);
  let routes = $state<MapRoute[]>([]);
  let toolActivity = $state<ToolActivity[]>([]);
  let evaluationProgress = $state<EvaluationProgress[]>([]);
  let evaluationComment = $state("");
  let evaluationCommentTimer: ReturnType<typeof setTimeout> | undefined;
  let toolReadiness = $state<ToolReadiness[]>([]);
  let apiStatus = $state<"loading" | "ready" | "unavailable">("loading");

  async function refreshToolReadiness(): Promise<void> {
    apiStatus = "loading";
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    try {
      const tools = await fetchToolReadiness(controller.signal);
      if (mounted) { toolReadiness = tools; apiStatus = "ready"; }
    } catch {
      if (mounted) { toolReadiness = []; apiStatus = "unavailable"; }
    } finally { clearTimeout(timeout); }
  }
  let viewport = $state<Viewport>(DEFAULT_VIEWPORT);
  let cache = $state<LayoutCache>({
    revision: 0,
    layout_hash: "",
    layout: defaultLayout(),
  });
  let expanded = $state(false);
  let loadingHistory = $state(true);
  let loadingOlderHistory = $state(false);
  let hasOlderHistory = $state(false);
  let olderHistoryCursor = $state<string | null>(null);
  let sending = $state(false);
  let syncStatus = $state<SyncStatus>("ok");
  let viewportTimer: ReturnType<typeof setTimeout> | undefined;
  let localTimer: ReturnType<typeof setTimeout> | undefined;
  let mounted = false;
  let historyGeneration = 0;

  async function clearConversation(): Promise<void> {
    if (sending) throw new Error("Wait for the current response to finish.");
    await clearHistory();
    historyGeneration++;
    messages = [];
    hasOlderHistory = false;
    olderHistoryCursor = null;
    loadingOlderHistory = false;
    loadingHistory = false;
  }

  onMount(() => {
    mounted = true;
    void refreshToolReadiness();
    void hydrate();
    return () => {
      mounted = false;
      clearTimeout(viewportTimer);
      clearTimeout(localTimer);
      clearTimeout(evaluationCommentTimer);
    };
  });

  async function hydrate(): Promise<void> {
    const generation = historyGeneration;
    cache = await loadLayout(accountId);
    viewport = viewportFromLayout(cache.layout);
    await Promise.all([
      fetchHistory()
        .then((page) => {
          if (mounted && generation === historyGeneration) {
            messages = page.messages;
            hasOlderHistory = page.has_more;
            olderHistoryCursor = page.next_cursor;
          }
        })
        .catch(() => {}),
    ]);
    if (!mounted) return;
    loadingHistory = false;
  }

  async function loadOlderHistory(): Promise<void> {
    if (loadingOlderHistory || !hasOlderHistory || !olderHistoryCursor) return;
    loadingOlderHistory = true;
    const generation = historyGeneration;
    try {
      const page = await fetchHistory(olderHistoryCursor);
      if (!mounted || generation !== historyGeneration) return;
      const existing = new Set(messages.map((message) => message.id));
      messages = [
        ...page.messages.filter((message) => !existing.has(message.id)),
        ...messages,
      ];
      hasOlderHistory = page.has_more;
      olderHistoryCursor = page.next_cursor;
    } finally {
      loadingOlderHistory = false;
    }
  }

  function updateViewport(next: Viewport): void {
    viewport = next;
    syncStatus = "pending";
    void withViewport(cache, next).then((updated) => {
      cache = updated;
    });
    clearTimeout(localTimer);
    localTimer = setTimeout(() => saveLayout(accountId, cache), 220);
    clearTimeout(viewportTimer);
    viewportTimer = setTimeout(() => {
      void reportViewport(next);
    }, 320);
  }

  async function reportViewport(next: Viewport): Promise<void> {
    try {
      const result = await syncLayout({
        client_revision: cache.revision,
        proposed_delta: { op: "map.set_viewport", source: "user", payload: viewportPayload(next) },
      });
      cache = result;
      if (!result.accepted) {
        syncStatus = "conflict";
        viewport = viewportFromLayout(result.layout);
        saveLayout(accountId, cache);
        return;
      }
      syncStatus = "ok";
      saveLayout(accountId, cache);
    } catch {
      syncStatus = "offline";
    }
  }

  async function fullSync(): Promise<void> {
    const result = await syncLayout({
      sync_mode: "full",
      client_revision: cache.revision,
      layout: cache.layout,
      layout_hash: cache.layout_hash,
      pending_deltas: [],
    });
    cache = result;
    viewport = viewportFromLayout(result.layout);
    syncStatus = "ok";
    saveLayout(accountId, cache);
  }

  function toggleExpanded(): void {
    expanded = !expanded;
  }

  async function send(message: string): Promise<void> {
    if (sending) return;
    sending = true;
    toolActivity = [];
    evaluationProgress = [];
    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      text: message,
      timestamp: new Date().toISOString(),
      source: "current",
    };
    const responseMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "assistant",
      text: "",
      timestamp: new Date().toISOString(),
      source: "current",
    };
    messages = [...messages, userMessage, responseMessage];
    const responseId = responseMessage.id;
    let accumulated = "";
    let searchResultsShown = false;
    let routeShown = false;
    const routeArguments = new globalThis.Map<string, Record<string, unknown>>();
    let lastPaint = 0;
    let paintFrame = 0;

    const updateResponse = (value: string, force = false) => {
      accumulated = value;
      const now = performance.now();
      if (!force && now - lastPaint < 45) {
        if (!paintFrame)
          paintFrame = requestAnimationFrame(() => {
            paintFrame = 0;
            lastPaint = performance.now();
            replaceMessage(responseId, accumulated);
          });
        return;
      }
      lastPaint = now;
      replaceMessage(responseId, value);
    };

    try {
      for await (const event of streamChat(
        message,
        await chatContext(
          cache,
          viewport,
          syncStatus,
          expanded ? "expanded" : "preview",
        ),
      )) {
        if (!mounted) return;
        if (event.type === "evaluation_progress") {
          if (typeof event.wave_id === "string" && (event.phase === "criteria_generation" || event.phase === "judging") && (event.status === "started" || event.status === "completed" || event.status === "failed")) {
            evaluationProgress = evaluationProgress.filter((item) => item.waveId !== event.wave_id || item.phase !== event.phase);
            if (event.status === "started") evaluationProgress = [...evaluationProgress, { waveId: event.wave_id, phase: event.phase }];
          }
        } else if (event.type === "evaluation_comment") {
          if (typeof event.wave_id === "string" && typeof event.comment === "string" && event.comment.trim()) {
            clearTimeout(evaluationCommentTimer);
            evaluationComment = event.comment.trim();
            evaluationCommentTimer = setTimeout(() => { evaluationComment = ""; }, 2000);
          }
        } else if (event.type === "assistant_delta") {
          if (event.delta) toolActivity = [];
          updateResponse(accumulated + event.delta);
        } else if (event.type === "tool_call_start") {
          if (event.name === "routes_compute" && event.run_id) routeArguments.set(event.run_id, event.arguments);
          toolActivity = [...toolActivity, { id: event.run_id ?? crypto.randomUUID(), name: event.name, done: false }];
        } else if (event.type === "tool_call_end") {
          const matched = event.run_id
            ? toolActivity.find((tool) => tool.id === event.run_id)
            : toolActivity.find((tool) => tool.name === event.name && !tool.done);
          if (matched) toolActivity = toolActivity.map((tool) => tool.id === matched.id ? { ...tool, done: true } : tool);
          else toolActivity = [...toolActivity, { id: event.run_id ?? crypto.randomUUID(), name: event.name, done: true }];
          if (event.name === "routes_compute") {
            try {
              const parsed = parseRoutes(event.output);
              const args = (event.run_id && routeArguments.get(event.run_id)) || event.arguments;
              const nameFor = (value: unknown): string | undefined => {
                if (!value || typeof value !== "object") return undefined;
                const waypoint = value as { address?: unknown; place_id?: unknown };
                if (typeof waypoint.place_id === "string") return places.find((place) => place.id === waypoint.place_id)?.name;
                return typeof waypoint.address === "string" ? waypoint.address : undefined;
              };
              if (parsed.length) { routes = parsed.map((route) => ({ ...route, originName: nameFor(args?.origin), destinationName: nameFor(args?.destination) })); routeShown = true; }
            } catch { /* Preserve the last valid route. */ }
          }
          if (
          (event.name === "places_text_search" || event.name === "places_search_nearby")) {
          try {
            const result: unknown = typeof event.output === "string" ? JSON.parse(event.output) : event.output;
            if (result && typeof result === "object" && Array.isArray((result as { places?: unknown }).places)) {
              places = (result as { places: unknown[] }).places.flatMap((item, index): MapPlace[] => {
                if (!item || typeof item !== "object") return [];
                const place = item as { id?: unknown; displayName?: { text?: unknown }; formattedAddress?: unknown; location?: { latitude?: unknown; longitude?: unknown } };
                const lat = place.location?.latitude, lng = place.location?.longitude;
                if (typeof lat !== "number" || !Number.isFinite(lat) || lat < -90 || lat > 90 || typeof lng !== "number" || !Number.isFinite(lng) || lng < -180 || lng > 180) return [];
                return [{ id: typeof place.id === "string" ? place.id : String(index), name: typeof place.displayName?.text === "string" ? place.displayName.text : "Place", latitude: lat, longitude: lng, address: typeof place.formattedAddress === "string" ? place.formattedAddress : undefined }];
              });
              searchResultsShown = places.length > 0;
            }
          } catch { /* An unsuccessful or malformed tool result leaves the map unchanged. */ }
          }
        }
        else if (event.type === "client_command") {
          await applyClientCommand(event);
          if (event.command === "map.set_viewport") {
            if (routeShown) routes = [...routes];
            else if (searchResultsShown) places = [...places];
          }
        }
        else if (event.type === "assistant_done") {
          if (event.layout_hash && event.layout_hash !== cache.layout_hash) {
            syncStatus = "conflict";
            try {
              await fullSync();
            } catch {
              syncStatus = "offline";
            }
          } else if (
            event.layout_revision !== undefined &&
            event.layout_revision !== cache.revision
          ) {
            cache = { ...cache, revision: event.layout_revision };
            saveLayout(accountId, cache);
          }
        }
      }
      updateResponse(
        accumulated || "I couldn’t produce a response. Please try again.",
        true,
      );
    } catch (error) {
      updateResponse(
        error instanceof Error
          ? error.message
          : "Could not reach the travel agent.",
        true,
      );
    } finally {
      if (paintFrame) cancelAnimationFrame(paintFrame);
      if (mounted) { sending = false; toolActivity = []; evaluationProgress = []; }
    }
  }

  function replaceMessage(id: string, text: string): void {
    messages = messages.map((message) =>
      message.id === id ? { ...message, text } : message,
    );
  }

  async function applyClientCommand(
    event: Extract<
      import("./lib/types").StreamEvent,
      { type: "client_command" }
    >,
  ): Promise<void> {
    if (event.command !== "map.set_viewport") return;
    if (
      event.base_revision !== undefined &&
      event.base_revision !== cache.revision &&
      cache.revision !== 0
    ) {
      syncStatus = "conflict";
      try {
        await fullSync();
      } catch {
        syncStatus = "offline";
        return;
      }
    }
    const center = event.payload.center as
      { lat?: number; lng?: number } | undefined;
    const lat = Number(center?.lat);
    const lng = Number(center?.lng);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
    const next = {
      latitude: lat,
      longitude: lng,
      zoom: Number(event.payload.zoom ?? viewport.zoom),
      label:
        typeof event.payload.label === "string"
          ? event.payload.label
          : undefined,
    };
    viewport = next;
    cache = await withViewport(cache, next);
    saveLayout(accountId, cache);
    try {
      cache = await syncLayout({
        client_revision: cache.revision,
        applied: { command_id: event.command_id, ok: true },
      });
      syncStatus = "ok";
      saveLayout(accountId, cache);
    } catch {
      syncStatus = "offline";
    }
  }
</script>

<svelte:head>
  <title>FOGG — Plan somewhere wonderful</title>
</svelte:head>

<main class="app-shell">
  <MapView {viewport} {places} {routes} onViewportChange={updateViewport} />
  {#if routes.length}
    <div class="route-summary">
      <strong>Route</strong>
      {#if routes[0].duration && Number.isFinite(Number(routes[0].duration.replace(/s$/, "")))}
        <span>{Math.round(Number(routes[0].duration.replace(/s$/, "")) / 60)} min</span>
      {/if}
      {#if routes[0].distanceMeters !== undefined}<span>{(routes[0].distanceMeters / 1000).toFixed(1)} km</span>{/if}
    </div>
  {/if}
  <div class="map-wash"></div>

  <div class="topbar">
    <button class="auth-logout" type="button" onclick={() => { confirmSignOut = true; }} aria-label="Sign out" title="Sign out"><LogOut size={17} /></button>
    <a class="wordmark" href="/" aria-label="FOGG home"
      ><span class="logo-symbol"><Compass size={20} strokeWidth={1.6} /></span
      >fogg<span class="wordmark-period">.</span></a
    >
    <div class="location-pill">
      <span class="location-pulse"></span><span
        >{viewport.label ?? "Exploring map"}</span
      ><span class="pill-divider"></span><span class="coordinates"
        >{viewport.latitude.toFixed(2)}° N</span
      >
    </div>
  </div>

  <div class="map-hint">
    <span class="hint-icon"><Navigation size={13} /></span>Drag the map to
    explore
  </div>

  <button
    class="map-action"
    aria-label="Center on Singapore"
    title="Center on Singapore"
    onclick={() => {
      updateViewport(DEFAULT_VIEWPORT);
    }}><LocateFixed size={18} /></button
  >

  <div class:expanded class="chat-position">
    <ChatPanel
      {messages}
      {expanded}
      {sending}
      {toolActivity}
      {evaluationProgress}
      {evaluationComment}
      {toolReadiness}
      {apiStatus}
      onRefreshTools={refreshToolReadiness}
      onClear={clearConversation}
      onRequestSignOut={() => { confirmSignOut = true; }}
      {loadingHistory}
      loadingOlder={loadingOlderHistory}
      hasOlderMessages={hasOlderHistory}
      {syncStatus}
      onExpand={toggleExpanded}
      onLoadOlder={loadOlderHistory}
      onSend={send}
    />
  </div>

  <div class="map-brand"><Map size={13} /> Map data © OpenStreetMap</div>
</main>
{#if confirmSignOut}
  <div class="confirm-overlay">
    <div class="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="signout-title" tabindex="-1">
      <h2 id="signout-title">Sign out?</h2>
      <p>You’ll need to sign in again to continue.</p>
      <button type="button" onclick={() => { confirmSignOut = false; }}>Cancel</button>
      <button type="button" onclick={async () => { confirmSignOut = false; await onLogout(); }}>Sign out</button>
    </div>
  </div>
{/if}
