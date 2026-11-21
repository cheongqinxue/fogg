<script lang="ts">
  import { tick } from "svelte";
  import { fade } from "svelte/transition";
  import { marked } from "marked";
  import DOMPurify from "dompurify";
  import { saveToolCredentials, setToolActive } from "../lib/agent";
  import SlashInteractive from "./SlashInteractive.svelte";
  import SlideConfirm from "./SlideConfirm.svelte";
  import type { SlashItem } from "../lib/slash/types";
  import {
    ArrowDown,
    ArrowUp,
    Check,
    Expand,
    MapPinned,
    MessageCircle,
    Minus,
    Sparkles,
    Trash2,
  } from "@lucide/svelte";
  import type { ChatMessage, EvaluationProgress, SyncStatus, ToolActivity, ToolReadiness } from "../lib/types";

  let {
    messages,
    expanded,
    sending,
    toolActivity,
    evaluationProgress,
    evaluationComment,
    toolReadiness,
    apiStatus,
    onRefreshTools,
    loadingHistory,
    loadingOlder = false,
    hasOlderMessages = false,
    syncStatus,
    onExpand,
    onLoadOlder,
    onSend,
    onClear,
  }: {
    messages: ChatMessage[];
    expanded: boolean;
    sending: boolean;
    toolActivity: ToolActivity[];
    evaluationProgress: EvaluationProgress[];
    evaluationComment: string;
    toolReadiness: ToolReadiness[];
    apiStatus: "loading" | "ready" | "unavailable";
    onRefreshTools: () => Promise<void>;
    loadingHistory: boolean;
    loadingOlder?: boolean;
    hasOlderMessages?: boolean;
    syncStatus: SyncStatus;
    onExpand: () => void;
    onLoadOlder?: () => Promise<void>;
    onSend: (message: string) => Promise<void>;
    onClear: () => Promise<void>;
  } = $props();

  let draft = $state("");
  let clearOpen = $state(false);
  function openClear() { if (!sending) { clearOpen = true; slashDismissed = true; draft = ""; } }
  let slashMenu = $state<SlashInteractive>();
  let slashDismissed = $state(false);
  let toolSaveError = $state("");
  let toolSaving = $state(false);
  async function toggleTool(name: string, active: boolean) {
    if (toolSaving) return;
    toolSaving = true; toolSaveError = "";
    try { await setToolActive(name, active); }
    catch (error) { toolSaveError = error instanceof Error ? error.message : "Could not update tool."; }
    finally { await onRefreshTools(); toolSaving = false; }
  }
  async function toggleToolGroup(tools: typeof toolReadiness, active: boolean) {
    if (toolSaving) return;
    toolSaving = true; toolSaveError = "";
    try {
      for (const tool of tools) {
        if (tool.active !== active) await setToolActive(tool.name, active);
      }
    } catch (error) {
      toolSaveError = error instanceof Error ? error.message : "Could not update tool group.";
    } finally {
      await onRefreshTools();
      toolSaving = false;
    }
  }
  async function submitCredentials(values: Record<string, string>) {
    try { await saveToolCredentials(values); }
    finally { await onRefreshTools(); }
  }
  const slashOpen = $derived(draft.startsWith("/") && !draft.includes("\n") && !slashDismissed);
  const toolGroups = $derived.by(() => {
    const definitions = [
      { id: "google-maps", title: "Google Maps", description: "Places and route tools", matches: (provider: string) => provider === "google_maps" },
      { id: "web-search", title: "Web Search", description: "Search the web and extract pages", matches: (provider: string) => ["tavily", "exa", "firecrawl"].includes(provider) },
      { id: "local", title: "Local tools", description: "Tools that do not need provider credentials", matches: (_provider: string) => false },
    ];
    return definitions.flatMap((group) => {
      const members = toolReadiness.filter((tool) => group.id === "local"
        ? tool.credentials.length === 0
        : tool.credentials.some((credential) => group.matches(credential.provider)));
      if (!members.length) return [];
      const active = members.every((tool) => tool.active);
      const ready = members.every((tool) => tool.status === "ready");
      const credentials = [...new Map(members.flatMap((tool) => tool.credentials).map((credential) => [credential.provider, credential])).values()];
      return [{
        id: group.id,
        title: group.title,
        description: group.description,
        trailing: `[${members.filter((tool) => tool.active).length}/${members.length}]`,
        children: [
          { id: "group-active", title: "Enable all tools", description: ready ? "Toggle this entire group" : "Add credentials before enabling this group", indicator: { kind: "checkbox" as const, active }, disabled: toolSaving || (!active && !ready), onToggle: (next: boolean) => toggleToolGroup(members, next) },
          ...(credentials.length ? [group.id === "web-search"
            ? { id: "credentials", title: "Provide credentials", description: "Choose a provider", children: credentials.map((credential) => ({
                id: credential.provider,
                title: credential.label,
                description: credential.configured ? "Configured" : "Not configured",
                fields: [{ id: credential.provider, label: credential.label }],
                onSubmit: submitCredentials,
              })) }
            : { id: "credentials", title: "Provide credentials", description: "Credentials shared by this group", fields: credentials.map((credential) => ({ id: credential.provider, label: `${credential.label}${credential.configured ? " (configured)" : ""}` })), onSubmit: submitCredentials }] : []),
          ...members.map((tool) => ({
            id: tool.name,
            title: tool.name,
            description: tool.description,
            indicator: { kind: "status" as const, active: tool.active },
            children: [
              { id: "enabled", title: "Enable tool", description: tool.message ?? "Enable or disable this tool", indicator: { kind: "checkbox" as const, active: tool.active }, disabled: toolSaving || (!tool.active && tool.status !== "ready"), onToggle: (next: boolean) => toggleTool(tool.name, next) },
            ],
          })),
        ],
      }];
    });
  });
  const slashItems = $derived<SlashItem[]>([{ id: "clear", title: "clear", description: "Clear conversation history", disabled: sending, action: openClear }, {
    id: "tools", title: "tools", description: "View tool configuration",
    children: toolReadiness.length ? toolGroups : [{ id: "unavailable", title: apiStatus === "loading" ? "Checking tools…" : "API server unavailable", description: "Refresh tool status to try again", action: () => void onRefreshTools() }],
  }]);
  let transcript: HTMLDivElement;
  let composer: HTMLTextAreaElement;
  let hasOverflow = $state(false);
  let nearBottom = true;
  let requestingOlder = false;
  function displayText(text: string): string {
    return text.replace(/(?:\u001b|␛)\[[0-?]*[ -/]*[@-~]/g, "");
  }
  function renderMarkdown(text: string): string {
    return DOMPurify.sanitize(marked.parse(displayText(text), { async: false }));
  }
  const visibleMessages = $derived(expanded ? messages : messages.slice(-2));
  const displayedMessages = $derived.by(() => {
    let previousDay = "";
    return visibleMessages.map((message) => {
      const dayKey = singaporeDayKey(message.timestamp);
      const showDay = dayKey !== previousDay;
      previousDay = dayKey;
      return { message, dayKey, dayLabel: singaporeDayLabel(message.timestamp), showDay };
    });
  });

  function singaporeDayKey(timestamp: string): string {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Singapore",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(new Date(timestamp));
    return parts.filter((part) => part.type !== "literal").map((part) => part.value).join("-");
  }

  function singaporeDayLabel(timestamp: string): string {
    const key = singaporeDayKey(timestamp);
    const today = singaporeDayKey(new Date().toISOString());
    const yesterday = singaporeDayKey(new Date(Date.now() - 86_400_000).toISOString());
    if (key === today) return "Today";
    if (key === yesterday) return "Yesterday";
    return new Intl.DateTimeFormat("en-SG", {
      timeZone: "Asia/Singapore",
      weekday: "long",
      day: "numeric",
      month: "long",
      year: "numeric",
    }).format(new Date(timestamp));
  }

  $effect(() => {
    messages.length;
    const lastText = messages[messages.length - 1]?.text;
    if (lastText !== undefined && expanded && nearBottom) {
      void tick().then(() =>
        transcript?.scrollTo({
          top: transcript.scrollHeight,
          behavior: "auto",
        }),
      );
    }
  });

  function resizeComposer(): void {
    if (!composer) return;
    composer.style.height = "0px";
    const maxHeight = 116;
    composer.style.height = `${Math.min(composer.scrollHeight, maxHeight)}px`;
    hasOverflow = composer.scrollHeight > maxHeight;
  }

  function onTranscriptScroll(): void {
    if (!transcript) return;
    nearBottom =
      transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight <
      64;
    if (
      expanded && transcript.scrollTop < 48 && hasOlderMessages &&
      !loadingOlder && !requestingOlder && onLoadOlder
    ) {
      const previousHeight = transcript.scrollHeight;
      const previousTop = transcript.scrollTop;
      requestingOlder = true;
      void onLoadOlder()
        .then(() => tick().then(() => {
          if (transcript)
            transcript.scrollTop = previousTop + transcript.scrollHeight - previousHeight;
        }))
        .catch(() => {})
        .finally(() => { requestingOlder = false; });
    }
  }

  async function send(): Promise<void> {
    const value = draft.trim();
    if (!value || sending || slashOpen || clearOpen) return;
    draft = "";
    await tick();
    resizeComposer();
    await onSend(value);
  }

  function onKeydown(event: KeyboardEvent): void {
    if (slashOpen && slashMenu?.handleKey(event)) return;
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      void send();
    }
  }
