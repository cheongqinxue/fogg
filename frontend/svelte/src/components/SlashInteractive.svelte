<script lang="ts">
  import SlashMenu from "./SlashMenu.svelte";
  import type { SlashColumn, SlashItem } from "../lib/slash/types";
  let { items, query, onClose, onNavigate, columns }: { items: SlashItem[]; query: string; onClose: () => void; onNavigate: () => void; columns?: SlashColumn[] } = $props();
  let menu: SlashMenu;
  export function handleKey(event: KeyboardEvent): boolean { return menu?.handleKey(event) ?? false; }
</script>
<SlashMenu bind:this={menu} {items} {query} {onClose} {onNavigate} {columns} />
