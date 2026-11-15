<script lang="ts">
  import { tick } from "svelte";
  import { fade } from "svelte/transition";
  import { marked } from "marked";
  import DOMPurify from "dompurify";
  import {
    ArrowDown,
    ArrowUp,
    Check,
    Expand,
    MapPinned,
    MessageCircle,
    Minus,
    Sparkles,
  } from "@lucide/svelte";
  import type { ChatMessage, SyncStatus, ToolActivity } from "../lib/types";

  let {
    messages,
    expanded,
    sending,
    toolActivity,
    loadingHistory,
    loadingOlder = false,
    hasOlderMessages = false,
    syncStatus,
    onExpand,
    onLoadOlder,
    onSend,
  }: {
    messages: ChatMessage[];
    expanded: boolean;
    sending: boolean;
    toolActivity: ToolActivity[];
    loadingHistory: boolean;
    loadingOlder?: boolean;
    hasOlderMessages?: boolean;
    syncStatus: SyncStatus;
    onExpand: () => void;
    onLoadOlder?: () => Promise<void>;
    onSend: (message: string) => Promise<void>;
  } = $props();

  let draft = $state("");
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
    if (!value || sending) return;
    draft = "";
    await tick();
    resizeComposer();
    await onSend(value);
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      void send();
    }
  }
</script>

<section class:expanded class="chat-card" aria-label="FOGG travel assistant">
  <header class="chat-header">
    <div class="brand-mark" aria-label="FOGG">
      <span class="brand-icon"><MapPinned size={17} strokeWidth={1.8} /></span>
      <span class="brand-word">FOGG</span>
    </div>
    <div class="header-context">
      <span class="status-dot" class:offline={syncStatus === "offline"}></span>
      <span>{syncStatus === "offline" ? "Offline" : "Trip planner"}</span>
    </div>
    <button
      class="expand-button icon-button"
      type="button"
      aria-label={expanded ? "Collapse chat" : "Expand chat"}
      onclick={onExpand}
    >
      {#if expanded}<Minus size={19} />{:else}<Expand size={17} />{/if}
    </button>
  </header>

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

  {#if toolActivity.length}
    <div class="tool-activity" aria-label="Tool activity" out:fade={{ duration: 250 }}>
      {#each toolActivity as tool (tool.id)}
        <span class="tool-item">
          {#if tool.done}<span class="tool-done"><Check size={10} strokeWidth={3} /></span>{:else}<span class="tool-running"></span>{/if}
          <span>{tool.name}</span>
        </span>
      {/each}
    </div>
  {/if}

  {#if !expanded && messages.length > 2}
    <button class="history-link" type="button" onclick={onExpand}
      ><MessageCircle size={13} /> View conversation <ArrowDown
        size={13}
      /></button
    >
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
      oninput={resizeComposer}
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
      disabled={!draft.trim() || sending}
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
