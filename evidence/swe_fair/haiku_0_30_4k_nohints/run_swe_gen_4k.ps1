# SWE-bench Lite 예측 생성 — AUDIT.md N5/N6 반영판 (2026-09-12)
#   변경: ANTHROPIC_MAX_TOKENS 1024 → 4096 (출력 절단 제거), hints_text 미포함 (swebench_g1.py에서 제거)
#   run_swe_gen_4k.ps1 -Cond single_novalidate|single_validate|harmonet_validate -Offset 0 -Limit 30 -Tag <실행 식별자>
#   Anthropic API에는 seed 파라미터가 없으므로 "반복"은 동일 설정 재실행이다 (temp 0.2).
param([string]$Cond, [int]$Offset = 0, [int]$Limit = 3, [string]$Tag = "")
$env:ANTHROPIC_API_KEY = [Environment]::GetEnvironmentVariable("ANTHROPIC_API_KEY", "User")
$env:HARMONET_LLM_BACKEND = "anthropic"
$env:ANTHROPIC_MODEL = "claude-haiku-4-5"
$env:ANTHROPIC_MAX_TOKENS = "4096"
$env:ANTHROPIC_TEMPERATURE = "0.2"
$env:PYTHONIOENCODING = "utf-8"
Set-Location "C:\Users\User\Documents\antigravity\harmonet"
if ($Tag -eq "") { $Tag = "4k_nohints_${Offset}_${Limit}" }
$out = "swe_fair/swe_${Cond}_$Tag.jsonl"
$log = "swe_fair/gen_${Cond}_$Tag.log"
switch ($Cond) {
  "single_novalidate" { $extra = @("--adapter", "single", "--no-validate-patches") }
  "single_validate"   { $extra = @("--adapter", "single", "--drop-invalid") }
  "harmonet_validate" { $extra = @("--adapter", "harmonet", "--drop-invalid") }
}
python -X utf8 -m benchmark.swebench_g1 --name $Cond --offset $Offset --limit $Limit --output $out --repo-cache swebench_repo_cache --overwrite @extra *> $log
"EXIT=$LASTEXITCODE" | Out-File -Append $log
New-Item -ItemType File -Force "swe_fair/gen_${Cond}_$Tag.done" | Out-Null
