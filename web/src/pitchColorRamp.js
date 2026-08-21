// GuitarHero._build_align_brushes / get_align_distance_brush, ported. Shared
// between NoteOverlay.svelte (note bars, legend) and PitchCanvas.svelte
// (pitch dots) so both draw from the exact same pitch-distance color ramp -
// previously duplicated only in NoteOverlay before the canvas/SVG split
// (system_design.md §11).
export const ALIGN_MAX_MULT = 4.0;

export function alignHue(distance, tolerance) {
  const greenThresh = Math.max(tolerance, 0);
  const maxDist = Math.max(ALIGN_MAX_MULT * greenThresh, greenThresh + 0.05);
  const d = Math.min(Math.abs(distance), maxDist);
  if (d <= greenThresh) return 120;
  const frac = Math.max(0, Math.min(1, (d - greenThresh) / (maxDist - greenThresh)));
  return 120 * (1 - frac);
}

// QColor.setHsv(hue, 255, 255) (full saturation+value) is exactly
// hsl(hue, 100%, 50%) - same color space, no conversion loss.
export const hsl = (hue, alpha = 1) => `hsla(${hue}, 100%, 50%, ${alpha})`;
