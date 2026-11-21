<script lang="ts">
  let { title, description, onConfirm, onCancel }: { title: string; description: string; onConfirm: () => Promise<void>; onCancel: () => void } = $props();
  let progress = $state(0);
  let busy = $state(false);
  let error = $state("");
  async function finish() {
    if (progress < 100 || busy) { progress = 0; return; }
    busy = true; error = "";
    try { await onConfirm(); onCancel(); }
    catch (e) { error = e instanceof Error ? e.message : "Could not complete the action."; progress = 0; }
    finally { busy = false; }
  }
</script>
<div class="confirm-overlay">
  <div class="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-title" tabindex="-1">
    <h2 id="confirm-title">{title}</h2>
    <p>{description}</p>
    <label>Slide all the way to confirm
      <input type="range" min="0" max="100" step="1" bind:value={progress} disabled={busy} onchange={() => void finish()} />
    </label>
    {#if busy}<p>Clearing…</p>{/if}
    {#if error}<p role="alert">{error}</p>{/if}
    <button type="button" disabled={busy} onclick={onCancel}>Cancel</button>
  </div>
</div>
