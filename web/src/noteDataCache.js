// Client-side cache for parsed score note data (POST /notedata's response),
// keyed by a SHA-256 hash of the score file's *content* plus the transpose
// amount requested, not just the filename - two uploads can share a name
// (e.g. a re-exported edit of the same file), and a name-only key would
// silently serve stale data for the second one. The transpose amount is
// part of the key (not a separate cache) because a transposed request is a
// genuinely different /notedata response, not a mutation of the
// untransposed one - see sessionState.svelte.js's setTranspose.
//
// This replaces a server-side GET-by-id endpoint entirely: the client holds
// the actual data once fetched, so there's nothing to look up by reference.
// Session-scoped only (a plain in-memory Map) - a page reload clears it, and
// the next score selection just re-fetches and re-populates it.
const cache = new Map(); // "content hash:semitones" -> /notedata response

async function hashFile(file) {
  const buffer = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

// Returns the cached note data for `scoreFile` at `semitones` transpose if
// this exact (content, transpose) pair has been seen before; otherwise POSTs
// it to /notedata and caches the result. `semitones` is always the TOTAL
// shift from the original score (see analyze_api.py's /notedata docstring),
// not incremental - so re-requesting semitones=0 after transposing away and
// back is just another cache hit, not a "reset."
export async function getNoteData(scoreFile, apiBaseUrl, semitones = 0) {
  const fileHash = await hashFile(scoreFile);
  const key = `${fileHash}:${semitones}`;
  if (cache.has(key)) {
    return cache.get(key);
  }

  const formData = new FormData();
  formData.append("score", scoreFile);
  if (semitones) {
    formData.append("transpose_semitones", String(semitones));
  }

  const response = await fetch(`${apiBaseUrl}/notedata`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Request failed (${response.status})`);
  }

  const data = await response.json();
  cache.set(key, data);
  return data;
}
