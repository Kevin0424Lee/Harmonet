# HarmoNet

HarmoNet is a resonance-gated sparse multi-agent runtime: tasks are embedded
into a shared field, relevant agents claim work by semantic/domain resonance,
and only the necessary agents call an LLM.

This repository is a public research package. It includes the runtime, benchmark
harness, tests, deployment scaffolding, curated reports, and summarized evidence
from G1-G3 validation. Raw logs, secrets, local caches, and private provider
responses are intentionally excluded.

## Core idea

Traditional multi-agent frameworks often execute a fixed or explicitly defined
agent graph. HarmoNet instead treats each task as a signal in a shared field.
Agents subscribe to semantic regions and compete for work only when a resonance
score crosses a threshold.

At a high level:

```text
task -> embedding -> DataUniverse -> resonance scoring -> sparse agent claims -> LLM calls -> validation/report
```

This makes the system useful for experiments where the question is not only
"can multiple agents solve the task?", but also "how many agents and LLM calls
were actually necessary?"

## Repository layout

```text
harmonet/      Runtime components: field, agents, storage, LLM clients, health, observability
benchmark/    G1/G2 benchmark harness and report generation
tests/        Unit tests
deploy/       Deployment and runtime support files
docs/         Curated architecture and report documents
evidence/     Publishable benchmark evidence summaries
```

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest tests/ -x -q
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest tests/ -x -q
```

## Mock benchmark

The mock LLM is never selected automatically: set `HARMONET_LLM_BACKEND=mock` explicitly (or configure a real backend), and `HARMONET_ALLOW_NO_REDIS=1` to run without Redis — otherwise the process stops with a `RuntimeError` that names these options.

Week-1 smoke (mock, no cost — checks traces, mechanical verification, per-role models, fail-closed backend): `python -X utf8 scripts/week1_smoke.py`

The default safe mode uses a mock LLM and does not require an API key:

```bash
HARMONET_LLM_BACKEND=mock python -X utf8 -m benchmark.runner \
  --limit 3 \
  --skip-langraph \
  --harmonet-ticks 2 \
  --output smoke.json

python -X utf8 -m benchmark.report --file smoke.json
```

## Ollama benchmark

```bash
export HARMONET_LLM_BACKEND=ollama
export OLLAMA_HOST=http://localhost:11434
export OLLAMA_MODEL=qwen2.5:7b

python -X utf8 -m benchmark.runner \
  --limit 3 \
  --repeats 1 \
  --harmonet-ticks 2 \
  --output compare_3.json
```

## Configuration

Copy `.env.example` to a local `.env` file and fill in provider keys locally.
Never commit real keys or raw provider logs.

Supported backend names depend on the installed runtime code, but the public
configuration template includes:

- `mock`
- `ollama`
- `runyourai`
- `openai`
- `anthropic`

## Docker

```bash
docker build --target runtime -t harmonet:local .
docker run --rm harmonet:local python -m pytest tests/ -x -q
```

## Evidence and reports

Curated reports are in `docs/reports/`. Reproducibility artifacts that are safe
to publish are in `evidence/`.

The public package intentionally excludes:

- API keys and `.env` files
- raw provider response dumps
- local model caches
- PID files and long-running process logs
- full experimental output directories

## Status

HarmoNet is a research prototype. The included validation material supports
further review, replication, and development, but it should not be treated as a
production SaaS platform without additional security, reliability, and product
hardening.
