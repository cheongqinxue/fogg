<script lang="ts">
  import { fade } from "svelte/transition";
  import { Bookmark, ChevronDown, ChevronUp } from "@lucide/svelte";
  import type { SavedTrip } from "../lib/types";

  let {
    trips,
    status,
    onRetry,
  }: {
    trips: SavedTrip[];
    status: "loading" | "ready" | "error";
    onRetry: () => Promise<void>;
  } = $props();

  let isOpen = $state(true);
  let expandedTripIds = $state<string[]>([]);
  let selectedTripId = $state("");
  let selectedItineraryId = $state("");

  const orderedTrips = $derived(trips.map((trip) => ({
    ...trip,
    itineraries: trip.head_itinerary_version_id
      ? [...trip.itineraries].sort((a, b) => Number(b.itinerary_version_id === trip.head_itinerary_version_id) - Number(a.itinerary_version_id === trip.head_itinerary_version_id))
      : trip.itineraries,
  })));
  const selectedItinerary = $derived(trips.flatMap((trip) => trip.itineraries.map((itinerary) => ({ trip, itinerary }))).find(({ trip, itinerary }) => trip.trip_id === selectedTripId && itinerary.itinerary_version_id === selectedItineraryId));

  function selectItinerary(tripId: string, itineraryId: string): void {
    selectedTripId = tripId;
    selectedItineraryId = itineraryId;
  }

  function toggleTripVersions(tripId: string): void {
    expandedTripIds = expandedTripIds.includes(tripId)
      ? expandedTripIds.filter((id) => id !== tripId)
      : [...expandedTripIds, tripId];
  }

  function coverFor(itineraryId: string): string {
    if (itineraryId === "75133098-25ad-4c74-ad01-dbb0ed73276e") return "/itinerary-covers/hakuba.webp";
    const covers = ["coast", "mountains", "city"];
    let hash = 2166136261;
    for (const character of itineraryId) hash = Math.imul(hash ^ character.charCodeAt(0), 16777619);
    return `/itinerary-covers/${covers[(hash >>> 0) % covers.length]}.webp`;
  }

  function tripDates(trip: SavedTrip): string {
    const format = (value: string | null) => value
      ? new Intl.DateTimeFormat("en-SG", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(new Date(`${value.slice(0, 10)}T00:00:00Z`))
      : "";
    const start = format(trip.starts_on), end = format(trip.ends_on);
    return start && end ? `${start} – ${end}` : start || end;
  }
</script>

<section class="saved-itineraries" aria-label="Saved itineraries">
  {#if status === "loading"}
    <div class="saved-itinerary-state" role="status"><Bookmark size={15} /> Loading saved itineraries…</div>
  {:else if status === "error"}
    <div class="saved-itinerary-state error" role="status">
      <span>Couldn’t load saved itineraries.</span>
      <button type="button" onclick={() => void onRetry()}>Retry</button>
    </div>
  {:else if !orderedTrips.length}
    <div class="saved-itinerary-state"><Bookmark size={15} /> No saved itineraries yet</div>
  {:else}
    <button class="saved-itinerary-toggle" type="button" aria-expanded={isOpen} onclick={() => { isOpen = !isOpen; }}>
      <span class="saved-itinerary-heading"><Bookmark size={15} /><span>Saved itineraries</span><span class="saved-itinerary-count">{orderedTrips.length}</span></span>
      <span class="saved-itinerary-current">{#if selectedItinerary}{selectedItinerary.trip.name} · {selectedItinerary.itinerary.name ?? "Itinerary"}{:else}Choose an itinerary{/if}</span>
      {#if isOpen}<ChevronUp size={16} />{:else}<ChevronDown size={16} />{/if}
    </button>
    {#if isOpen}
      <div class="saved-itinerary-list" transition:fade={{ duration: 160 }}>
        {#each orderedTrips as trip (trip.trip_id)}
          <section class="saved-trip-group" aria-label={trip.name}>
            <div class="saved-trip-heading"><strong>{trip.name}</strong>{#if tripDates(trip)}<span>{tripDates(trip)}</span>{/if}</div>
            {#if trip.itineraries.length}
              {@const primary = trip.itineraries[0]}
              <div class="saved-trip-versions">
                <button
                  class="saved-version"
                  class:selected={selectedTripId === trip.trip_id && selectedItineraryId === primary.itinerary_version_id}
                  type="button"
                  aria-pressed={selectedTripId === trip.trip_id && selectedItineraryId === primary.itinerary_version_id}
                  onclick={() => selectItinerary(trip.trip_id, primary.itinerary_version_id)}
                >
                  <img class="saved-version-cover" src={coverFor(primary.itinerary_version_id)} alt="" loading="lazy" onerror={(event) => event.currentTarget.remove()} />
                  <span class="saved-version-shade"></span>
                  <span class="saved-version-copy">
                    <span class="saved-version-name">{primary.name ?? "Itinerary"}</span>
                  </span>
                  {#if primary.status !== "valid"}<span class="saved-version-status" class:broken={primary.status === "broken"}>{primary.status}</span>{/if}
                </button>
                {#if trip.itineraries.length > 1}
                  <button class="saved-version-more" type="button" aria-expanded={expandedTripIds.includes(trip.trip_id)} onclick={() => toggleTripVersions(trip.trip_id)}>
                    {#if expandedTripIds.includes(trip.trip_id)}Hide alternate versions{:else}Show {trip.itineraries.length - 1} alternate {trip.itineraries.length === 2 ? "version" : "versions"}{/if}
                  </button>
                {/if}
                {#if expandedTripIds.includes(trip.trip_id)}
                  {#each trip.itineraries.slice(1) as itinerary (itinerary.itinerary_version_id)}
                    <button
                      class="saved-version"
                      class:selected={selectedTripId === trip.trip_id && selectedItineraryId === itinerary.itinerary_version_id}
                      type="button"
                      aria-pressed={selectedTripId === trip.trip_id && selectedItineraryId === itinerary.itinerary_version_id}
                      onclick={() => selectItinerary(trip.trip_id, itinerary.itinerary_version_id)}
                    >
                      <img class="saved-version-cover" src={coverFor(itinerary.itinerary_version_id)} alt="" loading="lazy" onerror={(event) => event.currentTarget.remove()} />
                      <span class="saved-version-shade"></span>
                      <span class="saved-version-copy">
                        <span class="saved-version-name">{itinerary.name ?? "Itinerary"}</span>
                      </span>
                      {#if itinerary.status !== "valid"}<span class="saved-version-status" class:broken={itinerary.status === "broken"}>{itinerary.status}</span>{/if}
                    </button>
                  {/each}
                {/if}
              </div>
            {:else}
              <p class="saved-trip-empty">No saved versions</p>
            {/if}
          </section>
        {/each}
      </div>
    {/if}
  {/if}
  <footer class="saved-itinerary-footer"><a href="/itinerary-covers/credits.html" target="_blank" rel="noreferrer">Photo credits</a></footer>
</section>
