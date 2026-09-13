# BCB 풀 프로브 (Week2-C0-probe): A = haiku-4-5, B = sonnet-4-6, 각 single 1회. 판정은 공식 Docker 이미지.
$env:ANTHROPIC_API_KEY = [Environment]::GetEnvironmentVariable("ANTHROPIC_API_KEY", "User")
$env:HARMONET_LLM_BACKEND="anthropic"
$env:ANTHROPIC_MAX_TOKENS="4096"
$env:ANTHROPIC_TEMPERATURE="0.2"
$env:HARMONET_ALLOW_NO_REDIS="1"
$env:PYTHONIOENCODING="utf-8"
Set-Location "C:\Users\User\Documents\antigravity\harmonet"
$env:HARMONET_MODEL_BUILDER="claude-haiku-4-5"
$env:HARMONET_TRACE_RUN_ID="pool_probe_bcb_A"
python -X utf8 -m benchmark.bcb_g1 --ids evidence/week2/probe_ids_bcb.json --output evidence/week2/pool_probe_bcb_A.json *> evidence/week2/probe_bcb_A_run.txt
"EXIT=$LASTEXITCODE" | Out-File -Append evidence/week2/probe_bcb_A_run.txt
$env:HARMONET_MODEL_BUILDER="claude-sonnet-4-6"
$env:HARMONET_TRACE_RUN_ID="pool_probe_bcb_B"
python -X utf8 -m benchmark.bcb_g1 --ids evidence/week2/probe_ids_bcb.json --output evidence/week2/pool_probe_bcb_B.json *> evidence/week2/probe_bcb_B_run.txt
"EXIT=$LASTEXITCODE" | Out-File -Append evidence/week2/probe_bcb_B_run.txt
