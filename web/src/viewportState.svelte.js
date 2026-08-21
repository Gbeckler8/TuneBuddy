// Shared time/pitch <-> pixel mapping for the GuitarHero pitch-overlay split
// (system_design.md §11b): the canvas dot layer and the SVG note/interaction
// layer are two separate rendering surfaces that must never compute their
// own transforms independently, or a note box drifts out of alignment with
// its own pitch dots. Both layers import timeToX/pitchToY (and their
// inverses) from here instead.
//
// Mirrors desktop's pyqtgraph ViewBox: `fitToContent` is the "zoomed all the
// way out" state (today's NoteOverlay always-fit-to-data behavior, called
// whenever new note/pitch data loads), and pan/zoom narrow the visible
// window from there - clamped so you can never pan past the take's own
// data or zoom in to nothing.

function createViewportState() {
  let t0 = $state(0);
  let t1 = $state(1);
  let pitchMin = $state(60);
  let pitchMax = $state(72);
  let width = $state(800);
  let height = $state(280);

  // The take's full data extent - both the default fully-zoomed-out window
  // and the pan/zoom clamp bounds. Set via fitToContent(), not touched by
  // pan/zoom themselves.
  let contentT0 = $state(0);
  let contentT1 = $state(1);
  let contentPitchMin = $state(60);
  let contentPitchMax = $state(72);

  const MIN_TIME_SPAN = 0.5; // seconds - floor on how far zoom-in can narrow the window
  const MIN_PITCH_SPAN = 2; // semitones

  // Auto-follow (Desktop's `move_plot`/`timeline_offset` scrolling-window
  // behavior, system_design.md §11e): while enabled, `follow(t)` keeps the
  // playhead visible by sliding the window (preserving its current zoom
  // span) so `t` sits at a fixed fraction from the left edge. Manual
  // pan/zoom disables it - otherwise the next currentTime tick (up to 10x/
  // sec during playback) would immediately undo the user's own drag/zoom.
  let followEnabled = $state(true);

  function clamp(v, lo, hi) {
    return Math.min(hi, Math.max(lo, v));
  }

  function timeToX(t) {
    const span = t1 - t0 || 1;
    return ((t - t0) / span) * width;
  }
  function xToTime(x) {
    const span = t1 - t0 || 1;
    return t0 + (x / width) * span;
  }
  function pitchToY(midi) {
    const span = pitchMax - pitchMin || 1;
    return height - ((midi - pitchMin) / span) * height;
  }
  function yToPitch(y) {
    const span = pitchMax - pitchMin || 1;
    return pitchMin + ((height - y) / height) * span;
  }

  // Establishes both the default zoomed-out window and the pan/zoom clamp
  // bounds from the take's own data extent - the direct replacement for
  // NoteOverlay's old per-render minTime/maxTime/minPitch/maxPitch
  // derivation. Resets the current window to show everything; call this
  // whenever the underlying note/pitch data changes (new score picked, new
  // analysis result), not on every render.
  function fitToContent(minTime, maxTime, minPitch, maxPitch) {
    contentT0 = minTime;
    contentT1 = maxTime;
    contentPitchMin = minPitch;
    contentPitchMax = maxPitch;
    t0 = minTime;
    t1 = maxTime;
    pitchMin = minPitch;
    pitchMax = maxPitch;
  }

  function setSize(w, h) {
    width = w;
    height = h;
  }

  function setWindow(newT0, newT1) {
    const contentSpan = contentT1 - contentT0 || MIN_TIME_SPAN;
    const span = clamp(newT1 - newT0, MIN_TIME_SPAN, contentSpan);
    const start = clamp(newT0, contentT0, contentT1 - span);
    t0 = start;
    t1 = start + span;
  }

  function panBy(dt) {
    setWindow(t0 + dt, t1 + dt);
  }

  // factor < 1 zooms in, > 1 zooms out, anchored so centerT stays fixed on
  // screen (the point under the cursor/playhead doesn't jump).
  function zoomAt(centerT, factor) {
    const span = t1 - t0;
    const newSpan = span * factor;
    const frac = (centerT - t0) / (span || 1);
    const newT0 = centerT - frac * newSpan;
    setWindow(newT0, newT0 + newSpan);
  }

  function setPitchWindow(newMin, newMax) {
    const contentSpan = contentPitchMax - contentPitchMin || MIN_PITCH_SPAN;
    const span = clamp(newMax - newMin, MIN_PITCH_SPAN, contentSpan);
    const start = clamp(newMin, contentPitchMin, contentPitchMax - span);
    pitchMin = start;
    pitchMax = start + span;
  }

  function panPitchBy(dp) {
    setPitchWindow(pitchMin + dp, pitchMax + dp);
  }

  function zoomPitchAt(centerP, factor) {
    const span = pitchMax - pitchMin;
    const newSpan = span * factor;
    const frac = (centerP - pitchMin) / (span || 1);
    const newMin = centerP - frac * newSpan;
    setPitchWindow(newMin, newMin + newSpan);
  }

  function resetView() {
    t0 = contentT0;
    t1 = contentT1;
    pitchMin = contentPitchMin;
    pitchMax = contentPitchMax;
  }

  // Default: playhead sits 30% of the way across the window, leaving more
  // room to see what's coming up than what's already passed. Not copied
  // from a specific Desktop constant (not available to check against) -
  // a reasonable default for the same "keep the playhead visible while
  // scrolling forward" behavior.
  const FOLLOW_OFFSET_FRAC = 0.3;

  function follow(t, offsetFrac = FOLLOW_OFFSET_FRAC) {
    const span = t1 - t0;
    const newT0 = t - offsetFrac * span;
    setWindow(newT0, newT0 + span);
  }

  function enableFollow() {
    followEnabled = true;
  }
  function disableFollow() {
    followEnabled = false;
  }

  return {
    get t0() { return t0; },
    get t1() { return t1; },
    get pitchMin() { return pitchMin; },
    get pitchMax() { return pitchMax; },
    get width() { return width; },
    get height() { return height; },
    get contentT0() { return contentT0; },
    get contentT1() { return contentT1; },
    get contentPitchMin() { return contentPitchMin; },
    get contentPitchMax() { return contentPitchMax; },
    get followEnabled() { return followEnabled; },

    timeToX,
    xToTime,
    pitchToY,
    yToPitch,
    fitToContent,
    setSize,
    setWindow,
    panBy,
    zoomAt,
    setPitchWindow,
    panPitchBy,
    zoomPitchAt,
    resetView,
    follow,
    enableFollow,
    disableFollow,
  };
}

export const viewport = createViewportState();
