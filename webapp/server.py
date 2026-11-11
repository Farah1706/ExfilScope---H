"""Local control service: static UI, read-only evidence API and a fixed set of run operations.

Bound to 127.0.0.1 only. Every /api route needs the session cookie issued in exchange for
the launch token, every state-changing route also needs a same-origin request with the
``X-ExfilScope`` header, and every JSON body is checked against the protected-value
registry before it leaves the process.
"""

import argparse
from contextlib import asynccontextmanager
import hashlib
import hmac
import json
import os
import re
import secrets
import time

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
import uvicorn

from dashboard.evidence import TITLES, export_csv, load_catalog
from exfilscope.registry import Registry

from . import dataset, readiness, research
from .contracts import STAGES, RunRequest
from .icons import ICONS
from .interpret import incident_view, summary
from .interpret import title as title_of
from .paths import ROOT, SNAPSHOTS, STATIC
from .runs import Busy, NotOwner, RunManager
from .scenarios import GROUPS, SCENARIOS, describe
from .trust import service as trust

COLLECTION = re.compile(r"^(snapshot:(qwen3-live|engineering-faults)|run:run-[0-9]{8}-[0-9]{6}-"
                        r"[0-9a-f]{8})$")
COOKIE = "exfilscope_session"
# Case types shown in the case browser. A type describes how a case was produced; it never
# merges collections, which stay separate and are counted only one at a time.
CASE_TYPES = {"live": "Live agent (Qwen3)", "stub": "Agent pipeline, deterministic proposal",
              "lab": "Deterministic laboratory case", "fault": "Controlled fault",
              "trust": "Government Trust extension"}
# Scenario Lab situation for each recorded snapshot case (payload subtypes by decision).
SNAPSHOT_SCENARIO = {"allow": "routine-submission", "redact": "confidential-request",
                     "block": "prohibited-transfer", "block_bypass": "transmission-after-rejection",
                     "destination_divergence": "unexpected-destination",
                     "no_observation": "missing-observation",
                     ("payload_divergence", "ALLOW"): "modified-after-approval",
                     ("payload_divergence", "REDACT"): "redaction-reversed"}
SESSION_IDLE_SECONDS = 8 * 3600
MAX_SESSIONS = 16
MAX_BODY_BYTES = 16 * 1024
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
       "frame-ancestors 'none'; form-action 'self'")
# Bundled OFL fonts (webapp/static/fonts): family, file, weight range.
FONTS = (("Inter", "InterVariable.woff2", "100 900"),
         ("JetBrains Mono", "JetBrainsMono-Regular.woff2", "400"),
         ("JetBrains Mono", "JetBrainsMono-Medium.woff2", "500"),
         ("JetBrains Mono", "JetBrainsMono-SemiBold.woff2", "600 900"))


