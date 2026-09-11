# single 어댑터만 Task 6 조건으로 실행
$env:HARMONET_LLM_BACKEND="openai_compatible"
$env:OPENAI_COMPAT_BASE_URL="http://localhost:11434/v1"
$env:OPENAI_COMPAT_MODEL="qwen2.5-coder:7b"
$env:OPENAI_COMPAT_API_KEY="ollama"
$env:OPENAI_COMPAT_TIMEOUT_SECONDS="600"
$env:G1_DISABLE_EVAL_REPAIR="1"
Set-Location "C:\Users\User\Documents\antigravity\harmonet"
python -X utf8 -m benchmark.external_g1 --benchmarks humaneval,mbpp --limit-per-benchmark 20 --repeats 3 `
  --adapters single --output g1_fair_single_norepair_20x3.json *> g1_fair_single_norepair_20x3.log
"EXIT=$LASTEXITCODE" | Out-File -Append g1_fair_single_norepair_20x3.log
"ALL_DONE" | Out-File run_single.done
