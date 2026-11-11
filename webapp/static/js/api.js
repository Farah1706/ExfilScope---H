// Same-origin calls to the local control service. The launch token arrives in the URL
// fragment (never sent to a server or logged), is exchanged once for an HttpOnly cookie
// and is then removed from the address bar.
//
// The same interface also runs as a public, read-only site built by webapp/public_site.py.
// There every GET is answered by a prebuilt JSON file and nothing can be started.

export const PUBLIC = document.querySelector('meta[name="exfilscope-mode"]')?.content === "public";

// /api/investigations/run:run-… → data/investigations/run_run-….json
export function publicPath(path) {
  return path.replace(/^\/api\//, "data/").replace(/:/g, "_").replace(/%3A/gi, "_") + ".json";
}

export function csvUrl(collectionId) {
  const id = encodeURIComponent(collectionId);
  return PUBLIC ? `data/export/${collectionId.replace(/:/g, "_")}.csv` : `/api/investigations/${id}/export.csv`;
}

export class ApiError extends Error {
  constructor(status, body) {
    super(body?.error || `HTTP ${status}`);
    this.status = status;
    this.body = body || {};
  }
}

// Resolves to null when a session is active, otherwise to the reason code to show.
export async function bootstrapSession() {
  if (PUBLIC) return null;
  const match = location.hash.match(/^#t=([A-Za-z0-9_-]{16,128})$/);
  let linkProblem = null;
  if (match) {
    history.replaceState(null, "", location.pathname + "#/overview");
    try {
      await post("/api/session", { token: match[1] });
    } catch (error) {
      if (error.status !== 401) throw error;
      linkProblem = error.message;  // e.g. a used link reopened while a session is still valid
    }
  }
  try {
    await get("/api/session");
    return null;
  } catch (error) {
    if (error.status === 401) return linkProblem || error.message;
    throw error;
  }
}

export function isSessionError(error) {
  return error instanceof ApiError && error.status === 401;
}

export async function get(path) {
  if (PUBLIC) {
    const response = await fetch(publicPath(path), { headers: { Accept: "application/json" } });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new ApiError(response.status === 404 ? 404 : response.status, { error: "NOT_IN_PUBLIC_REPLAY" });
    return body;
  }
  const response = await fetch(path, { credentials: "same-origin", headers: { Accept: "application/json" } });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, body);
  return body;
}

export async function post(path, payload = {}) {
  if (PUBLIC) throw new ApiError(405, { error: "PUBLIC_READ_ONLY" });
  const response = await fetch(path, {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-ExfilScope": "1" },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, body);
  return body;
}

// Plain-language text for the service's error codes.
export const ERRORS = {
  RUN_ALREADY_ACTIVE: "Another run is in progress. Wait for it to finish or cancel it first.",
  MODE_UNAVAILABLE: "This mode cannot run because a prerequisite is missing.",
  INVALID_RUN_REQUEST: "The service rejected these settings.",
  SESSION_REQUIRED: "This browser has no session for this ExfilScope service.",
  SESSION_EXPIRED_OR_STALE: "This browser's session has expired or belongs to an earlier launch of ExfilScope.",
  INVALID_LAUNCH_TOKEN: "This link does not belong to the ExfilScope service now running.",
  LAUNCH_LINK_ALREADY_USED: "This launch link has already been used. Each link opens one session.",
  RUNS_OWNED_BY_OTHER_SERVICE: "Another ExfilScope window owns the run folder. Runs can be started only there; evidence remains viewable here.",
  REQUEST_TOO_LARGE: "The request was larger than the service accepts.",
  SERVICE_UNREACHABLE: "The ExfilScope service is not answering. It may have been stopped.",
  COLLECTION_UNAVAILABLE: "This evidence collection is unavailable or failed validation.",
  UNKNOWN_RUN: "No run with this identifier exists.",
  OPERATOR_SESSION_MISMATCH: "Only the local session that started this lifecycle can change its authority.",
  AUTHORITY_STATE_CONFLICT: "That decision is no longer available or is already queued. Wait for the current operator state.",
  INVALID_AUTHORITY_OPERATION: "The service rejected this authority request.",
  NOT_OPERATOR_LIFECYCLE: "This run does not accept interactive operator decisions.",
  RUN_NOT_ACTIVE: "This run is no longer active.",
  TRUST_AUDIT_UNAVAILABLE: "The trust audit for this run is unavailable.",
  RESPONSE_WITHHELD: "The service withheld a response that failed its privacy check.",
  NOT_IN_PUBLIC_REPLAY: "This record is not part of the public replay. It exists only in a local installation.",
  PUBLIC_READ_ONLY: "The public site is read-only. Running a scenario needs the local application.",
  DATASET_UNAVAILABLE: "The demonstration dataset could not be read or failed its integrity check.",
};

export function explain(error) {
  if (error instanceof ApiError) return ERRORS[error.message] || `The service answered ${error.message}.`;
  return "The local service did not answer. Check that the launcher window is still open.";
}
