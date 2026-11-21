<script lang="ts">
  import { tick } from "svelte";
  import type { SlashColumn, SlashItem } from "../lib/slash/types";
  import SlashDialogue from "./SlashDialogue.svelte";
  let { items, query, onClose, onNavigate, columns }: { items: SlashItem[]; query: string; onClose: () => void; onNavigate: () => void; columns?: SlashColumn[] } = $props();
  const defaultColumns: SlashColumn[] = [{ id: "title", value: (item) => item.title, width: "2fr" }, { id: "description", value: (item) => item.description, width: "3fr" }];
  let path = $state<string[]>([]);
  let selected = $state(-1);
  let list = $state<HTMLDivElement>();
  let dialogue = $state<SlashItem | null>(null);
  const current = $derived.by(() => {
    let level = items;
    for (const id of path) level = level.find((item) => item.id === id)?.children ?? [];
    return level;
  });
  const filtered = $derived(current.filter((item) => `${item.title} ${item.description ?? ""}`.toLowerCase().includes(query.toLowerCase())));
  const currentColumns = $derived.by(() => {
    let level = items, result = columns ?? defaultColumns;
    for (const id of path) { const parent = level.find((item) => item.id === id); if (!parent) break; result = parent.columns ?? columns ?? defaultColumns; level = parent.children ?? []; }
    return result;
  });
  $effect(() => { query; selected = -1; });
  $effect(() => {
    const value = query.trim().toLowerCase();
    if (!value || dialogue) return;
    const match = current.find((item) => item.children && !item.disabled && (item.id.toLowerCase() === value || item.title.toLowerCase() === value));
    if (match) { path = [...path, match.id]; selected = -1; onNavigate(); }
  });
  function back() { if (dialogue) dialogue = null; else if (path.length) path = path.slice(0, -1); else onClose(); selected = -1; onNavigate(); }
  function select(item: SlashItem) {
    if (item.disabled) return;
    if (item.indicator?.kind === "checkbox") { item.onToggle?.(!item.indicator.active); return; }
    if (item.fields) { dialogue = item; onNavigate(); void tick().then(() => document.querySelector<HTMLInputElement>(".slash-dialogue input:not(:disabled)")?.focus()); }
    else if (item.children) { path = [...path, item.id]; selected = -1; onNavigate(); }
    else { item.action?.(); }
  }
  export function handleKey(event: KeyboardEvent): boolean {
    if (event.key === "Escape") { event.preventDefault(); onClose(); return true; }
    if (event.key === "ArrowLeft" && (path.length || dialogue) && !query) { event.preventDefault(); back(); return true; }
    if (dialogue) { if (event.key === "Enter") { event.preventDefault(); return true; } return false; }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!filtered.length) return true;
      if (selected < 0) selected = 0;
      else if (event.key === "ArrowDown") selected = selected === filtered.length - 1 ? -1 : selected + 1;
      else selected = Math.max(0, selected - 1);
      void tick().then(() => {
        if (!list) return;
        if (selected < 0) { list.scrollTop = 0; return; }
        const row = list.children[selected] as HTMLElement | undefined;
        if (!row) return;
        if (row.offsetTop < list.scrollTop) list.scrollTop = row.offsetTop;
        else if (row.offsetTop + row.offsetHeight > list.scrollTop + list.clientHeight) list.scrollTop = row.offsetTop + row.offsetHeight - list.clientHeight;
      });
      return true;
    }
    if (event.key === " " && filtered[selected]?.indicator?.kind === "checkbox" && !filtered[selected].disabled) { event.preventDefault(); select(filtered[selected]); return true; }
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); if (filtered[selected]) select(filtered[selected]); return true; }
    return false;
  }
</script>
<div class="slash-menu" aria-label="Commands">
  <div class="slash-heading">{#if path.length || dialogue}<button type="button" onclick={back} aria-label="Back">←</button>{/if}<span>/{path.join(" / ")}{dialogue ? ` / ${dialogue.title}` : ""}</span></div>
  {#if dialogue}<SlashDialogue fields={dialogue.fields ?? []} onBack={back} onSubmit={dialogue.onSubmit} />
  {:else if filtered.length}
    <div class="slash-list" bind:this={list}>{#each filtered as item, index (item.id)}
      <button type="button" class="slash-row" class:selected={index === selected} disabled={item.disabled} role={item.indicator?.kind === "checkbox" ? "checkbox" : undefined} aria-checked={item.indicator?.kind === "checkbox" ? item.indicator.active : undefined} onclick={() => select(item)} onmouseenter={() => selected = index} style:grid-template-columns={`${currentColumns.map((column) => column.width ?? "1fr").join(" ")} auto`}>
        {#each currentColumns as column (column.id)}<span class="slash-column">{column.value(item) ?? ""}</span>{/each}
        <span class="slash-indicator">{#if item.trailing}<span aria-label={`${item.trailing} tools enabled`}>{item.trailing}</span>{:else if item.indicator?.kind === "status"}<span class="slash-status" class:active={item.indicator.active} aria-label={item.indicator.active ? "Enabled" : "Disabled"}></span>{:else if item.indicator?.kind === "checkbox"}<span class="slash-checkbox" class:checked={item.indicator.active} aria-hidden="true">{item.indicator.active ? "✓" : ""}</span>{/if}</span>
      </button>
    {/each}</div>
    <div class="slash-return">↓ Back to composer</div>
  {:else}<p class="slash-empty">No matching commands.</p>{/if}
</div>
