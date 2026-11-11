# Technical guide

## Protected execution

Two callers feed the same in-process interface, `ProtectedDispatch.execute(capability, proof, action)`. The seven-attempt scripted driver exercises negative controls. The live driver runs under an official-data mandate (next section): pinned Qwen3 selects up to three cells from the approved GDRFA Dubai table and returns the requested endpoint, the server renders the sandbox-only brief from those cells, and the agent signs the exact action under the pilot workload scope. A selection outside the mandate stops the run before dispatch. The audit includes the mandate, the cited cells and the signed action commitment.

An action contains task, tool, endpoint ID, method, route ID and a JSON object body. A trusted issuer signs the scope and registered key binding. The agent adapter signs the exact canonical action and one-time ID. The dispatch validates the proof against a canonical snapshot and checks the fixed server task and route before calling the deterministic gateway. The mapped receiver URL comes from the local harness. The gateway can still deny or redact a permitted proposal. Rejected Trust actions call neither gateway nor transport. Revocation and replay use one synchronized in-memory validator. An accepted grant is consumed before gateway execution, including ambiguous failures. There is no automatic retry.

The protected Trust dispatch is opt-in. The legacy HTTP tool endpoint and ordinary Lab/stub/live scenarios retain their own deterministic gateway policy. They do not require a Trust capability. Keys live in the supervisor process, with no hardware-backed or external identity claim. The second caller reuses the same local contract. We only tested on Windows with this one model family.

## Evidence and operational limits

The proxy writes Ledger B independently of the runtime's Ledger A writer. A verifier result concerns the bounded configured path, and inadequate evidence stays UNVERIFIED. A divergence can be detected after emission. Trust pre-gateway rejects are shown in the Trust audit with independent harness receiver counts. They do not generate a forensic MATCH. Proofs, private keys and raw notice bodies are outside the exported audit.

The model service, receiver, proxy and verifier have distinct failure modes. If Ollama is absent, use the scripted run. If proxy setup or the lab fails, show a recorded run. Missing paired evidence stays UNVERIFIED. Pause the pilot on monitoring loss and fall back to manual review. Host-wide containment, persistent replay, availability under load and production key custody remain outside this prototype.

The authorization benchmark alternates matched baseline and protected in-process dispatch with a mocked gateway/runtime. It records 300 pairs after 30 warmups, nearest-rank p50/p95, and a replay-rejection series. Use scripts/benchmark_trust.py with a new path under artifacts. This excludes model, network and SQLite. Retained capstone results are separate.

