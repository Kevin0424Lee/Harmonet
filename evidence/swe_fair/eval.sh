#!/bin/bash
# SWE-bench 공식 하네스 평가 (WSL Ubuntu에서 실행). 인자: 예측 jsonl 경로(윈도우 경로 X, /mnt/c 경로), run_id
PRED="$1"; RUN="$2"; WORKERS="${3:-4}"
mkdir -p ~/swe_eval && cd ~/swe_eval
~/swe/bin/python -m swebench.harness.run_evaluation \
  --dataset_name SWE-bench/SWE-bench_Lite --split test \
  --predictions_path "$PRED" --max_workers "$WORKERS" --run_id "$RUN" \
  --timeout 1800 > "eval_$RUN.log" 2>&1
echo "EXIT=$?" >> "eval_$RUN.log"
# 리포트 json을 결과 폴더로 복사
cp -f *."$RUN".json /mnt/c/Users/User/Documents/antigravity/harmonet/swe_fair/ 2>/dev/null
cp -f "eval_$RUN.log" /mnt/c/Users/User/Documents/antigravity/harmonet/swe_fair/
touch "/mnt/c/Users/User/Documents/antigravity/harmonet/swe_fair/eval_$RUN.done"
