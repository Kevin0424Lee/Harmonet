$env:ANTHROPIC_API_KEY = [Environment]::GetEnvironmentVariable("ANTHROPIC_API_KEY", "User")
$env:HARMONET_LLM_BACKEND="anthropic"
$env:HARMONET_MODEL_BUILDER="claude-haiku-4-5"
$env:ANTHROPIC_MAX_TOKENS="4096"
$env:ANTHROPIC_TEMPERATURE="0.2"
$env:HARMONET_ALLOW_NO_REDIS="1"
$env:HARMONET_TRACE_RUN_ID="pool_probe_mbppplus"
$env:PYTHONIOENCODING="utf-8"
Set-Location "C:\Users\User\Documents\antigravity\harmonet"
python -X utf8 -m benchmark.mbppplus_g1 --ids evidence/week2/probe_ids_mbppplus.json --output evidence/week2/pool_probe_mbppplus.json *> evidence/week2/probe_mbppplus_run.log
"EXIT=$LASTEXITCODE" | Out-File -Append evidence/week2/probe_mbppplus_run.log