def create_app(*, token: str, port: int, manager: RunManager | None = None,
               registry: Registry | None = None) -> FastAPI:
    manager = manager or RunManager(samples=ROOT / "webapp/public_samples")

    @asynccontextmanager
    async def lifespan(_app):
        yield
        manager.shutdown()  # stop a run still owned by this service

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    manager.recover()
    registry = registry or Registry.load(ROOT / "examples/registry.json")
    # session value -> last use (monotonic). Bounded, idle-expiring, never persisted.
    sessions: dict[str, float] = {}
    launch = {"token": token, "used": False}
    cookie = f"{COOKIE}_{port}"  # cookies are not port-isolated; keep instances apart
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    origins = {f"http://{h}" for h in hosts}
    app.state.manager = manager
    app.state.cookie = cookie

    def session_valid(value: str | None) -> bool:
        now = time.monotonic()
        for stale in [s for s, last in sessions.items() if now - last > SESSION_IDLE_SECONDS]:
            del sessions[stale]
        if value not in sessions:
            return False
        sessions[value] = now
        return True

    def respond(data, status=200) -> Response:
        body = json.dumps(data, separators=(",", ":"))
        if registry.contains(body):
            # Defence in depth: never let a registered value reach the browser.
            body, status = json.dumps({"error": "RESPONSE_WITHHELD"}), 500
        return Response(body, status_code=status, media_type="application/json")

    def error(code: str, status: int) -> Response:
        return respond({"error": code}, status)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.headers.get("host") not in hosts:
            return JSONResponse({"error": "HOST_NOT_ALLOWED"}, status_code=421)
        path = request.url.path
        if path.startswith("/api/"):
            mutating = request.method not in ("GET", "HEAD")
            if mutating and (request.headers.get("origin") not in origins
                             or request.headers.get("x-exfilscope") != "1"):
                return JSONResponse({"error": "CROSS_ORIGIN_REJECTED"}, status_code=403)
            if mutating:
                length = request.headers.get("content-length")
                if length is None or not length.isdigit():
                    return JSONResponse({"error": "LENGTH_REQUIRED"}, status_code=411)
                if int(length) > MAX_BODY_BYTES:
                    return JSONResponse({"error": "REQUEST_TOO_LARGE"}, status_code=413)
            # Only the bootstrap exchange itself is reachable without a session.
            bootstrap = path == "/api/session" and request.method == "POST"
            if not bootstrap and not session_valid(request.cookies.get(cookie)):
                code = "SESSION_EXPIRED_OR_STALE" if request.cookies.get(cookie) \
                    else "SESSION_REQUIRED"
                return JSONResponse({"error": code}, status_code=401)
        response = await call_next(request)
        response.headers.update({"Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff",
                                 "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
                                 "Cross-Origin-Opener-Policy": "same-origin",
                                 "X-Frame-Options": "DENY"})
        return response

    # ---- shell -------------------------------------------------------------------------
    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html", media_type="text/html")

    @app.get("/fonts.css")
    def fonts():
        """@font-face rules: the bundled file first, then an installed copy; the CSS stacks
        fall back to system fonts. Nothing is requested from another host."""
        rules = []
        for family, name, weight in FONTS:
            sources = [f'local("{family}")']
            if (STATIC / "fonts" / name).is_file():
                sources.insert(0, f'url("/static/fonts/{name}") format("woff2")')
            rules.append(f'@font-face {{ font-family: "{family}"; font-style: normal; '
                         f'font-weight: {weight}; font-display: swap; src: {", ".join(sources)}; }}')
        return Response("\n".join(rules), media_type="text/css")

    @app.get("/healthz")
    def healthz():
        return respond({"ok": True, "service": "exfilscope-platform",
                        "run_owner": manager.owner})

    @app.get("/icons.json")
    def icons():
        return respond(ICONS)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.post("/api/session")
    async def session(request: Request):
        try:
            supplied = (await request.json()).get("token", "")
        except (ValueError, AttributeError):
            supplied = ""
        if not isinstance(supplied, str) or not hmac.compare_digest(supplied, launch["token"]):
            return error("INVALID_LAUNCH_TOKEN", 401)
        # Single use: the link may persist in browser history or a process command line,
        # so it must not open a second session later.
        if launch["used"]:
            return error("LAUNCH_LINK_ALREADY_USED", 401)
        launch["used"] = True
        value = secrets.token_urlsafe(32)
        while len(sessions) >= MAX_SESSIONS:
            del sessions[min(sessions, key=sessions.get)]
        sessions[value] = time.monotonic()
        response = respond({"ok": True})
        response.set_cookie(cookie, value, httponly=True, samesite="strict", path="/",
                            max_age=SESSION_IDLE_SECONDS)
        return response

    @app.get("/api/session")
    def session_state():
        return respond({"ok": True})

    # ---- read-only views ---------------------------------------------------------------
    @app.get("/api/status")
    def status():
        state = readiness.check()
        active = manager.active
        state["active_run"] = active["run_id"] if active else None
        # False when another ExfilScope service owns the runs folder: evidence is
        # viewable here, but runs can only be started in that service.
        state["run_owner"] = manager.owner
        return respond(state)

    @app.get("/api/scenarios")
    def scenarios():
        return respond({"scenarios": [describe(s) for s in SCENARIOS],
                        "groups": [{"id": g, "title": t, "note": n} for g, t, n in GROUPS],
                        "stages": [{"id": s, "label": label} for s, label in STAGES]})

    @app.get("/api/research")
    def research_records():
        return respond(research.records())

    def display_origin(record: dict) -> str | None:
        # Trust runs are labelled by their extension, not the replay origin the
        # research snapshot schema assigns to their deterministic proposal.
        return record["origin"] if record["mode"] == "trust" else None

    def collection(identifier: str):
        if not COLLECTION.fullmatch(identifier):
            raise KeyError("INVALID_COLLECTION")
        kind, name = identifier.split(":", 1)
        if kind == "snapshot":
            catalog, _ = load_catalog(SNAPSHOTS)
            if name not in catalog:
                raise KeyError("SNAPSHOT_REJECTED_OR_MISSING")
            bundle = catalog[name]
            return {"id": identifier, "kind": "historical", "title": TITLES[name],
                    "source": "Committed engineering snapshot (read-only)",
                    "source_hashes": bundle.source_hashes}, bundle.incidents, None
        snapshot = manager.snapshot(name)
        record = manager.get(name)
        return {"id": identifier, "kind": "platform-run", "title": record["scenario_title"],
                "source": f"Platform run {name} ({record['mode']} mode)",
                "run": {k: record[k] for k in ("run_id", "mode", "protocol", "claim_mode",
                                               "created", "scenario_id", "origin")},
                "source_hashes": snapshot.source_hashes}, snapshot.incidents, display_origin(record)

    @app.get("/api/government-data")
    def government_data():
        from .government_data import load_snapshot

        try:
            return load_snapshot().model_dump(mode="json")
        except (OSError, ValueError):
            return JSONResponse({"error": "OFFICIAL_DATA_UNAVAILABLE"}, status_code=503)

    @app.get("/api/dataset")
    def dataset_view():
        try:
            return respond(dataset.load())
        except (OSError, ValueError, KeyError):
            return error("DATASET_UNAVAILABLE", 500)

    def case_type(origin: str, mode: str | None = None) -> str:
        if mode in ("live", "stub", "trust"):
            return mode
        return {"LLM run": "live", "Controlled fault injection": "fault"}.get(origin, "lab")

    @app.get("/api/cases")
    def cases():
        """One navigation index over every validated collection, plus the lifecycle records of
        runs that produced no validated evidence. Rows keep their collection; nothing here is
        an aggregate result."""
        catalog, issues = load_catalog(SNAPSHOTS)
        rows = []

        def add(collection_id, title, source, incidents, mode=None, created=None, origin=None,
                scenario_id=None, trust_driver=None, operator_lifecycle=False):
            for number, i in enumerate(incidents, 1):
                situation = scenario_id or SNAPSHOT_SCENARIO.get(
                    (i.scenario, i.runtime.decision) if i.scenario == "payload_divergence"
                    else i.scenario)
                rows.append({"collection": collection_id, "collection_title": title,
                             "scenario_id": situation, "trust_driver": trust_driver,
                             "operator_lifecycle": operator_lifecycle, "delivery_index": number,
                             "source": source, "type": case_type(i.origin, mode),
                             "event_id": str(i.runtime.event_id), "trace": str(i.runtime.trace_id),
                             "scenario_title": title_of(i), "decision": i.runtime.decision,
                             "result": i.verification.result,
                             "labels": list(i.verification.labels),
                             "diagnostics": list(i.verification.diagnostics),
                             "protocol": i.protocol, "display_origin": origin or i.origin,
                             "created": created, "run_id": i.run_id})

        for name, bundle in catalog.items():
            add(f"snapshot:{name}", TITLES[name], "historical", bundle.incidents)
        incomplete = []
        for record in manager.list():
            if record["status"] != "succeeded":
                incomplete.append({k: record.get(k) for k in (
                    "run_id", "scenario_id", "scenario_title", "mode", "protocol", "origin",
                    "status", "error", "created", "finished")})
                continue
            try:
                snapshot = manager.snapshot(record["run_id"])
            except (KeyError, OSError, ValueError):
                issues.append(f"{record['run_id']}: run snapshot rejected.")
                continue
            add(f"run:{record['run_id']}", record["scenario_title"], "bundled-sample" if manager.is_sample(record["run_id"]) else "platform-run",
                snapshot.incidents, record["mode"], record["created"], display_origin(record),
                record["scenario_id"], record.get("trust_driver"), record.get("operator_lifecycle", False))
        return respond({"cases": rows, "types": CASE_TYPES, "incomplete": incomplete,
                        "issues": issues})

    @app.get("/api/investigations")
    def investigations():
        catalog, issues = load_catalog(SNAPSHOTS)
        items = [{"id": f"snapshot:{name}", "kind": "historical", "title": TITLES[name],
                  **summary(bundle.incidents)} for name, bundle in catalog.items()]
        for record in manager.list():
            if record["status"] == "succeeded":
                try:
                    snapshot = manager.snapshot(record["run_id"])
                except (KeyError, OSError, ValueError):
                    issues.append(f"{record['run_id']}: run snapshot rejected.")
                    continue
                items.append({"id": f"run:{record['run_id']}", "kind": "platform-run",
                              "title": record["scenario_title"], "mode": record["mode"],
                              "created": record["created"],
                              **summary(snapshot.incidents, display_origin(record))})
        return respond({"collections": items, "issues": issues})

    @app.get("/api/investigations/{identifier}")
    def investigation(identifier: str):
        try:
            meta, incidents, origin = collection(identifier)
        except (KeyError, OSError, ValueError):
            return error("COLLECTION_UNAVAILABLE", 404)
        return respond({**meta, "summary": summary(incidents, origin),
                        "incidents": [incident_view(i, origin) for i in incidents]})

    @app.get("/api/investigations/{identifier}/export.csv")
    def investigation_csv(identifier: str):
        try:
            _, incidents, _ = collection(identifier)
        except (KeyError, OSError, ValueError):
            return error("COLLECTION_UNAVAILABLE", 404)
        data = export_csv(incidents)
        if registry.contains(data.decode("utf-8")):
            return error("RESPONSE_WITHHELD", 500)
        name = identifier.replace(":", "-")
        return Response(data, media_type="text/csv", headers={
            "Content-Disposition": f'attachment; filename="exfilscope-{name}.csv"'})

    # ---- runs --------------------------------------------------------------------------
    @app.get("/api/runs")
    def runs():
        return respond({"runs": [r for r in manager.list() if not manager.is_sample(r["run_id"])]})

    @app.get("/api/runs/{run_id}")
    def run(run_id: str):
        try:
            return respond(manager.get(run_id))
        except (KeyError, OSError, ValueError):
            return error("UNKNOWN_RUN", 404)

    @app.post("/api/runs")
    async def start(request: Request):
        try:
            payload = await request.json()
            run_request = RunRequest.model_validate(payload)
        except ValidationError as exc:
            codes = sorted({str(e.get("ctx", {}).get("error", e["type"])) for e in exc.errors()})
            return respond({"error": "INVALID_RUN_REQUEST",
                            "codes": [c if c.isupper() else "FIELD_INVALID" for c in codes]}, 422)
        except ValueError:
            return error("INVALID_JSON", 400)
        if not manager.owner:
            return error("RUNS_OWNED_BY_OTHER_SERVICE", 409)
        state = readiness.check()
        if run_request.trust_driver == "qwen3" and not any(
                item["id"] == "ollama" and item["state"] == "healthy"
                for item in state.get("items", [])):
            return respond({"error": "MODE_UNAVAILABLE", "blocking": ["ollama"]}, 503)
        mode_state = state["modes"][run_request.mode]
        if not mode_state["ready"]:
            return respond({"error": "MODE_UNAVAILABLE", "blocking": mode_state["blocking"]}, 503)
        try:
            return respond(manager.start(run_request, operator_id=(
                "local-session-" + hashlib.sha256(request.cookies[cookie].encode()).hexdigest()[:16]
            ) if run_request.operator_lifecycle else None), 202)
        except Busy:
            return error("RUN_ALREADY_ACTIVE", 409)
        except NotOwner:
            return error("RUNS_OWNED_BY_OTHER_SERVICE", 409)

    @app.post("/api/runs/{run_id}/authority")
    async def authority(run_id: str, request: Request):
        try:
            payload = await request.json()
            if not isinstance(payload, dict) or set(payload) != {"operation"} or not isinstance(payload["operation"], str):
                raise ValueError("INVALID_AUTHORITY_OPERATION")
            actor = "local-session-" + hashlib.sha256(request.cookies[cookie].encode()).hexdigest()[:16]
            return respond(manager.authority_command(run_id, payload["operation"], actor), 202)
        except PermissionError:
            return error("OPERATOR_SESSION_MISMATCH", 403)
        except (KeyError, ValueError):
            return error("INVALID_AUTHORITY_OPERATION", 422)
        except Busy as exc:
            return error(str(exc), 409)

    @app.post("/api/runs/{run_id}/cancel")
    def cancel(run_id: str):
        try:
            return respond(manager.cancel(run_id))
        except KeyError:
            return error("RUN_NOT_ACTIVE", 409)

    trust.register(app, respond, error)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="ExfilScope local platform service")
    parser.add_argument("--port", type=int, default=8600)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    supplied = os.environ.pop("EXFILSCOPE_UI_TOKEN", "")
    token = supplied or secrets.token_urlsafe(32)
    app = create_app(token=token, port=args.port)
    if not supplied:
        # Started by hand: the operator needs the session link. The launcher knows it already.
        print(f"Open http://127.0.0.1:{args.port}/#t={token}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_config=None, log_level="warning",
                access_log=False, server_header=False)


if __name__ == "__main__":
    main()
