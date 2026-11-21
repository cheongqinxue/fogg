<script lang="ts">
  import { onMount } from "svelte";
  import App from "../App.svelte";
  import MapView from "./MapView.svelte";
  import { DEFAULT_VIEWPORT } from "../lib/types";
  import { countries } from "../lib/countries";
  import { authenticate, logout, restoreSession, type AuthSession } from "../lib/agent";

  let session = $state<AuthSession | null>(null);
  let checking = $state(true);
  let creating = $state(false);
  let busy = $state(false);
  let error = $state("");
  let email = $state("");
  let password = $state("");
  let name = $state("");
  let address = $state("");
  let homeCountry = $state("");
  let gender = $state("");
  let statuses = $state<{ id: number; country_code: string; kind: "citizenship" | "permanent_resident" }[]>([]);
  let nextId = 0;

  onMount(() => { void restoreSession().then((value) => { session = value; checking = false; }); });
  async function submit() {
    if (busy) return;
    busy = true; error = "";
    try {
      const body: Record<string, unknown> = { email: email.trim(), password };
      if (creating) {
        body.name = name.trim();
        body.home_formatted_address = address.trim();
        body.home_country_code = homeCountry.trim().toUpperCase();
        if (gender.trim()) body.gender = gender.trim();
        const rows = statuses.filter((row) => row.country_code.trim()).map((row) => ({ country_code: row.country_code.trim().toUpperCase(), kind: row.kind }));
        if (rows.length) body.immigration_statuses = rows;
      }
      session = await authenticate(creating ? "register" : "login", body);
      password = "";
    } catch (e) { error = e instanceof TypeError ? "Cannot reach the server. Please try again." : e instanceof Error ? e.message : "Unable to sign in."; }
    finally { busy = false; }
  }
  async function signOut() {
    try { await logout(); session = null; email = ""; password = ""; name = ""; address = ""; homeCountry = ""; gender = ""; statuses = []; error = ""; }
    catch (e) { error = e instanceof Error ? e.message : "Could not sign out."; }
  }
</script>

{#if checking}
  <main class="auth-screen"><p>Checking your session…</p></main>
{:else if session}
  {#key session.accountId}<App accountId={session.accountId} onLogout={signOut} />{/key}
  {#if error}<div class="auth-notice" role="alert">{error}</div>{/if}
{:else}
  <div class="auth-map" aria-hidden="true"><MapView viewport={DEFAULT_VIEWPORT} places={[]} routes={[]} onViewportChange={() => {}} /></div>
  <main class="auth-screen">
    <section class="auth-card" aria-label={creating ? "Create account" : "Sign in"}>
      <h1>fogg<span>.</span></h1>
      <h2>{creating ? "Create your account" : "Welcome back"}</h2>
      <form onsubmit={(event) => { event.preventDefault(); void submit(); }}>
        <label>Email<input type="email" bind:value={email} required autocomplete="email" /></label>
        <label>Password<input type="password" bind:value={password} required minlength={creating ? 15 : undefined} autocomplete={creating ? "new-password" : "current-password"} /></label>
        {#if creating}
          <small>Use at least 15 characters.</small>
          <label>Name<input bind:value={name} required autocomplete="name" /></label>
          <label>Home address<input bind:value={address} required autocomplete="street-address" /></label>
          <label>Home country<select bind:value={homeCountry} required autocomplete="country"><option value="" disabled>Select a country</option>{#each countries as country (country.code)}<option value={country.code}>{country.name}</option>{/each}</select></label>
          <label>Gender (optional)<input bind:value={gender} autocomplete="sex" /></label>
          <fieldset><legend>Citizenship or permanent residency (optional)</legend>
            {#each statuses as row (row.id)}
              <div class="auth-status-row"><label>Country<select bind:value={row.country_code} required><option value="" disabled>Select a country</option>{#each countries as country (country.code)}<option value={country.code}>{country.name}</option>{/each}</select></label>
                <label>Status<select bind:value={row.kind}><option value="citizenship">Citizenship</option><option value="permanent_resident">Permanent resident</option></select></label>
                <button type="button" onclick={() => statuses = statuses.filter((item) => item.id !== row.id)}>Remove</button></div>
            {/each}
            <button type="button" onclick={() => statuses = [...statuses, { id: nextId++, country_code: "", kind: "citizenship" }]}>Add country</button>
          </fieldset>
        {/if}
        {#if error}<p class="auth-error" role="alert">{error}</p>{/if}
        <button class="auth-submit" type="submit" disabled={busy}>{busy ? "Please wait…" : creating ? "Create account" : "Sign in"}</button>
      </form>
      {#if !creating}<button class="auth-google" type="button" disabled><svg aria-hidden="true" width="18" height="18" viewBox="0 0 48 48"><path fill="#4285f4" d="M43.6 24.5c0-1.4-.1-2.9-.4-4.2H24v8h11a9.4 9.4 0 0 1-4.1 6.2v5.2h6.6c3.9-3.6 6.1-8.8 6.1-15.2z"/><path fill="#34a853" d="M24 44.5c5.5 0 10.1-1.8 13.5-4.8l-6.6-5.2c-1.8 1.2-4.2 1.9-6.9 1.9-5.3 0-9.7-3.6-11.3-8.4H5.9v5.3A20.4 20.4 0 0 0 24 44.5z"/><path fill="#fbbc05" d="M12.7 28a12.3 12.3 0 0 1 0-8V14.7H5.9a20.5 20.5 0 0 0 0 18.6z"/><path fill="#ea4335" d="M24 11.6c3 0 5.6 1 7.8 3.1l5.8-5.8A19.5 19.5 0 0 0 24 3.5 20.4 20.4 0 0 0 5.9 14.7l6.8 5.3c1.6-4.8 6-8.4 11.3-8.4z"/></svg> Continue with Google <small>Coming soon</small></button>{/if}
      <button class="auth-switch" type="button" onclick={() => { creating = !creating; error = ""; password = ""; }}>{creating ? "Already have an account? Sign in" : "Create an account"}</button>
    </section>
  </main>
{/if}
