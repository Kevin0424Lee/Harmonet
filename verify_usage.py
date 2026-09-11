"""
verify_usage.py — 재측정 전 필수 확인

프로바이더가 실제 usage를 반환하는지 LLM 호출 1회로 검증한다.
이것이 실패하면 비싼 본 실험을 돌려도 전부 추정치가 되므로,
반드시 본 실험 전에 실행할 것.

사용법:
    python verify_usage.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harmonet.usage import METER
from harmonet.llm import get_llm_client

backend = os.getenv("HARMONET_LLM_BACKEND", "(미설정)")
print(f"백엔드: {backend}")
print("-" * 60)

METER.reset()
client = get_llm_client()
out = client.generate(
    "Reply with exactly the word: ok",
    system_prompt="You are a terse assistant. Reply with one word only.",
)
snap = METER.snapshot()

print(f"응답: {out[:60]!r}")
print(f"계측: {snap}")
print("-" * 60)

if snap["calls"] == 0:
    print("❌ 실패 — LLM 호출이 계측되지 않았습니다.")
    print("   원인: 해당 클라이언트에 METER 계측이 삽입되지 않음.")
    print("   확인: harmonet/llm.py 에서 METER.record_from_response 위치")
    sys.exit(1)

if not snap["measured"]:
    print("⚠️  경고 — 추정치로 기록되었습니다 (measured=False).")
    print("   프로바이더가 response.usage 를 반환하지 않습니다.")
    print()
    print("   mock/ollama 백엔드라면 정상입니다.")
    print("   실제 API 백엔드인데 이 메시지가 나오면 본 실험을 중단하고")
    print("   프로바이더 응답에 usage 필드가 있는지 먼저 확인하세요:")
    print("     - RunYourAI 등 라우터는 usage 를 생략하는 경우가 있습니다")
    print("     - 생략된다면 Anthropic/OpenAI 직접 호출로 전환하는 것이 안전합니다")
    sys.exit(2)

if snap["prompt_tokens"] == 0:
    print("❌ 실패 — usage 는 왔으나 prompt_tokens 가 0입니다. 필드명을 확인하세요.")
    sys.exit(3)

print("✅ 통과 — 실측 usage 가 정상 기록됩니다.")
print(f"   prompt {snap['prompt_tokens']} / completion {snap['completion_tokens']}")
print()
print("   참고: 시스템 프롬프트가 포함되었는지 확인하려면 위 prompt_tokens 가")
print("   사용자 프롬프트('Reply with exactly the word: ok', 약 8토큰)보다")
print("   충분히 큰지 보세요. 크다면 시스템 프롬프트가 집계된 것입니다.")
