<script lang="ts">
  import type { SlashField } from "../lib/slash/types";
  let { fields, onBack, onSubmit }: { fields: SlashField[]; onBack: () => void; onSubmit?: (values: Record<string, string>) => void | Promise<void> } = $props();
  let values = $state<Record<string, string>>({});
  let error = $state("");
  let saving = $state(false);
  async function submit() {
    if (!onSubmit || saving) return;
    const supplied = Object.fromEntries(Object.entries(values).filter(([, value]) => value.trim()));
    if (!Object.keys(supplied).length) { error = "Enter at least one credential."; return; }
    error = ""; saving = true;
    try { await onSubmit(supplied); values = {}; onBack(); }
    catch (e) { error = e instanceof Error ? e.message : "Could not save credentials."; }
    finally { saving = false; }
  }
</script>
<form class="slash-dialogue" onsubmit={(event) => { event.preventDefault(); void submit(); }}>
  {#each fields as field (field.id)}
    <label>{field.label}<input type={field.masked ? "password" : "text"} autocomplete="off" value={values[field.id] ?? ""} oninput={(event) => values[field.id] = event.currentTarget.value} onkeydown={(event) => { if (event.key === "Escape") { event.preventDefault(); onBack(); } }} /></label>
  {/each}
  {#if error}<p role="alert">{error}</p>{/if}
  {#if onSubmit}<button type="submit" disabled={saving}>{saving ? "Saving…" : "Save"}</button>{:else}<p>Saving credentials will be available when the service is connected.</p>{/if}
  <button type="button" onclick={onBack}>Back</button>
</form>
