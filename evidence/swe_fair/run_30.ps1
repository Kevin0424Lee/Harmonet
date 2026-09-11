$S = "C:\Users\User\Documents\antigravity\harmonet\swe_fair\run_swe_gen.ps1"
& $S -Cond single_novalidate -Offset 0 -Limit 30 -Backend anthropic
& $S -Cond single_validate   -Offset 0 -Limit 30 -Backend anthropic
& $S -Cond harmonet_validate -Offset 0 -Limit 30 -Backend anthropic
New-Item -ItemType File -Force "C:\Users\User\Documents\antigravity\harmonet\swe_fair\run30.done" | Out-Null
