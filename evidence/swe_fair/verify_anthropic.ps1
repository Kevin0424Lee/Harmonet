# 새 프로세스에서 사용자 환경변수(ANTHROPIC_API_KEY)를 읽어 1회 호출로 usage 실측 확인
$env:ANTHROPIC_API_KEY = [Environment]::GetEnvironmentVariable("ANTHROPIC_API_KEY","User")
$env:HARMONET_LLM_BACKEND="anthropic"
$env:ANTHROPIC_MODEL="claude-haiku-4-5"
$env:ANTHROPIC_MAX_TOKENS="1024"
$env:ANTHROPIC_TEMPERATURE="0.2"
$env:PYTHONIOENCODING="utf-8"
Set-Location "C:\Users\User\Documents\antigravity\harmonet"
python -X utf8 verify_usage.py *> swe_fair\verify_anthropic_output.txt
"EXIT=$LASTEXITCODE" | Out-File -Append swe_fair\verify_anthropic_output.txt
