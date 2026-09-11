#!/bin/bash
E=/mnt/c/Users/User/Documents/antigravity/harmonet/swe_fair
for c in single_novalidate single_validate harmonet_validate; do
  "$E/eval.sh" "$E/swe_${c}_anthropic_0_30.jsonl" "swe_fair_${c}_anthropic_0_30" 4
done
touch "$E/eval30.done"
