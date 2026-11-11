# Setup

You need Windows and Python 3.13 (64-bit) with the `py` launcher. Ollama and the model are installed separately.

## Scripted checks (no model)

Double-click `Launch-Hackathon.cmd`. The first launch creates `.venv` and installs `requirements.lock`, so it needs internet.

## Live government example with Ollama

1. Install Ollama and pull `qwen3:4b-instruct-2507-q4_K_M`.
2. Double-click `Launch-Live-Hackathon.cmd`.
3. Open the government example and choose "Live local Qwen3".

The launcher checks the model and starts a separate listener on `127.0.0.1:11435`. The accepted model manifest is `6214d088d3846e16c9fe00adcbabdbfddc61ce4a70daacc46cb2310c38603054`. If the model is different or the port is already in use, the launch stops. See [DEPLOYMENT.md](DEPLOYMENT.md) for fixes.

## Document-based agent scenarios (optional)

These scenarios use a second Python environment and a local embedding cache:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1 -Agent -EmbeddingCache
```

This creates `.venv-agent`, installs `requirements-phase2.lock` and prepares the embedding cache. The government example does not need it.

## Environments

| Environment | Dependency file | Used for |
| --- | --- | --- |
| `.venv` | `requirements.lock` | Web app, security checks, monitor, verifier, government Ollama adapter, core tests |
| `.venv-agent` | `requirements-phase2.lock` | Document-based agent and retrieval |

## Tests

Run the tests with the matching environment and a new `--basetemp` folder each time. Some tests need local evidence, the embedding cache or a running model. They are skipped when those are missing, and a skip does not mean the live model was tested.

To rebuild the recorded website, run `python -m webapp.public_site <empty-folder>`.

Press Enter in the launcher window to stop the app. Keep files from `artifacts/` out of any shared copy, because they can contain test keys.
