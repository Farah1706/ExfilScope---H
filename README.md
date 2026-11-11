# ExfilScope

UAE Hackathon 2026, Challenge 27.

**Website: https://farah1706.github.io/ExfilScope---H/**

The website works in any browser on a phone, tablet or computer, with nothing to install. It replays tests we recorded on our own machine. It does not run the AI model or the security services, so every number on it comes from a recorded run. Start with "See the government example".

## What it does

ExfilScope sits between an AI agent and the network. Before the agent sends anything, a security gateway checks who the agent is, what task it was given and whether the data is allowed. The gateway writes its decision to Ledger A. A separate proxy watches what actually leaves and writes that to Ledger B. A verifier then compares the two ledgers and marks each request MATCH, MISMATCH or UNVERIFIED.

In the government example, a local Qwen3 model prepares a short brief from GDRFA Dubai's published residency statistics (2018 to 2025). The brief can only contain approved figures from that table. If a figure is changed or the destination is wrong, ExfilScope stops the brief before it is sent.

## Running it locally (Windows)

1. Install Python 3.13 (64-bit).
2. Double-click `Launch-Hackathon.cmd`. The first run downloads the pinned dependencies, so it needs internet. The app opens in your browser.
3. Go to Scenario Lab, then Government Trust. Choose "Scripted security checks" and HTTPS, and start the run. You should see one accepted request and six requests rejected before the gateway.

To use the real model instead, install Ollama with `qwen3:4b-instruct-2507-q4_K_M`, double-click `Launch-Live-Hackathon.cmd` and choose "Live local Qwen3".

More detail: [setup](docs/SETUP.md), [running and troubleshooting](docs/DEPLOYMENT.md), [how it works](docs/TECHNICAL.md), [test results and limits](docs/STATUS.md).

## Earlier capstone results

The capstone run e1-c2292f76f71a had 42 primary cases (18 MATCH, 18 MISMATCH, 6 UNVERIFIED) and 6 supplementary cases (all MISMATCH). Diagnostic run e1-6e021d09d252 passed 24 of 24 checks. In the timing study, all 180 measured pairs were valid, and the median added delay was 22.1 to 25.6 ms across the six groups (360 measured requests plus 120 warm-ups). These results come from before the hackathon version. The human review study has not been done yet.

## Repository layout

| Folder | Contents |
|---|---|
| `src/exfilscope` | Gateway, proxy monitor, ledgers and verifier |
| `webapp` | The web app, the Government Trust checks and the recorded samples |
| `phase2` | The Qwen3 agent and its Ollama connection |
| `dashboard` | Helpers that read and export evidence |
| `scripts` | Launchers, setup, data refresh and benchmark |
| `examples` | Fictional test data, policy and registry |
| `tests` | Core tests |
