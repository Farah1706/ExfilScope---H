# Status

Last updated 11 November 2026.

## Hackathon version

The website opens on the government example: a recorded Qwen3 run where the approved brief is delivered and a brief with a changed figure is stopped before sending. The Government Trust checks bind every figure to an exact cell in GDRFA Dubai's published workbooks and check the signed request before it is sent.

Results from our test runs on 10 November 2026:

- Signed HTTPS test: the one valid request was sent once. All 17 invalid requests were rejected, and the receiver got none of them.
- Live approve, withdraw and recover run `run-20261110-080242-73871aeb`: receiver counts were [1, 0, 0, 1, 0], with two MATCH results. Rejected attempts were stopped before the gateway, so they have no MATCH/MISMATCH result.
- All eight GDRFA source workbooks matched their pinned SHA-256 values, and all 40 headline figures matched.
- Web app tests: 168 passed, 1 skipped. Agent tests: 22 passed. Supervisor tests: 7 passed.
- Core tests: 484 passed, 2 failed, 2 skipped. Both failures need an archived Git object that is not in this copy. The tests were not changed to make them pass.
- We checked the website in Chrome at desktop, tablet and phone widths.

We have not yet tested whether a new user understands the website within a minute.

## Current state

| | |
|---|---|
| Implementation | Gateway, proxy monitor, two ledgers, verifier, test lab, Qwen3 agent, web app and the Government Trust extension |
| Timing parameters | W = 5 s, G = 1 s, h = 0.6576741600001696 s, from the D5 40-request container calibration (40 of 40 valid) |
| Capstone collection | Experiment `e1-c2292f76f71a`: 42 primary and 6 supplementary cases, all scored correctly. Diagnostics `e1-6e021d09d252`: 24 of 24 correct. Timing: 180 of 180 valid pairs |
| Human review study | Not done. The 48 review packages are prepared, but no reviewers have answered yet |

## Known issues

- In one fault mode, a blocked request can record `EXECUTED_SUCCESS`. The verifier reports `BLOCK_BYPASS` but does not also flag the wrong Ledger A claim.
- `POST /execute` returns the full Ledger A event. The agent only keeps the event ID and decision, but the API should return only those.
- The monitor's health check does not test for raw flow capture. Capture is off because no launcher turns it on.
- `tests/test_integration.py::test_timeout_keeps_independent_request_evidence` can fail on a heavily loaded machine.

None of these can produce a false MATCH.

## Limitations

- On Windows, all local services run under one user account. They are not isolated from each other the way the Docker setup is.
- A proxy observation shows what crossed the proxy. It does not show what the remote side did with it.
- The ledgers are not signed, and clock IDs are declared, not proven.
- The local tool API has no login, so it must stay on 127.0.0.1 or a private network.
- The privacy scanner only finds known values in the formats we declared.
- Model behaviour outside the recorded runs has not been measured.
- Withdrawing access does not cancel a request that is already in flight.

## Team responsibilities

| Role | Responsibility |
|---|---|
| Core and integration | Gateway, evidence, verifier, deployment, regression tests |
| Agent and demonstration | Agent workflow and website |
| Evaluation | Test cases, measurements and scoring |
