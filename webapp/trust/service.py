"""Read-only API route for trust audits; runs start through the ordinary run endpoint."""

from .audit import load_trust_audit


def register(app, respond, error):
    @app.get("/api/trust/{run_id}")
    def trust_audit(run_id: str):
        manager = app.state.manager
        try:
            record = manager.get(run_id)
            if record["mode"] != "trust" or record["status"] != "succeeded":
                raise KeyError("NOT_A_TRUST_RUN")
            manager.snapshot(run_id)
            audit = load_trust_audit(manager.path(run_id) / "export")
        except (KeyError, OSError, ValueError):
            return error("TRUST_AUDIT_UNAVAILABLE", 404)
        return respond(audit.model_dump(mode="json"))
