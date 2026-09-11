# 재측정 본 실행 (Task 5 + Task 6) — 툴 타임아웃과 무관하게 분리 실행하기 위한 스크립트
$env:HARMONET_LLM_BACKEND="openai_compatible"
$env:OPENAI_COMPAT_BASE_URL="http://localhost:11434/v1"
$env:OPENAI_COMPAT_MODEL="qwen2.5-coder:7b"
$env:OPENAI_COMPAT_API_KEY="ollama"
$env:OPENAI_COMPAT_TIMEOUT_SECONDS="600"
$env:CREWAI_DISABLE_TELEMETRY="true"
$env:OTEL_SDK_DISABLED="true"
$env:CREWAI_TRACING_ENABLED="false"
Set-Location "C:\Users\User\Documents\antigravity\harmonet"

# Task 5: 수리 경로 포함
python -X utf8 -m benchmark.external_g1 --benchmarks humaneval,mbpp --limit-per-benchmark 20 --repeats 3 `
  --adapters harmonet_v2,harmonet,langraph,autogen,crewai --output g1_fair_20x3.json *> g1_fair_20x3.log
"EXIT=$LASTEXITCODE" | Out-File -Append g1_fair_20x3.log

# Task 6: 수리 경로 제외 (대칭 조건)
$env:G1_DISABLE_EVAL_REPAIR="1"
python -X utf8 -m benchmark.external_g1 --benchmarks humaneval,mbpp --limit-per-benchmark 20 --repeats 3 `
  --adapters harmonet_v2,langraph,autogen,crewai --output g1_fair_norepair_20x3.json *> g1_fair_norepair_20x3.log
"EXIT=$LASTEXITCODE" | Out-File -Append g1_fair_norepair_20x3.log
Remove-Item Env:\G1_DISABLE_EVAL_REPAIR
"ALL_DONE" | Out-File run_fair.done
