# SWE-bench Lite 예측 생성. 조건·범위·백엔드를 인자로 받는다.
#   run_swe_gen.ps1 -Cond single_novalidate|single_validate|harmonet_validate -Offset 0 -Limit 30 -Backend anthropic|ollama
# anthropic 백엔드는 기존 43/50 실행과 같은 조건(claude-haiku-4-5, temp 0.2, max_tokens 1024)으로 맞춘다.
param([string]$Cond, [int]$Offset = 0, [int]$Limit = 10, [string]$Backend = "ollama", [string]$Tag = "")
if ($Backend -eq "anthropic") {
  $env:ANTHROPIC_API_KEY = [Environment]::GetEnvironmentVariable("ANTHROPIC_API_KEY", "User")
  $env:HARMONET_LLM_BACKEND = "anthropic"
  $env:ANTHROPIC_MODEL = "claude-haiku-4-5"
  $env:ANTHROPIC_MAX_TOKENS = "1024"
  $env:ANTHROPIC_TEMPERATURE = "0.2"
} else {
  $env:HARMONET_LLM_BACKEND = "openai_compatible"
  $env:OPENAI_COMPAT_BASE_URL = "http://localhost:11434/v1"
  $env:OPENAI_COMPAT_MODEL = "qwen2.5-coder:7b-32k"
  $env:OPENAI_COMPAT_API_KEY = "ollama"
  $env:OPENAI_COMPAT_TIMEOUT_SECONDS = "900"
}
$env:PYTHONIOENCODING = "utf-8"
Set-Location "C:\Users\User\Documents\antigravity\harmonet"
if ($Tag -eq "") { $Tag = "${Backend}_${Offset}_${Limit}" }
$out = "swe_fair/swe_${Cond}_$Tag.jsonl"
$log = "swe_fair/gen_${Cond}_$Tag.log"
switch ($Cond) {
  "single_novalidate" { $extra = @("--adapter", "single", "--no-validate-patches") }
  "single_validate"   { $extra = @("--adapter", "single", "--drop-invalid") }
  "harmonet_validate" { $extra = @("--adapter", "harmonet", "--drop-invalid") }
}
python -X utf8 -m benchmark.swebench_g1 --name $Cond --offset $Offset --limit $Limit --output $out --repo-cache swebench_repo_cache @extra *> $log
"EXIT=$LASTEXITCODE" | Out-File -Append $log
New-Item -ItemType File -Force "swe_fair/gen_${Cond}_$Tag.done" | Out-Null
