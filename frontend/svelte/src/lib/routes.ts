import type { MapRoute } from "./types";

function decodePolyline(encoded: string): [number, number][] {
  const points: [number, number][] = [];
  let index = 0, lat = 0, lng = 0;
  function read(): number {
    let result = 0, shift = 0, byte: number;
    do {
      if (index >= encoded.length || shift > 30) throw new Error("Invalid polyline");
      byte = encoded.charCodeAt(index++) - 63;
      if (byte < 0 || byte > 63) throw new Error("Invalid polyline");
      result |= (byte & 31) << shift;
      shift += 5;
    } while (byte >= 32);
    return result & 1 ? ~(result >> 1) : result >> 1;
  }
  while (index < encoded.length) {
    lat += read(); lng += read();
    if (Math.abs(lat) > 9000000 || Math.abs(lng) > 18000000) throw new Error("Invalid coordinates");
    points.push([lat / 1e5, lng / 1e5]);
  }
  return points;
}

export function parseRoutes(output: unknown): MapRoute[] {
  const result = typeof output === "string" ? JSON.parse(output) : output;
  if (!result || typeof result !== "object" || !Array.isArray(result.routes)) return [];
  return result.routes.flatMap((route: any): MapRoute[] => {
    if (typeof route?.polyline?.encodedPolyline !== "string") return [];
    try {
      const points = decodePolyline(route.polyline.encodedPolyline);
      if (points.length < 2) return [];
      return [{ points, distanceMeters: typeof route.distanceMeters === "number" ? route.distanceMeters : undefined, duration: typeof route.duration === "string" ? route.duration : undefined }];
    } catch { return []; }
  });
}
