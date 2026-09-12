"""테스트는 Redis 없이 돈다. 폴백은 명시 허용일 때만 가능하므로(WEEK1 A2) 여기서 명시한다."""
import os

os.environ.setdefault("HARMONET_ALLOW_NO_REDIS", "1")
os.environ.setdefault("HARMONET_LLM_BACKEND", "mock")
