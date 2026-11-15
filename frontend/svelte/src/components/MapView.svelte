<script lang="ts">
  import { mount, onMount, unmount, untrack } from "svelte";
  import { MapPin } from "@lucide/svelte";
  import L from "leaflet";
  import type { MapPlace, MapRoute, Viewport } from "../lib/types";

  let {
    viewport,
    places,
    routes,
    onViewportChange,
  }: { viewport: Viewport; places: MapPlace[]; routes: MapRoute[]; onViewportChange: (viewport: Viewport) => void } =
    $props();
  let host: HTMLDivElement;
  let map: L.Map | undefined;
  let programmaticTarget: Viewport | undefined;
  let markers: L.LayerGroup | undefined;
  let routeLayer: L.LayerGroup | undefined;

  function showRoutes(items: MapRoute[]): void {
    if (!map || !routeLayer) return;
    routeLayer.clearLayers();
    if (!items.length) return;
    for (let i = items.length - 1; i >= 0; i--) {
      const points = items[i].points;
      L.polyline(points, { color: "#fff", weight: i ? 7 : 9, opacity: 0.9 }).addTo(routeLayer);
      L.polyline(points, { color: i ? "#91a8bd" : "#246ddb", weight: i ? 4 : 5, opacity: 1 }).addTo(routeLayer);
    }
    const primary = items[0].points;
    for (const [point, kind, label] of [[primary[0], "route-start", items[0].originName || "Route start"], [primary[primary.length - 1], "route-destination", items[0].destinationName || "Route destination"]] as const) {
      const element = document.createElement("span");
      const pin = mount(MapPin, { target: element, props: { size: 36 } });
      const card = document.createElement("span");
      const visible = availableArea();
      const projected = map.latLngToContainerPoint(point);
      const rightSpace = visible.right - projected.x;
      const leftSpace = projected.x - visible.left;
      card.className = `place-card ${rightSpace >= leftSpace ? "opens-right" : "opens-left"}`;
      card.style.maxWidth = `${Math.max(1, Math.min(220, Math.max(leftSpace, rightSpace) - 20))}px`;
      const title = document.createElement("strong");
      title.textContent = label;
      card.append(title);
      card.addEventListener("animationend", () => card.remove(), { once: true });
      element.append(card);
      const icon = L.divIcon({ className: `place-marker ${kind}`, html: element, iconSize: [36, 36], iconAnchor: [18, 33] });
      L.marker(point, { icon, title: label, alt: label })
        .bindTooltip(label)
        .on("remove", () => { void unmount(pin); })
        .addTo(routeLayer);
    }
    const bounds = L.latLngBounds(items.flatMap((item) => item.points));
    const width = host.clientWidth, height = host.clientHeight;
    const mobile = window.matchMedia("(max-width: 640px)").matches;
    const reserved = mobile ? width - 10 : Math.min(520, width - 48) + 24;
    const available = Math.max(1, width - reserved);
    const padding = Math.min(44, Math.max(0, (available - 1) / 2));
    const topLeft = L.point(padding, 44), bottomRight = L.point(width - available + padding, 44);
    const zoom = Math.min(15, map.getBoundsZoom(bounds, false, topLeft.add(bottomRight)));
    const midpoint = map.project(bounds.getSouthWest(), zoom).add(map.project(bounds.getNorthEast(), zoom)).divideBy(2);
    const center = map.unproject(midpoint.add(bottomRight.subtract(topLeft).divideBy(2)), zoom);
    onViewportChange({ latitude: center.lat, longitude: center.lng, zoom });
  }

  function availableArea() {
    const chat = document.querySelector<HTMLElement>(".chat-position")?.getBoundingClientRect();
    const mapRect = host.getBoundingClientRect();
    const width = mapRect.width, height = mapRect.height;
    let area = { left: 0, top: 0, right: width, bottom: height };
    if (chat && chat.right > mapRect.left && chat.left < mapRect.right && chat.bottom > mapRect.top && chat.top < mapRect.bottom) {
      const left = Math.max(0, Math.min(width, chat.left - mapRect.left));
      const right = Math.max(0, Math.min(width, chat.right - mapRect.left));
      const top = Math.max(0, Math.min(height, chat.top - mapRect.top));
      const bottom = Math.max(0, Math.min(height, chat.bottom - mapRect.top));
      const candidates = [
        { left: 0, top: 0, right: left, bottom: height },
        { left: right, top: 0, right: width, bottom: height },
        { left: 0, top: 0, right: width, bottom: top },
        { left: 0, top: bottom, right: width, bottom: height },
      ];
      area = candidates.reduce((best, candidate) =>
        (candidate.right - candidate.left) * (candidate.bottom - candidate.top) >
        (best.right - best.left) * (best.bottom - best.top) ? candidate : best,
      candidates[0]);
    }
    return area;
  }

  function showPlaces(results: MapPlace[]): void {
    if (!map || !markers) return;
    markers.clearLayers();
    if (!results.length) return;
    const bounds = L.latLngBounds(results.map((place) => [place.latitude, place.longitude]));
    const mapRect = host.getBoundingClientRect();
    const width = mapRect.width, height = mapRect.height;
    const margin = 44;
    const mobile = window.matchMedia("(max-width: 640px)").matches;
    const potentialWidth = mobile ? width - 20 : Math.min(520, width - 48);
    const potentialRight = mobile ? 10 : 24;
    const area = { left: 0, top: 0, right: Math.max(1, width - potentialRight - potentialWidth), bottom: height };
    const cardArea = availableArea();
    const horizontalMargin = Math.min(margin, Math.max(0, (area.right - area.left - 1) / 2));
    const verticalMargin = Math.min(margin, Math.max(0, (area.bottom - area.top - 1) / 2));
    const topLeft = L.point(area.left + horizontalMargin, area.top + verticalMargin);
    const bottomRight = L.point(width - area.right + horizontalMargin, height - area.bottom + verticalMargin);
    const zoom = Math.min(15, map.getBoundsZoom(bounds, false, topLeft.add(bottomRight)));
    const midpoint = map.project(bounds.getSouthWest(), zoom).add(map.project(bounds.getNorthEast(), zoom)).divideBy(2);
    const center = map.unproject(midpoint.add(bottomRight.subtract(topLeft).divideBy(2)), zoom);
    for (const place of results) {
      const content = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = place.name;
      content.append(title);
      if (place.address) {
        const address = document.createElement("div");
        address.textContent = place.address;
        content.append(address);
      }
      const iconElement = document.createElement("span");
      const pin = mount(MapPin, { target: iconElement, props: { size: 36 } });
      const card = document.createElement("span");
      const point = map.project([place.latitude, place.longitude], zoom)
        .subtract(map.project(center, zoom)).add(L.point(width / 2, height / 2));
      const spaceLeft = Math.max(0, point.x - cardArea.left - 20);
      const spaceRight = Math.max(0, cardArea.right - point.x - 20);
      const opensRight = spaceRight >= spaceLeft;
      card.className = `place-card ${opensRight ? "opens-right" : "opens-left"}`;
      card.style.maxWidth = `${Math.max(1, Math.min(220, opensRight ? spaceRight : spaceLeft))}px`;
      const cardName = document.createElement("strong");
      cardName.textContent = place.name;
      card.append(cardName);
      if (place.address) {
        const cardAddress = document.createElement("span");
        cardAddress.textContent = place.address;
        card.append(cardAddress);
      }
      card.addEventListener("animationend", () => card.remove(), { once: true });
      iconElement.append(card);
      const icon = L.divIcon({
        className: "place-marker",
        html: iconElement,
        iconSize: [36, 36],
        iconAnchor: [18, 33],
        popupAnchor: [0, -32],
      });
      L.marker([place.latitude, place.longitude], { icon, title: place.name, alt: place.name })
        .bindPopup(content, { autoPan: false, className: "place-popup" })
        .on("popupopen", (event) => {
          if (!map) return;
          const popup = event.popup;
          const rect = popup.getElement()?.getBoundingClientRect();
          if (!rect) return;
          const visible = availableArea();
          const mapBox = host.getBoundingClientRect();
          const minX = mapBox.left + visible.left + 8, maxX = mapBox.left + visible.right - 8;
          const minY = mapBox.top + visible.top + 8, maxY = mapBox.top + visible.bottom - 8;
          const dx = rect.left < minX ? rect.left - minX : rect.right > maxX ? rect.right - maxX : 0;
          const dy = rect.top < minY ? rect.top - minY : rect.bottom > maxY ? rect.bottom - maxY : 0;
          if (dx || dy) {
            const offset = L.point(popup.options.offset ?? [0, 0]);
            popup.options.offset = offset.subtract([dx, dy]);
            popup.update();
          }
        })
        .on("remove", () => { void unmount(pin); })
        .addTo(markers);
      const cardHeight = card.offsetHeight;
      const cardTop = Math.max(cardArea.top + 8, Math.min(point.y - 33, cardArea.bottom - 8 - cardHeight));
      card.style.top = `${cardTop - (point.y - 33)}px`;
    }
    onViewportChange({ latitude: center.lat, longitude: center.lng, zoom });
  }

  function moveTo(next: Viewport): void {
    if (!map) return;
    const center = map.getCenter();
    if (
      Math.abs(center.lat - next.latitude) < 0.00001 &&
      Math.abs(center.lng - next.longitude) < 0.00001 &&
      Math.abs(map.getZoom() - next.zoom) < 0.02
    )
      return;
    programmaticTarget = next;
    map.flyTo([next.latitude, next.longitude], next.zoom, { duration: 0.7 });
  }

  $effect(() => moveTo(viewport));
  $effect(() => {
    const results = places;
    untrack(() => showPlaces(results));
  });
  $effect(() => { const current = routes; untrack(() => showRoutes(current)); });

  onMount(() => {
    map = L.map(host, {
      center: [viewport.latitude, viewport.longitude],
      zoom: viewport.zoom,
      zoomControl: false,
      attributionControl: false,
      preferCanvas: true,
    });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);
    L.control.zoom({ position: "bottomright" }).addTo(map);
    markers = L.layerGroup().addTo(map);
    routeLayer = L.layerGroup().addTo(map);
    showPlaces(places);
    showRoutes(routes);
    L.control
      .attribution({ position: "bottomright", prefix: false })
      .addTo(map);

    map.on("moveend", () => {
      if (!map) return;
      const center = map.getCenter();
      const current = {
        latitude: center.lat,
        longitude: center.lng,
        zoom: map.getZoom(),
      };
      const target = programmaticTarget;
      if (
        target &&
        Math.abs(current.latitude - target.latitude) < 0.0001 &&
        Math.abs(current.longitude - target.longitude) < 0.0001 &&
        Math.abs(current.zoom - target.zoom) < 0.03
      ) {
        programmaticTarget = undefined;
        return;
      }
      programmaticTarget = undefined;
      onViewportChange(current);
    });

    moveTo(viewport);
    return () => {
      map?.remove();
      map = undefined;
      markers = undefined;
      routeLayer = undefined;
    };
  });
</script>

<div class="map-canvas" bind:this={host} aria-label="Interactive map"></div>
