# Running and troubleshooting

## Scripted lab

Put the project in a short folder path. Double-click `Launch-Hackathon.cmd`. The first run creates a Python environment and installs the hash-pinned dependencies. If setup is interrupted, fix the network or prerequisite error and launch again; missing packages are repaired from the lock file. A broken Python install has to be fixed first. To use a specific interpreter, run `scripts/launch-hackathon.ps1` with its Python parameter.

The app runs on 127.0.0.1 and tries ports 8700 to 8720. Each launch link works once. Press Enter in the launcher window to stop it.

The launcher ignores any EXFILSCOPE settings from your shell and keeps its environments, caches and evidence inside the project. Every run gets its own keys, receivers, proxy state, TLS files and ledgers. Don't share virtual environments, TLS state or evidence folders with other projects.

## Live Qwen3

Install Ollama and pull `qwen3:4b-instruct-2507-q4_K_M`. The accepted manifest SHA-256 is `6214d088d3846e16c9fe00adcbabdbfddc61ce4a70daacc46cb2310c38603054`. Your normal Ollama service and model store are left alone. `Launch-Live-Hackathon.cmd` starts and stops a separate model listener together with the app.

To start that listener by hand, for example to see its errors:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/serve-hackathon-model.ps1
```

It checks the model manifest and layers, copies the pinned files to the project's model store and listens only on 127.0.0.1:11435. `SourceModels` can point to another verified model store. A busy port or a wrong digest stops it.

Then start the web launcher, open Government Trust and choose "Live local Qwen3". This uses only the core environment. The older document-based scenarios also need the agent environment and the embedding cache (see [SETUP.md](SETUP.md)). Stop the app with Enter and the model listener with Ctrl+C. If Qwen3 is unavailable, use the scripted run or the recorded website.

## Recorded website offline

The recorded website is a folder of static files. To view a copy without internet, serve that folder locally, for example:

```powershell
py -3.13 -m http.server 8730 --bind 127.0.0.1
```

Then open http://127.0.0.1:8730. Opening `index.html` directly from disk does not work. The recorded site never starts the model, gateway, proxy or verifier.

## Packaging

`python -B scripts/package_hackathon.py dist/ExfilScope-Hackathon.zip` builds a ZIP from the files committed in Git. It leaves out Git metadata, environments, caches, model files and local evidence. Keep the ZIP and its SHA-256 file together.

Connecting this to a real government system would also need an approved service owner, a network and key custody design, a privacy review and tested failure and rollback steps.

## Checking a fresh copy

After the first setup, run:

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q --basetemp artifacts/product-validation tests/test_policy.py tests/test_verifier.py tests/test_health.py tests/test_privacy_controls.py tests/test_api.py tests/test_monitor.py webapp/tests/test_trust.py webapp/tests/test_platform.py webapp/tests/test_workspaces.py
```

Use a new `--basetemp` folder for each attempt.
