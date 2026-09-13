# A7c 로컬 재실행: 7B norepair 20x3, 새 채점기(score_hidden). single / harmonet_v2 / harmonet
$env:HARMONET_LLM_BACKEND="openai_compatible"
$env:OPENAI_COMPAT_BASE_URL="http://localhost:11434/v1"
$env:OPENAI_COMPAT_MODEL="qwen2.5-coder:7b"
$env:OPENAI_COMPAT_API_KEY="ollama"
$env:OPENAI_COMPAT_TIMEOUT_SECONDS="600"
$env:HARMONET_ALLOW_NO_REDIS="1"
$env:HARMONET_TRACE_RUN_ID="g1_rescore_7b_norepair_20x3"
$env:PYTHONIOENCODING="utf-8"
Set-Location "C:\Users\User\Documents\antigravity\harmonet"
python -X utf8 -m benchmark.external_g1 --benchmarks humaneval,mbpp --limit-per-benchmark 20 --repeats 3 `
  --adapters single,harmonet_v2,harmonet --output evidence/g1_fair/rescore/g1_rescore_7b_norepair_20x3.json *> evidence/g1_fair/rescore/run.log
"EXIT=$LASTEXITCODE" | Out-File -Append evidence/g1_fair/rescore/run.log
New-Item -ItemType File -Force evidence/g1_fair/rescore/run.done | Out-Null
