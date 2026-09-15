import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { FeatureCollection } from "geojson";

const STYLE = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";

interface Props {
  lines: [number, number][][];
  places?: { name: string; lat: number; lon: number }[];
  endpoints?: boolean;
  height?: number | string;
  opacity?: number;
}

export function RouteMap({ lines, places = [], endpoints = false, height = 360, opacity = 0.9 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    let m: maplibregl.Map;
    try {
      m = new maplibregl.Map({ container: ref.current, style: STYLE, attributionControl: { compact: true }, center: [-97.74, 30.28], zoom: 10 });
    } catch (e) {
      // No WebGL (old browser, locked-down GPU, headless): keep the rest of the page working.
      queueMicrotask(() => setFailed(e instanceof Error ? e.message : String(e)));
      return;
    }
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.current = m;
    return () => { m.remove(); map.current = null; };
  }, []);

  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const draw = () => {
      const data: FeatureCollection = {
        type: "FeatureCollection",
        features: lines.filter((l) => l.length > 1).map((coords) => ({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: coords } })),
      };
      const pts: FeatureCollection = {
        type: "FeatureCollection",
        features: [
          ...places.map((p) => ({ type: "Feature" as const, properties: { name: p.name, role: "place" }, geometry: { type: "Point" as const, coordinates: [p.lon, p.lat] } })),
          ...(endpoints && lines[0]?.length ? [
            { type: "Feature" as const, properties: { name: "Start", role: "start" }, geometry: { type: "Point" as const, coordinates: lines[0][0] } },
            { type: "Feature" as const, properties: { name: "End", role: "end" }, geometry: { type: "Point" as const, coordinates: lines[lines.length - 1][lines[lines.length - 1].length - 1] } },
          ] : []),
        ],
      };
      const src = m.getSource("routes") as maplibregl.GeoJSONSource | undefined;
      if (src) {
        src.setData(data);
        (m.getSource("points") as maplibregl.GeoJSONSource).setData(pts);
      } else {
        m.addSource("routes", { type: "geojson", data });
        m.addSource("points", { type: "geojson", data: pts });
        m.addLayer({ id: "routes-glow", type: "line", source: "routes", paint: { "line-color": "#3987e5", "line-width": 6, "line-opacity": 0.12, "line-blur": 3 }, layout: { "line-cap": "round", "line-join": "round" } });
        m.addLayer({ id: "routes", type: "line", source: "routes", paint: { "line-color": "#5aa2f0", "line-width": 2, "line-opacity": opacity }, layout: { "line-cap": "round", "line-join": "round" } });
        m.addLayer({ id: "points", type: "circle", source: "points", paint: {
          "circle-radius": ["match", ["get", "role"], "place", 4, 6],
          "circle-color": ["match", ["get", "role"], "start", "#199e70", "end", "#e82127", "#f4f5f7"],
          "circle-stroke-color": "#15171a", "circle-stroke-width": 2 } });
        m.addLayer({ id: "labels", type: "symbol", source: "points", filter: ["==", ["get", "role"], "place"], layout: { "text-field": ["get", "name"], "text-size": 11, "text-offset": [0, 1.1], "text-anchor": "top" }, paint: { "text-color": "#b4b8bf", "text-halo-color": "#0b0c0e", "text-halo-width": 1.2 } });
      }
      const all = lines.flat();
      places.forEach((p) => all.push([p.lon, p.lat]));
      if (all.length) {
        const b = all.reduce((acc, c) => acc.extend(c as [number, number]), new maplibregl.LngLatBounds(all[0], all[0]));
        m.fitBounds(b, { padding: 40, duration: 0, maxZoom: 15 });
      }
    };
    if (m.isStyleLoaded()) draw(); else m.once("load", draw);
  }, [lines, places, endpoints, opacity]);

  if (failed) {
    return (
      <div style={{ height }} className="flex w-full items-center justify-center rounded-xl bg-surface-2 p-6 text-center text-sm text-ink-3">
        The map needs WebGL, which this browser does not provide. Routes and stats are still recorded.
      </div>
    );
  }
  return <div ref={ref} style={{ height }} className="w-full overflow-hidden rounded-xl" role="img" aria-label="Map of driven routes" />;
}
