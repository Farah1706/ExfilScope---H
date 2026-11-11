"""Local POST /execute tool boundary; authorization stays in the deterministic gateway."""

import os
import ssl
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from .canonical import MAX_BODY
from .config import Catalog, load_key
from .contracts import ProposedAction
from .gateway import Gateway
from .ledger import RuntimeWriter
from .registry import Registry
from .runtime import Runtime
from .policy import GatewayPolicy


def create_app(gateway: Gateway, runtime: Runtime) -> FastAPI:
    app = FastAPI(title="ExfilScope lab gateway", docs_url=None, redoc_url=None)

    @app.post("/execute")
    async def execute(request: Request) -> JSONResponse:
        # Do not use FastAPI's default validation response, which can echo tool inputs.
        size = 0
        chunks = []
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_BODY * 2:
                event = gateway.reject_invalid_schema()
                return JSONResponse(event.model_dump(mode="json"), status_code=400)
            chunks.append(chunk)
        try:
            action = ProposedAction.model_validate_json(b"".join(chunks))
        except ValidationError:
            event = gateway.reject_invalid_schema()
            return JSONResponse(event.model_dump(mode="json"), status_code=400)
        # Synchronous network and SQLite work runs in a worker thread.
        def handle():
            return runtime.execute(gateway.authorize(action))
        try:
            event = await run_in_threadpool(handle)
            return JSONResponse(event.model_dump(mode="json"))
        except Exception:
            return JSONResponse({"error_category": "EVIDENCE_OR_RUNTIME_FAILURE"}, status_code=503)

    return app


def app_from_env() -> FastAPI:
    # Refuse to start rather than authorize requests under an unfrozen default policy.
    if not os.environ.get("EXFILSCOPE_POLICY_FILE"):
        raise ValueError("EXFILSCOPE_POLICY_FILE_REQUIRED")
    policy = GatewayPolicy.load(Path(os.environ["EXFILSCOPE_POLICY_FILE"]))
    writer = RuntimeWriter(Path(os.environ["EXFILSCOPE_LEDGER_A"]))
    gateway = Gateway(Registry.load(Path(os.environ["EXFILSCOPE_REGISTRY"])), Catalog.from_env(),
                      set(os.environ["EXFILSCOPE_APPROVED"].split(",")),
                      load_key(Path(os.environ["EXFILSCOPE_KEY_FILE"])),
                      os.environ.get("EXFILSCOPE_KEY_ID", "lab-key-1"), writer, policy=policy)
    context = None
    if os.environ.get("EXFILSCOPE_PROXY_CA"):
        context = ssl.create_default_context(cafile=os.environ["EXFILSCOPE_PROXY_CA"])
    return create_app(gateway, Runtime(writer, os.environ["EXFILSCOPE_PROXY"], context))
