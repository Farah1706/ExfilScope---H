"""Run lifecycle: one fixed runner subprocess at a time, with timeouts and cancellation."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import threading
import time

from .contracts import RUN_ID, STAGE_IDS, STAGE_STATES, STAGES, RunRequest
from .evidence import load_run_snapshot
from .paths import ROOT, RUNS, core_python
from .scenarios import BY_ID

TIMEOUTS = {"lab": 180, "stub": 420, "live": 600, "trust": 180}
SAFE_TEXT = re.compile(r"^[A-Za-z0-9 ,.:;()_/'’…-]{0,160}$")
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.:-]{0,96}$")
FACT_KEYS = {"decision", "reason", "policy", "claim", "fault", "paired", "window_seconds",
             "result", "evidence_status", "labels", "protocol", "case", "lab_scenario", "task",
             "api_calls", "expected", "incidents", "run_id", "operator_state", "operator_code",
             "receiver_requests", "initial_receiver_requests", "operator_verdict"}
# Environment names passed to the runner; everything else (proxies, tokens) is dropped.
ENV_KEEP = {"SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP", "USERPROFILE", "APPDATA",
            "LOCALAPPDATA", "PATH", "PATHEXT", "COMSPEC", "NUMBER_OF_PROCESSORS",
            "PROCESSOR_ARCHITECTURE", "EXFILSCOPE_AGENT_PYTHON", "EXFILSCOPE_EMBEDDING_CACHE",
            "EXFILSCOPE_ENV_ROOT"}


class Busy(Exception):
    pass


class NotOwner(Exception):
    pass


class Ownership:
    """Exclusive claim on a runs folder by one service process.

    The claim is an OS byte-range lock (msvcrt on Windows, flock elsewhere) on
    ``.service.lock``. The operating system drops it when the owning process exits for any
    reason, so a crashed owner never blocks recovery, and a healthy owner can never be
    mistaken for a dead one.
    """

    def __init__(self, runs: Path):
        self.path = runs / ".service.lock"
        self.handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")  # noqa: SIM115 - held open for the process lifetime
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self.handle = handle
        return True

    def release(self) -> None:
        if self.handle is not None:
            try:
                if os.name == "nt":
                    import msvcrt

                    self.handle.seek(0)
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            self.handle.close()
            self.handle = None


def safe_fact(value):
    if isinstance(value, bool) or (isinstance(value, (int, float)) and not isinstance(value, bool)):
        return value
    if isinstance(value, str) and SAFE_TOKEN.fullmatch(value):
        return value
    if isinstance(value, list) and all(isinstance(v, str) and SAFE_TOKEN.fullmatch(v)
                                       for v in value):
        return value[:16]
    return None


def _retry(operation):
    """Windows refuses to replace or open a file another handle is using; retry briefly."""
    for attempt in range(40):
        try:
            return operation()
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(0.025)


def write_json(path: Path, data: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    _retry(lambda: os.replace(temporary, path))


def read_json(path: Path) -> dict:
    return json.loads(_retry(lambda: path.read_text(encoding="utf-8")))


def runner_environment(runs: Path) -> dict:
    environment = {k: v for k, v in os.environ.items() if k.upper() in ENV_KEEP}
    environment.update(EXFILSCOPE_PLATFORM_RUNS=str(runs.resolve()),
                       PYTHONPATH=os.pathsep.join([str(ROOT), str(ROOT / "src")]),
                       PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    return environment


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("run-%Y%m%d-%H%M%S-") + secrets.token_hex(4)


class RunManager:
    def __init__(self, runs: Path = RUNS, command: list[str] | None = None,
                 samples: Path | None = None):
        from exfilscope.registry import Registry

        self.runs = runs
        self.samples = samples
        self.command = command
        self.registry = Registry.load(ROOT / "examples/registry.json")
        self.lock = threading.Lock()
        self.active: dict | None = None
        self.finished: dict[str, dict] = {}
        self.ownership = Ownership(runs)
        # Only the owner may start runs or rewrite other runs' records; a second service on
        # the same folder serves evidence read-only.
        self.owner = self.ownership.acquire()

    def recover(self) -> None:
        """Holding the claim proves no live service owns these runs, so a record still marked
        running was left by an owner that stopped."""
        if not self.owner:
            return
        for record in self.list():
            if record["status"] == "running" and not self.is_sample(record["run_id"]):
                record.update(status="interrupted", error="SERVICE_STOPPED_DURING_RUN",
                              finished=record["finished"] or time.time())
                write_json(self.path(record["run_id"]) / "lifecycle.json", record)

    # ---- lifecycle records -------------------------------------------------------------
    def path(self, run_id: str) -> Path:
        if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
            raise KeyError("INVALID_RUN_ID")
        path = (self.runs / run_id).resolve()
        if path.parent != self.runs.resolve():
            raise KeyError("INVALID_RUN_ID")
        if (self.samples is not None and not path.exists()
                and (self.samples / run_id / "lifecycle.json").is_file()):
            return self.samples / run_id
        return path

    def is_sample(self, run_id: str) -> bool:
        return self.samples is not None and self.path(run_id).parent.resolve() == self.samples.resolve()

    def get(self, run_id: str) -> dict:
        path = self.path(run_id) / "lifecycle.json"
        with self.lock:
            # The active run is served from memory, so polling never races its file writes.
            active = self.active
            if active is not None and active["run_id"] == run_id:
                return json.loads(json.dumps(active["record"]))
            # A run this service finished is final in memory, even if its last write failed.
            if run_id in self.finished:
                return json.loads(json.dumps(self.finished[run_id]))
        if not path.is_file():
            raise KeyError("UNKNOWN_RUN")
        return read_json(path)

    def list(self) -> list[dict]:
        folders = [self.runs]
        if self.samples is not None:
            folders.append(self.samples)
        names = {p.name for folder in folders if folder.is_dir() for p in folder.iterdir()}
        records = []
        for name in sorted(names, reverse=True):
            path = self.path(name) if RUN_ID.fullmatch(name) else self.runs / name
            if RUN_ID.fullmatch(path.name) and (path / "lifecycle.json").is_file():
                try:
                    records.append(self.get(path.name))
                except (OSError, ValueError, KeyError):
                    continue
        return records

    def snapshot(self, run_id: str):
        record = self.get(run_id)
        if record["status"] != "succeeded":
            raise KeyError("RUN_HAS_NO_VALIDATED_EVIDENCE")
        return load_run_snapshot(self.path(run_id) / "export")

    # ---- execution ---------------------------------------------------------------------
    def start(self, request: RunRequest, operator_id: str | None = None) -> dict:
        if request.operator_lifecycle and not re.fullmatch(r"local-session-[0-9a-f]{16}", operator_id or ""):
            raise ValueError("OPERATOR_SESSION_REQUIRED")
        with self.lock:
            if not self.owner:
                raise NotOwner("RUNS_OWNED_BY_OTHER_SERVICE")
            if self.active is not None:
                raise Busy("RUN_ALREADY_ACTIVE")
            run_id = new_run_id()
            run = self.path(run_id)
            run.mkdir(parents=True, exist_ok=False)
            scenario = BY_ID[request.scenario_id]
            record = {
                "schema_version": "platform-lifecycle-1.0", "run_id": run_id,
                "scenario_id": scenario.id, "scenario_title": scenario.title,
                "mode": request.mode, "protocol": request.protocol,
                "protected_item": request.protected_item, "claim_mode": request.claim_mode,
                "trust_driver": request.trust_driver,
                "operator_lifecycle": request.operator_lifecycle,
                "operator_id": operator_id if request.operator_lifecycle else None,
                "origin": {"live": "LLM run", "stub": "Deterministic replay"}.get(
                    request.mode, scenario.origin if scenario.origin != "Normal condition"
                    else "Deterministic replay"),
                "status": "running", "created": time.time(), "finished": None,
                "exit_code": None, "error": None, "timeout_seconds": 600 if request.operator_lifecycle else TIMEOUTS[request.mode],
                "stages": [{"id": s, "label": label, "status": "pending", "detail": "",
                            "facts": {}, "at": None} for s, label in STAGES],
                "history": [],
            }
            record["stages"][0]["status"] = "running"
            record["owner_pid"] = os.getpid()
            write_json(run / "lifecycle.json", record)
            (run / "restricted").mkdir()
            stderr = (run / "restricted" / "runner-stderr.log").open("w", encoding="utf-8")
            command = self.command or [str(core_python()), "-B", "-m", "webapp.runner"]
            try:
                process = subprocess.Popen(
                    command, cwd=ROOT, env=runner_environment(self.runs), stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=stderr, text=True, encoding="utf-8",
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            except OSError:
                stderr.close()
                record.update(status="failed", error="RUNNER_START_FAILED", finished=time.time())
                record["stages"][0].update(status="failed", detail="RUNNER_START_FAILED")
                write_json(run / "lifecycle.json", record)
                return record
            self.active = {"run_id": run_id, "process": process, "record": record,
                           "cancelled": False, "timed_out": False, "stderr": stderr}
            threading.Thread(target=self._follow, args=(self.active,), daemon=True).start()
            threading.Thread(target=self._watchdog, args=(self.active,), daemon=True).start()
            try:
                process.stdin.write(json.dumps({"run_id": run_id, "operator_id": record["operator_id"],
                                                **request.model_dump()}))
                process.stdin.close()
            except OSError:
                pass  # the runner exited at once; _follow records the failure
            return record

    def _update(self, active: dict, line: str) -> None:
        try:
            event = json.loads(line)
        except ValueError:
            return
        if not isinstance(event, dict) or event.get("xs_stage") not in STAGE_IDS \
                or event.get("status") not in STAGE_STATES:
            return
        detail = event.get("detail", "")
        detail = detail if isinstance(detail, str) and SAFE_TEXT.fullmatch(detail) \
            else "DETAIL_WITHHELD"
        raw = event.get("facts")
        facts = {k: safe_fact(v) for k, v in (raw if isinstance(raw, dict) else {}).items()
                 if k in FACT_KEYS and safe_fact(v) is not None}
        # Runner output is fixed text and codes, but never persist a registered value.
        if self.registry.contains(json.dumps([detail, facts])):
            detail, facts = "DETAIL_WITHHELD", {}
        record = active["record"]
        with self.lock:
            index = STAGE_IDS.index(event["xs_stage"])
            stage = record["stages"][index]
            stage.update(status=event["status"], detail=detail, at=time.time())
            stage["facts"].update(facts)
            # Stages change only on an explicit runner record; nothing advances on a timer.
            record["history"].append({"stage": event["xs_stage"], "status": event["status"],
                                      "at": stage["at"]})
            write_json(self.path(record["run_id"]) / "lifecycle.json", record)

    def _follow(self, active: dict) -> None:
        """Follow the runner to its end. Whatever fails here, the run gets a terminal record
        and the service is released for the next run."""
        process, record = active["process"], active["record"]
        try:
            for line in process.stdout:
                try:
                    self._update(active, line)
                except Exception:  # a bad line must never strand the run
                    continue
            code = process.wait()
            with self.lock:
                record["exit_code"] = code
                record["finished"] = time.time()
                if active["timed_out"] or active["cancelled"]:
                    record["status"] = "timed_out" if active["timed_out"] else "cancelled"
                    record["error"] = ("RUN_TIMED_OUT" if active["timed_out"]
                                       else "CANCELLED_BY_USER")
                elif code == 0:
                    try:
                        load_run_snapshot(self.path(record["run_id"]) / "export")
                        record["status"] = "succeeded"
                    except Exception:  # any loader failure means no validated evidence
                        record["status"], record["error"] = "failed", "EXPORT_REJECTED_BY_LOADER"
                else:
                    record["status"] = "failed"
                    failed = next((s for s in record["stages"] if s["status"] == "failed"), None)
                    record["error"] = failed["detail"] if failed else "RUNNER_FAILED"
                self._close_stages(record)
                write_json(self.path(record["run_id"]) / "lifecycle.json", record)
        except Exception:
            with self.lock:
                record.update(status="failed", error="SUPERVISION_ERROR",
                              finished=record.get("finished") or time.time())
                self._close_stages(record)
                try:
                    write_json(self.path(record["run_id"]) / "lifecycle.json", record)
                except OSError:
                    pass  # the in-memory record below is still final; restart marks it
        finally:
            try:
                active["stderr"].close()
            except OSError:
                pass
            with self.lock:
                self.finished[record["run_id"]] = record
                if self.active is active:
                    self.active = None

    @staticmethod
    def _close_stages(record: dict) -> None:
        if record["status"] != "succeeded":
            for stage in record["stages"]:
                if stage["status"] == "running":
                    stage["status"] = "failed"
                    stage["detail"] = record["error"]

    def _watchdog(self, active: dict) -> None:
        deadline = active["record"]["created"] + active["record"].get("timeout_seconds", TIMEOUTS[active["record"]["mode"]])
        while active["process"].poll() is None:
            if time.time() > deadline:
                active["timed_out"] = True
                self._kill(active["process"])
                return
            time.sleep(0.5)

    @staticmethod
    def _kill(process: subprocess.Popen) -> None:
        # The runner owns mitmdump, receivers and agent workers: end the whole tree.
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)],
                           capture_output=True, check=False,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            process.kill()

    def authority_command(self, run_id: str, operation: str, operator_id: str) -> dict:
        expected = {"authorize": "WAITING_AUTHORIZATION", "revoke": "WAITING_REVOCATION",
                    "recover": "WAITING_RECOVERY"}
        if operation not in expected:
            raise ValueError("INVALID_AUTHORITY_OPERATION")
        with self.lock:
            active = self.active
            if not self.owner or active is None or active["run_id"] != run_id:
                raise Busy("RUN_NOT_ACTIVE")
            record = active["record"]
            if not record.get("operator_lifecycle"):
                raise Busy("NOT_OPERATOR_LIFECYCLE")
            if record.get("operator_id") != operator_id:
                raise PermissionError("OPERATOR_SESSION_MISMATCH")
            state = record["stages"][STAGE_IDS.index("gateway")]["facts"].get("operator_state")
            path = self.path(run_id) / ("operator-" + operation + ".json")
            if record["status"] != "running" or state != expected[operation] or path.exists():
                raise Busy("AUTHORITY_STATE_CONFLICT")
            write_json(path, {"operation": operation, "actor": operator_id, "at": time.time()})
            return {"operation": operation, "status": "queued"}

    def cancel(self, run_id: str) -> dict:
        with self.lock:
            active = self.active
            if active is None or active["run_id"] != run_id:
                raise KeyError("RUN_NOT_ACTIVE")
            active["cancelled"] = True
        self._kill(active["process"])
        return self.get(run_id)

    def shutdown(self) -> None:
        active = self.active
        if active is not None:
            active["cancelled"] = True
            self._kill(active["process"])
            deadline = time.time() + 10
            while self.active is not None and time.time() < deadline:
                time.sleep(0.1)  # let _follow write the terminal record while still owner
        self.ownership.release()
