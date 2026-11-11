"""Opt-in loopback HTTP boundary for one protected sandbox dispatch."""

from contextlib import contextmanager
import json
import socket
import threading
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
import uvicorn

from .capability import Rejected

MAX_ENVELOPE_BYTES = 32_768


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_KEY")
        result[key] = value
    return result


def reject_constant(_):
    raise ValueError("NONFINITE_JSON")


def create_app(dispatch):
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    @app.post("/v1/protected-action")
    async def protected_action(request: Request):
        if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
            return JSONResponse({"code": "JSON_REQUIRED"}, status_code=415)
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > MAX_ENVELOPE_BYTES:
                return JSONResponse({"code": "ENVELOPE_TOO_LARGE"}, status_code=413)
            raw.extend(chunk)
        try:
            envelope = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                                  parse_constant=reject_constant)
            if (not isinstance(envelope, dict)
                    or envelope.keys() != {"action", "capability", "proof"}
                    or not isinstance(envelope["action"], dict)
                    or any(not isinstance(envelope[k], str) for k in ("capability", "proof"))):
                raise ValueError("INVALID_ENVELOPE")
        except (ValueError, RecursionError):
            return JSONResponse({"code": "INVALID_ENVELOPE"}, status_code=400)
        try:
            _, event = await run_in_threadpool(dispatch.execute, **envelope)
        except Rejected as exc:
            return JSONResponse({"code": exc.code}, status_code=403)
        except Exception:
            # The grant may have been consumed and the delivery may be ambiguous.
            return JSONResponse({"code": "DISPATCH_UNAVAILABLE"}, status_code=503)
        status = 200
        if event.claim.value == "EXECUTED_FAILED" or (event.response_status or 0) >= 500:
            status = 502
        return JSONResponse({"event_id": str(event.event_id), "decision": event.decision.value,
                             "claim": event.claim.value, "receiver_status": event.response_status},
                            status_code=status)

    return app


@contextmanager
def serve(dispatch):
    """Bind an ephemeral loopback socket, owned by the sandbox supervisor."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(16)
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(create_app(dispatch), lifespan="off",
                                              log_config=None, log_level="critical",
                                              access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if not thread.is_alive() or time.monotonic() > deadline:
                    raise RuntimeError("PROTECTED_LISTENER_START_FAILED")
                time.sleep(0.02)
            yield f"http://127.0.0.1:{port}/v1/protected-action"
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError("PROTECTED_LISTENER_SHUTDOWN_FAILED")