</script>

<section class:expanded class:menu-open={slashOpen} class="chat-card" aria-label="FOGG travel assistant">
  <header class="chat-header">
    <div class="brand-mark" aria-label="FOGG">
      <span class="brand-icon"><MapPinned size={17} strokeWidth={1.8} /></span>
      <span class="brand-word">FOGG</span>
    </div>
    <div class="header-context">
      <span class="status-dot" class:offline={syncStatus === "offline"}></span>
      <span>{syncStatus === "offline" ? "Offline" : "Trip planner"}</span>
    </div>
    <button class="icon-button expand-button" type="button" aria-label="Clear conversation" title="Clear conversation" disabled={sending} onclick={openClear}><Trash2 size={16} /></button>
    <button
      class="expand-button icon-button"
      type="button"
      aria-label={expanded ? "Collapse chat" : "Expand chat"}
      onclick={onExpand}
    >
      {#if expanded}<Minus size={19} />{:else}<Expand size={17} />{/if}
    </button>
  </header>

  <details class="tool-readiness">
    <summary>Tools · {apiStatus === "loading" ? "Checking…" : apiStatus === "unavailable" ? "API server unavailable" : `${toolReadiness.filter((tool) => tool.status === "ready").length}/${toolReadiness.length} ready`}</summary>
    {#if apiStatus === "unavailable"}
      <p>Could not reach the API server.</p>
    {:else if apiStatus === "ready"}
      <ul>{#each toolReadiness as tool}<li><strong>{tool.name}</strong> · {tool.status === "ready" ? "Ready" : "Needs configuration"}{#if tool.status === "needs_configuration" && tool.message}<span>{tool.message}</span>{/if}</li>{/each}</ul>
    {/if}
    <button type="button" onclick={() => void onRefreshTools()} disabled={apiStatus === "loading"}>Refresh</button>
  </details>

  <div
    class:preview={!expanded}
    class="transcript"
    bind:this={transcript}
    onscroll={onTranscriptScroll}
  >
    {#if loadingHistory}
      <div class="loading-history">
        <span class="loading-orb"></span>Picking up your trip…
      </div>
    {:else if messages.length === 0}
      <div class="welcome-message">
        <div class="welcome-icon"><Sparkles size={17} /></div>
        <div>
          <strong>Your next trip starts here.</strong>
          <p>Tell me where you’re dreaming of going.</p>
        </div>
      </div>
    {:else}
      {#if loadingOlder}<div class="history-loading-older">Loading earlier messages…</div>{/if}
      {#each displayedMessages as entry (entry.message.id)}
        {#if entry.showDay}<div class="day-separator"><span>{entry.dayLabel}</span></div>{/if}
        <article
          class:from-user={entry.message.role === "user"}
          class:from-history={entry.message.source === "history"}
          class="message-row"
        >
          {#if entry.message.role === "assistant"}
            <span class="assistant-avatar"><Sparkles size={13} /></span>
          {/if}
          <div class="message-bubble">
            {#if entry.message.text}
              {#if entry.message.role === "assistant"}<div class="markdown">{@html renderMarkdown(entry.message.text)}</div>{:else}<p>{displayText(entry.message.text)}</p>{/if}
            {:else}<span
                class="thinking-dots"><i></i><i></i><i></i></span
              >{/if}
          </div>
        </article>
      {/each}
      {#if sending && messages[messages.length - 1]?.role !== "assistant"}
        <div class="message-row">
          <span class="assistant-avatar"><Sparkles size={13} /></span>
          <div class="message-bubble">
            <span class="thinking-dots"><i></i><i></i><i></i></span>
          </div>
        </div>
      {/if}
    {/if}
  </div>

  {#if toolActivity.length || evaluationProgress.length}
    <div class="tool-activity" aria-label="Tool activity" out:fade={{ duration: 250 }}>
      {#each toolActivity as tool (tool.id)}
        <span class="tool-item">
          {#if tool.done}<span class="tool-done"><Check size={10} strokeWidth={3} /></span>{:else}<span class="tool-running"></span>{/if}
          <span>{tool.name}</span>
        </span>
      {/each}
      {#each evaluationProgress as progress (`${progress.waveId}:${progress.phase}`)}
        <span class="tool-item"><span class="tool-running"></span><span>{progress.phase === "criteria_generation" ? "Preparing evaluation" : "Evaluating results"}</span></span>
      {/each}
    </div>
  {/if}

  {#if evaluationComment}<div class="evaluation-comment" role="status" out:fade={{ duration: 250 }}>{evaluationComment}</div>{/if}

  {#if !expanded && messages.length > 2}
    <button class="history-link" type="button" onclick={onExpand}
      ><MessageCircle size={13} /> View conversation <ArrowDown
        size={13}
      /></button
    >
  {/if}

  {#if slashOpen}
    {#if toolSaveError}<p class="slash-error" role="alert">{toolSaveError}</p>{/if}
    <SlashInteractive bind:this={slashMenu} items={slashItems} query={draft.slice(1)} onClose={() => { slashDismissed = true; }} onNavigate={() => { draft = "/"; }} />
  {/if}
  <form
    class="composer"
    onsubmit={(event) => {
      event.preventDefault();
      void send();
    }}
  >
    <textarea
      bind:this={composer}
      bind:value={draft}
      oninput={() => { slashDismissed = false; resizeComposer(); }}
      onkeydown={onKeydown}
      rows="1"
      placeholder="Where would you like to go?"
      aria-label="Message the travel assistant"
      style:overflow-y={hasOverflow ? "auto" : "hidden"}></textarea>
    <button
      class:ready={draft.trim().length > 0}
      class="send-button"
      type="submit"
      aria-label="Send message"
      disabled={!draft.trim() || sending || slashOpen}
    >
      {#if sending}<span class="send-spinner"></span>{:else}<ArrowUp
          size={18}
          strokeWidth={2.3}
        />{/if}
    </button>
  </form>
  <footer class="chat-footer">
    <span>AI can make mistakes. Verify important details.</span><kbd>↵</kbd
    ><span>to send</span>
  </footer>
</section>
{#if clearOpen}<SlideConfirm title="Clear conversation?" description="This clears the conversation history. Your map layout stays saved." onConfirm={onClear} onCancel={() => { clearOpen = false; }} />{/if}