The pilot planner compares the 2024 and 2025 GDRFA Dubai annual RES Transactions rows. It divides the modeled annual actions by the days in the selected calendar year and scales to the trial duration. Report PDFs, retrieval date and source SHA-256 digests are recorded in the bundled normalized snapshot. These aggregate counts cover GDRFA Dubai operations and cannot establish renewal-only demand, individual records, UAE-wide population or traffic peaks. GDRFA Dubai allows reuse with attribution, accuracy and scope preserved. [Official tables](https://www.gdrfad.gov.ae/en/statistics) · [Reuse terms](https://www.gdrfad.gov.ae/en/open-data-policy)

Normal launches and the recorded website read the bundled data offline. To refresh, use a separate tooling environment with the locked app dependencies and pypdf 6.x. Run `python scripts/refresh_government_data.py 2024 2025` from the Hackathon root. The script fetches the specified completed annual reports directly from the publisher, validates the table layout and stages a new JSON candidate in the Hackathon artifacts folder. Compare the reported rows and PDF hashes with the publisher, review definition changes, promote the candidate to `webapp/static/government-data.json`, then run the data tests and rebuild the replay. The updater refuses to overwrite an existing candidate. The planner flags old snapshots and stops estimating when the snapshot is unavailable.

Bundled third-party notices are in dashboard/THIRD_PARTY_NOTICES.md.
## Independent loopback HTTP integration

The opt-in sandbox supervisor can bind `webapp.trust.http_api.serve(dispatch)` to an ephemeral port on 127.0.0.1. This is separate from the web launcher and from the legacy /execute route. The supervisor registers the known client key and supplies an Ed25519 capability out of band. There is no HTTP key registration or grant issuance.

`POST /v1/protected-action` requires UTF-8 application/json and exactly three fields. The action is the existing task, tool, endpoint_id, method, route_id and body object. The capability and proof are strings. The client signs RFC 8785 canonical JSON over the action, capability jti and Unix timestamp in seconds. The request limit is 32,768 bytes. Duplicate JSON keys, nonfinite values and malformed shapes are rejected. The server verifies before dispatch and binds the receiver to the configured sandbox route.

| Status | Meaning |
|---|---|
| 200 | Trust accepted, with event ID, gateway decision, runtime claim and receiver status. Read the gateway decision to distinguish BLOCK from an emitted request. |
| 400 / 413 / 415 | Invalid envelope, excessive size, or wrong media type. |
| 403 | Capability, signature, proof, scope or replay rejected before gateway dispatch. |
| 502 | Transport failure or downstream 5xx. The body still carries the event reference. |
| 503 | Dispatch or evidence failure. The action may be ambiguous. Investigate before issuing a new grant. |

The caller should time out without automatic retry. A timeout cannot establish that nothing crossed the network. The Node.js sample uses a 10-second client timeout and holds its own key. The sandbox runtime has a bounded receiver timeout. The result ID links to the same Ledger A, independent proxy observation and verifier used by the Trust lab. The HTTP response never includes payload, key, capability or proof.

Run the isolated example with Node.js 20+ and the core environment.

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q --basetemp artifacts/adapter-validation webapp/tests/test_trust_http.py
```

The test supervisor provisions a real loopback listener and a real proxied HTTPS lab. The separate Node client uses only standard runtime APIs. Review the port, key custody and test scope before adapting to a separate host. No shared gateway policy or legacy route is changed.

## Official-data mandate

The live Trust task uses [GDRFA Dubai's annual statistics](https://www.gdrfad.gov.ae/en/open-data).
The pinned extract covers 2018 to 2025 with five metrics per year. It carries each workbook URL and
SHA-256. The Trust task gives Qwen3 four candidate cells from the two latest years, covering
residence and entry permit transactions. The separate Pilot Planner uses the two PDF-derived
residence counts. These are counts of government transactions.

The loader checks the extract's SHA-256 and arithmetic and cross-checks the two residence counts
against the Planner snapshot. The v7 audit also downloaded and verified all eight source workbooks
against the pinned hashes and all 40 headline cells. The release contains the extract and the
workbook references. The workbook files and verification log are retained in local audit artifacts.

Qwen3 selects years and metrics. The server generates a signed brief containing the publisher,
snapshot digest, unit, workbook URL and hash, exact cells and deterministic text. The dispatcher
checks the signature and scope, then reconstructs the entire brief from the approved cells. It
rejects duplicate JSON keys, duplicate citations, unsupported cells, altered values or prose,
and additional fields. After the gateway returns, dispatch checks the permitted body again before
giving it to the runtime. The existing gateway policy and wire envelope are shared with earlier
releases.

The three live attempts show an approved brief, an out-of-scope destination, and a labelled
test fixture that changes one digit in the rendered brief. The latter two stop before the gateway
and have zero receiver requests. The lifecycle run has five attempts with the receiver pattern
`[1, 0, 0, 1, 0]`. Earlier recordings remain replayable with their original check labels. The
v7 recording identifies the stricter binding in its audit.

## Interactive sandbox operator lifecycle

Select Live local Qwen3 and enable operator approval, revocation and recovery. Start prepares the isolated lab and waits up to 90 seconds per decision. The initiating launch session authorizes the public-data task, withdraws the registered identity after the first observed delivery, and approves a fresh identity for recovery. State changes use authenticated same-origin POST requests bound to that session and active run. Concurrent or repeated decisions are rejected. No issuance or emergency endpoint is public.

The runner uses the existing Issuer, Validator and ProtectedDispatch. Revocation happens before checking both an unused signed grant and the earlier consumed grant. Recovery registers a different identity and key, leaving the old identity revoked. A final negative control confirms that withdrawal survived recovery. Both actual permitted deliveries retain their own runtime event, observation and verdict in the Hackathon export.

This controls the protected integration only. It does not cancel requests already in flight. Authority and keys remain in runner memory. Cancellation or service restart ends the run; unfinished state is marked interrupted, and a new run requires new approval. The operator identifier attributes decisions to a local launch session, not to a government identity provider. Production sponsor approval, hardware custody, distributed revocation and service recovery procedures remain external pilot requirements.
