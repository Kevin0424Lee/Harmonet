$env:ANTHROPIC_API_KEY = [Environment]::GetEnvironmentVariable("ANTHROPIC_API_KEY", "User")
$env:HARMONET_LLM_BACKEND="anthropic"
$env:HARMONET_MODEL_BUILDER="claude-haiku-4-5"
$env:ANTHROPIC_MAX_TOKENS="4096"
$env:ANTHROPIC_TEMPERATURE="0.2"
$env:HARMONET_ALLOW_NO_REDIS="1"
$env:HARMONET_TRACE_RUN_ID="pool_probe_humaneval164"
$env:PYTHONIOENCODING="utf-8"
Set-Location "C:\Users\User\Documents\antigravity\harmonet"
python -X utf8 -m benchmark.external_g1 --benchmarks humaneval --limit-per-benchmark 164 --repeats 1 --adapters single --output evidence/week2/pool_probe_humaneval164.json *> evidence/week2/probe_run.log
"EXIT=$LASTEXITCODE" | Out-File -Append evidence/week2/probe_run.log
New-Item -ItemType File -Force evidence/week2/probe.done | Out-Null
