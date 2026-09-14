"""
harmonet/verify.py — 기계적 검증 (LLM 호출 0회)  [WEEK1 A1 → A7 재작성]

두 검증기:
    verify_visible(artifact, spec)  루프 안. 행동 결정(자기수정/전문가 추가/종료)에 쓰는 공개 신호.
    score_hidden(artifact, spec)    에피소드 종료 후 채점. 결과는 TaskState.score 에 trigger="post_hoc" 로만 기록.
둘은 같은 하네스를 쓰되 spec["tests"](공개) 와 spec["hidden_tests"](채점용) 를 각각 읽는다.

판정 형식 (두 검증기 동일):
    {"passed": bool,                 # True 는 level=="functional" 이고 outcome=="pass" 일 때만
     "level": "static"|"apply"|"functional",
     "outcome": "pass"|"fail"|"error"|"timeout"|"no_tests"|"aborted",
     "applied": bool,                # patch 전용 (git apply --check)
     "n_run": int, "n_passed": int, "n_failed": int,
     "flags": [..],                  # AST 사전검사 경고 (차단 아님)
     "method": [..],                 # "ast" / "apply_check" / "test_exec"
     "evidence": str, "cost_tokens": 0,
     "wall_ms": int, "exec_count": int, "sandbox": "subprocess"|"docker"}

task_spec["kind"] = "code" | "patch" | "stdio" | "mbppplus" | "bcb".
     # bcb (Week2-C0, BigCodeBench): tests / hidden_tests = [unittest 모듈 소스, ...] (가시 = doctest 를 TestCases 로 감싼 것, 히든 = 공식 test).
     #   **공식 Docker 이미지 안에서만** 판정한다 (HARMONET_BCB_IMAGE, digest 고정; --network none --memory --cpus). Windows 전사 금지 —
     #   docker 가 없으면 RuntimeError. 판정 함수는 공식 bigcodebench.eval.untrusted_check 그대로 (harmonet/bcb_harness.py).
     # mbppplus (Week2-B0): tests / hidden_tests = [{"input": repr, "expected": repr, "atol": float, "time_limit": s}, ...]
     #   함수형(code) 하네스를 그대로 쓰되 프렐류드(harmonet/mbppplus_compare.py 소스)를 후보 exec **뒤에** 네임스페이스에 넣고,
     #   케이스마다 entry_point(*input) 을 호출해 공식 evalplus 비교(집합 비교·특수 판정·float atol·np.allclose)로 판정한다.
     #   시간제한: 공식과 같은 케이스별 max(1s, 4×정답 시간)을 호출 후 경과시간으로 판정(초과 = 그 케이스 실패), 프로세스 전체는
     #   공식 식 min(60, Σ제한)+2 초로 타임아웃. 공식은 SIGALRM 으로 케이스 도중 끊지만 Windows 엔 SIGALRM 이 없다 — 사후 측정이
     #   통과/실패 게이트에서는 동치(초과 케이스는 어느 쪽이든 비통과)이고, 폭주 케이스는 전체 타임아웃으로 잡힌다.
     # stdio (Week2-A0, LiveCodeBench): tests / hidden_tests = [{"input": stdin, "output": expected_stdout}, ...]
     #   하네스가 테스트마다 후보를 **별도 subprocess** 로 실행하고 그 테스트의 stdin 만 넘긴다. 기대 출력·nonce·결과 파일 경로는
     #   후보 프로세스에 노출되지 않는다(argv·env·후보 cwd 어디에도 없음: 하네스가 stdin 으로 받아 메모리에만 둔다).
     #   테스트당 타임아웃(기본 10s) 시 자식 프로세스 트리 전체 종료(Windows taskkill /T, POSIX 프로세스 그룹). stdout 상한 1MB(초과 = fail).
     #   메모리 상한: POSIX 는 RLIMIT_AS, Windows 는 미적용 — 결과의 mem_limit 에 "not_applied" 로 기록한다(조용히 생략하지 않음).
     #   판정(A0c, 사전 등록): 테스트마다 정상 종료(rc==0) ∧ 시간·출력 제한 준수 ∧ 기대 출력 일치 → pass. 하나라도 아니면
     #   timeout / error(rc!=0) / fail. 정답을 출력하고도 남는 스레드·무한루프로 종료하지 않으면 timeout 이다.
     #   함수형(code) 하네스의 "os._exit → aborted" 규칙은 여기 적용하지 않는다: 그쪽은 후보가 하네스와 같은 프로세스라 종료 코드를
     #   판정 신호로 쓸 수 없고(후보가 죽으면 기록기도 죽음) 결과 파일 유무로만 판정하지만, stdio 는 후보가 별도 프로세스라
     #   종료 코드가 판정의 일부다.
     #   비교 규칙은 LCB 공식 testing_util.grade_stdio 와 동일 (harmonet/stdio_compare.py).
     #   **별도 subprocess 는 보안 격리가 아니다** (같은 사용자 권한·파일 접근·자원 고갈 가능).

거짓 통과 방지 (A7): 종료 코드는 통과 신호가 아니다. 하네스가 후보를 import 하고 테스트를 하나씩 실행한 뒤
result.json {n_run, n_passed, n_failed, errors, duration_ms, nonce} 를 쓴다. 검증기는
  파일 존재 ∧ nonce 일치 ∧ n_run == 기대 테스트 수 ∧ n_passed == n_run  일 때만 pass.
후보 import 와 각 테스트는 try/except BaseException 으로 감싸 SystemExit 도 error 로 기록한다.
os._exit 처럼 하네스를 통째로 죽이면 result.json 이 없다 → outcome="aborted".

격리: 새 임시 디렉터리, cwd 고정, 최소 환경변수(PATH·SYSTEMROOT·TEMP 계열)만 전달 — API 키는 절대 넘기지 않는다,
python -I, 타임아웃. HARMONET_SANDBOX=docker 면 python:3.11-slim 컨테이너(--network none)에서 실행하고 Docker 가
없으면 RuntimeError (조용한 폴백 금지). 기본은 subprocess.

A7b: nonce 와 결과 경로는 argv 가 아니라 stdin 으로 넘기고 후보 exec 전에 소비한다; 기록기(json.dump/open/os._exit)는
후보 exec 전에 바인딩한다; 하네스는 끝에서 os._exit 로 종료해 후보의 잔여 스레드가 timeout 을 만들지 못하게 한다.

알려진 한계 (subprocess 모드):
  - `sys._getframe` 등으로 하네스 프레임의 지역변수(nonce, out_path)를 읽는 후보는 막지 못한다.
  - `builtins` / `os` 모듈 수준을 통째로 패치하는 후보(사전 바인딩된 함수 객체 자체를 바꾸는 수준)는 막지 못한다.
  - 같은 OS 사용자 권한으로 돈다. 파일시스템·네트워크 격리 없음, CPU/메모리 제한 없음 (타임아웃만).
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional

_CODE_BLOCK_RE = re.compile(r"```(?:python|py)?\s*(.*?)```", re.I | re.S)
OUTCOMES = ("pass", "fail", "error", "timeout", "no_tests", "aborted")
LEVELS = ("static", "apply", "functional")

# 하네스: 후보 import → 테스트 하나씩 실행 → result.json. 종료 코드는 보지 않는다.
_HARNESS = r'''
import json, os, sys, time, traceback
_dump, _open, _exit = json.dump, open, os._exit            # 후보 exec 전에 바인딩: 후보가 json/open 을 패치해도 영향 없음
nonce, expected, out_path = json.loads(sys.stdin.readline())  # stdin 으로 받고 즉시 소비: 후보는 argv 에서 nonce 를 볼 수 없다
t0 = time.time()
res = {"n_run": 0, "n_passed": 0, "n_failed": 0, "errors": [], "duration_ms": 0, "nonce": nonce}
def _write():
    res["duration_ms"] = int((time.time() - t0) * 1000)
    with _open(out_path, "w", encoding="utf-8") as f:
        _dump(res, f)
ns = {"__name__": "candidate"}
try:
    with open("candidate.py", encoding="utf-8") as f:
        src = f.read()
    exec(compile(src, "candidate.py", "exec"), ns)          # 후보 import (SystemExit 포함 전부 error 로)
except BaseException as e:                                    # noqa: BLE001
    res["errors"].append("import: " + type(e).__name__ + ": " + str(e)[:300])
    _write(); _exit(0)
if os.path.exists("prelude.py"):                              # mbppplus: 공식 비교 함수. 후보 뒤에 넣어 후보가 덮지 못하게
    try:
        with open("prelude.py", encoding="utf-8") as f:
            exec(compile(f.read(), "prelude.py", "exec"), ns)
    except BaseException as e:                                # noqa: BLE001
        res["errors"].append("prelude: " + type(e).__name__ + ": " + str(e)[:300])
        _write(); _exit(0)
with open("tests.json", encoding="utf-8") as f:
    tests = json.load(f)
for i, t in enumerate(tests):
    res["n_run"] += 1
    try:
        exec(compile(t, "test_%d" % i, "exec"), dict(ns))     # 테스트마다 후보 네임스페이스 복사본
        res["n_passed"] += 1
    except BaseException as e:                                # noqa: BLE001
        res["n_failed"] += 1
        res["errors"].append("test_%d: %s: %s" % (i, type(e).__name__, str(e)[:300]))
_write()
_exit(0)                                                      # 후보가 남긴 스레드가 프로세스를 붙잡아 timeout 나는 것 방지
'''


def extract_artifact(output: str, kind: str = "code", report: Optional[Dict[str, str]] = None) -> str:
    """LLM 출력에서 산출물(코드 블록 / unified diff)만 뽑는다. str(output) 전체를 씨앗에 싣지 않기 위함.

    코드 블록이 없을 때는 (1) 첫 import/def/class 부터, (2) 그것도 없으면 출력 전체를 돌려준다.
    이 강등은 report["extraction"] 에 "fenced" / "heuristic" / "raw" 로 남겨 검증 evidence 에 찍힌다 — 조용히 하지 않는다.
    """
    output = output or ""
    if kind == "patch":
        from benchmark.swebench_g1 import _extract_patch  # 패치 추출·정규화 로직은 러너 것을 재사용
        patch = _extract_patch(output)
        if report is not None:
            report["extraction"] = "diff" if patch else "none"
        return patch
    blocks = _CODE_BLOCK_RE.findall(output)
    if blocks:
        if report is not None:
            report["extraction"] = "fenced"
        return max(blocks, key=len).strip()
    m = re.search(r"(^|\n)(from\s+\S+\s+import\s+|import\s+|def\s+|class\s+)", output)
    if report is not None:
        report["extraction"] = "heuristic" if m else "raw"
    return output[m.start():].strip() if m else output.strip()


def _artifact_evidence(artifact: str) -> str:
    """builder 산출물을 실제로 받았다는 증거: 길이 + sha256 앞 12자리 (trace에서 builder 출력과 대조 가능)."""
    return f"artifact_chars={len(artifact)} artifact_sha={hashlib.sha256(artifact.encode('utf-8')).hexdigest()[:12]}"


def _exit_flags(tree: ast.AST) -> List[str]:
    """모듈 레벨(및 if __name__ 블록)의 sys.exit / exit / quit / os._exit / raise SystemExit → 경고 플래그."""
    flags: List[str] = []

    def is_exit_call(node: ast.AST) -> bool:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            f = node.value.func
            name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
            return name in ("exit", "quit", "_exit")
        return isinstance(node, ast.Raise) and isinstance(node.exc, (ast.Call, ast.Name)) and \
            (getattr(node.exc, "id", None) == "SystemExit" or getattr(getattr(node.exc, "func", None), "id", None) == "SystemExit")

    def walk_block(body: List[ast.stmt], where: str) -> None:
        for node in body:
            if is_exit_call(node):
                flags.append(f"exit_call:{where}:line{node.lineno}")
            elif isinstance(node, ast.If):
                walk_block(node.body, "if_main" if "__name__" in ast.dump(node.test) else where)
                walk_block(node.orelse, where)
    walk_block(getattr(tree, "body", []), "module")
    return flags


def _result(level: str, outcome: str, evidence: List[str], method: List[str], **extra: Any) -> Dict[str, Any]:
    r = {"passed": level == "functional" and outcome == "pass", "level": level, "outcome": outcome,
         "applied": False, "n_run": 0, "n_passed": 0, "n_failed": 0, "flags": [], "method": method,
         "evidence": "; ".join(evidence), "cost_tokens": 0, "wall_ms": 0, "exec_count": 0, "sandbox": "none", "infra": False}
    r.update(extra)
    return r


def _sandbox_mode() -> str:
    mode = os.getenv("HARMONET_SANDBOX", "subprocess").lower()
    if mode not in ("subprocess", "docker"):
        raise RuntimeError(f"HARMONET_SANDBOX={mode!r} 는 지원하지 않습니다 (subprocess | docker)")
    if mode == "docker":
        if not shutil.which("docker"):
            raise RuntimeError("HARMONET_SANDBOX=docker 이지만 docker 실행 파일이 없습니다. 조용히 subprocess 로 대체하지 않습니다.")
        probe = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=30)
        if probe.returncode != 0:
            raise RuntimeError("HARMONET_SANDBOX=docker 이지만 Docker 데몬에 연결할 수 없습니다: " + (probe.stderr or probe.stdout)[-200:])
    return mode


def _min_env() -> Dict[str, str]:
    """후보 프로세스에 넘기는 최소 환경. API 키·HARMONET_* 는 절대 넘기지 않는다."""
    keep = ("PATH", "SYSTEMROOT", "SystemRoot", "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "LANG", "LC_ALL", "PATHEXT", "COMSPEC")
    return {k: os.environ[k] for k in keep if k in os.environ}


def _run_harness(artifact: str, tests: List[str], timeout_s: float, prelude: Optional[str] = None) -> Dict[str, Any]:
    """격리된 디렉터리에서 하네스 실행. result.json 을 nonce 로 검증해 outcome 을 정한다."""
    mode = _sandbox_mode()
    nonce = secrets.token_hex(16)
    tmp = tempfile.mkdtemp(prefix="harmonet_verify_")
    try:
        with open(os.path.join(tmp, "candidate.py"), "w", encoding="utf-8") as f:
            f.write(artifact + "\n")
        if prelude:
            with open(os.path.join(tmp, "prelude.py"), "w", encoding="utf-8") as f:
                f.write(prelude)
        with open(os.path.join(tmp, "tests.json"), "w", encoding="utf-8") as f:
            json.dump(tests, f)
        with open(os.path.join(tmp, "harness.py"), "w", encoding="utf-8") as f:
            f.write(_HARNESS)
        out_name = f"result_{nonce[:8]}.json"
        if mode == "docker":
            cmd = ["docker", "run", "-i", "--rm", "--network", "none", "-v", f"{tmp}:/w", "-w", "/w", "python:3.11-slim",
                   "python", "-I", "harness.py"]
        else:
            cmd = [sys.executable, "-I", "harness.py"]
        t0 = time.perf_counter()
        timed_out = False
        try:
            proc = subprocess.run(cmd, cwd=tmp, env=_min_env(), input=json.dumps([nonce, len(tests), out_name]) + "\n",
                                  capture_output=True, text=True, timeout=timeout_s)
            tail = (proc.stderr or proc.stdout)[-300:]
        except subprocess.TimeoutExpired:
            timed_out, tail = True, "timeout"
        wall_ms = int((time.perf_counter() - t0) * 1000)
        out_path = os.path.join(tmp, out_name)
        data: Optional[Dict[str, Any]] = None
        if os.path.exists(out_path):
            try:
                with open(out_path, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as exc:                          # 손상된 result.json 도 aborted 로
                tail = f"result.json unreadable: {exc}"
        if timed_out:
            outcome = "timeout"
        elif data is None or data.get("nonce") != nonce:
            outcome = "aborted"                               # 파일 없음 / nonce 불일치 (후보가 미리 쓴 파일 등)
            if data is not None:
                tail = "nonce mismatch"
        elif data.get("n_run") != len(tests):
            outcome = "error" if data.get("errors") else "aborted"
        elif data.get("n_passed") == data.get("n_run"):
            outcome = "pass"
        else:
            outcome = "error" if any(e.startswith(("import:", "prelude:")) for e in data.get("errors", [])) else "fail"
        d = data or {}
        return {"outcome": outcome, "n_run": int(d.get("n_run", 0)), "n_passed": int(d.get("n_passed", 0)),
                "n_failed": int(d.get("n_failed", 0)), "errors": list(d.get("errors", []))[:5], "tail": tail,
                "wall_ms": wall_ms, "sandbox": mode}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── stdio 하네스 (Week2-A0) ─────────────────────────────────────────────────
# 부모(하네스) 프로세스가 stdin 으로 {nonce, out_path, tests[{input,output}], timeout_s, stdout_cap} 를 받아 메모리에만 두고,
# 테스트마다 `python -I candidate.py` 를 run/ 디렉터리(cwd)에서 띄워 stdin 만 넘긴다. 결과 파일은 부모 cwd(run/ 밖)에 쓴다.
_STDIO_HARNESS_MAIN = r'''
import json, os, subprocess, sys, threading, time
_dump, _open, _exit = json.dump, open, os._exit
cfg = json.loads(sys.stdin.readline())
nonce, out_path, tests, per_test_timeout, cap = cfg["nonce"], cfg["out_path"], cfg["tests"], cfg["timeout_s"], cfg["stdout_cap"]
t0 = time.time()
res = {"n_run": 0, "n_passed": 0, "n_failed": 0, "n_timeout": 0, "n_error": 0, "errors": [], "duration_ms": 0, "nonce": nonce, "mem_limit": "n/a", "notes": []}
IS_WIN = os.name == "nt"
def _write():
    res["duration_ms"] = int((time.time() - t0) * 1000)
    with _open(out_path, "w", encoding="utf-8") as f:
        _dump(res, f)
def _kill_tree(p):
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
        else:
            import signal
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    except Exception:
        pass
def _preexec():
    try:
        import resource
        lim = 2 * 1024 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (lim, lim))
    except Exception:
        pass
def _limit_note():
    if IS_WIN:
        return "not_applied(windows)"
    try:
        import resource  # noqa: F401
        return "RLIMIT_AS=2GiB"
    except Exception:
        return "not_applied(no resource module)"
res["mem_limit"] = _limit_note()
def run_one(inp):
    """(stdout, timed_out, overflow, rc)"""
    kw = dict(stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd="run")
    if IS_WIN:
        kw["creationflags"] = 0x00000200  # CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
        kw["preexec_fn"] = _preexec
    p = subprocess.Popen([sys.executable, "-I", "candidate.py"], **kw)
    buf = bytearray(); overflow = [False]
    def reader():
        while True:
            chunk = p.stdout.read(65536)
            if not chunk:
                break
            if len(buf) + len(chunk) > cap:
                buf.extend(chunk[: max(0, cap - len(buf))]); overflow[0] = True; _kill_tree(p); break
            buf.extend(chunk)
    th = threading.Thread(target=reader, daemon=True); th.start()
    try:
        p.stdin.write(inp.encode("utf-8")); p.stdin.close()
    except Exception:
        pass
    timed_out = False
    try:
        p.wait(timeout=per_test_timeout)
    except subprocess.TimeoutExpired:
        timed_out = True; _kill_tree(p)
    th.join(timeout=2)
    return buf.decode("utf-8", errors="replace"), timed_out, overflow[0], p.returncode
for i, t in enumerate(tests):
    res["n_run"] += 1
    try:
        out, timed_out, overflow, rc = run_one(t["input"])
        ok, why = stdio_match(out, t["output"])
        if overflow:
            res["n_failed"] += 1; res["errors"].append("test_%d: fail: stdout over cap" % i); continue
        if timed_out:                      # 정답을 출력했더라도 종료하지 않으면 timeout (A0c)
            res["n_timeout"] += 1; res["errors"].append("test_%d: timeout%s" % (i, " (output matched)" if ok else "")); continue
        if rc != 0:                        # 정답을 출력했더라도 비정상 종료면 error
            res["n_error"] += 1; res["errors"].append("test_%d: error: rc=%s%s" % (i, rc, " (output matched)" if ok else "")); continue
        if ok:
            res["n_passed"] += 1
        else:
            res["n_failed"] += 1; res["errors"].append("test_%d: fail: %s" % (i, why))
    except BaseException as e:  # noqa: BLE001
        res["n_failed"] += 1; res["errors"].append("test_%d: harness %s: %s" % (i, type(e).__name__, str(e)[:200]))
_write()
_exit(0)
'''


def _stdio_harness_source() -> str:
    """stdio_compare.py 소스 + 하네스 본문 — 하네스가 표준 라이브러리 외 아무것도 import 하지 않게 한다."""
    from pathlib import Path
    cmp_src = (Path(__file__).parent / "stdio_compare.py").read_text(encoding="utf-8")
    return cmp_src + "\n" + _STDIO_HARNESS_MAIN


def _run_stdio_harness(artifact: str, tests: List[Dict[str, str]], per_test_timeout_s: float,
                       stdout_cap: int = 1_000_000) -> Dict[str, Any]:
    mode = _sandbox_mode()
    nonce = secrets.token_hex(16)
    tmp = tempfile.mkdtemp(prefix="harmonet_stdio_")
    try:
        os.makedirs(os.path.join(tmp, "run"))
        with open(os.path.join(tmp, "run", "candidate.py"), "w", encoding="utf-8") as f:
            f.write(artifact + "\n")
        with open(os.path.join(tmp, "harness.py"), "w", encoding="utf-8") as f:
            f.write(_stdio_harness_source())
        out_name = f"result_{nonce[:8]}.json"
        cfg = json.dumps({"nonce": nonce, "out_path": out_name, "tests": tests, "timeout_s": per_test_timeout_s, "stdout_cap": stdout_cap})
        if mode == "docker":
            cmd = ["docker", "run", "-i", "--rm", "--network", "none", "-v", f"{tmp}:/w", "-w", "/w", "python:3.11-slim",
                   "python", "-I", "harness.py"]
        else:
            cmd = [sys.executable, "-I", "harness.py"]
        total_timeout = per_test_timeout_s * (len(tests) + 1) + 30
        t0 = time.perf_counter()
        timed_out = False
        try:
            proc = subprocess.run(cmd, cwd=tmp, env=_min_env(), input=cfg + "\n", capture_output=True, text=True, timeout=total_timeout)
            tail = (proc.stderr or proc.stdout)[-300:]
        except subprocess.TimeoutExpired:
            timed_out, tail = True, "harness timeout"
        wall_ms = int((time.perf_counter() - t0) * 1000)
        out_path = os.path.join(tmp, out_name)
        data = None
        if os.path.exists(out_path):
            try:
                with open(out_path, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as exc:
                tail = f"result.json unreadable: {exc}"
        if timed_out:
            outcome = "timeout"
        elif data is None or data.get("nonce") != nonce:
            outcome = "aborted"
        elif data.get("n_run") != len(tests):
            outcome = "aborted"
        elif data.get("n_passed") == data.get("n_run"):
            outcome = "pass"
        elif data.get("n_timeout", 0) > 0:       # 우선순위: timeout > error > fail
            outcome = "timeout"
        elif data.get("n_error", 0) > 0:
            outcome = "error"
        else:
            outcome = "fail"
        d = data or {}
        return {"outcome": outcome, "n_run": int(d.get("n_run", 0)), "n_passed": int(d.get("n_passed", 0)),
                "n_failed": int(d.get("n_failed", 0)) + int(d.get("n_timeout", 0)) + int(d.get("n_error", 0)),
                "n_timeout": int(d.get("n_timeout", 0)), "n_error": int(d.get("n_error", 0)),
                "errors": list(d.get("errors", []))[:5], "notes": list(d.get("notes", []))[:5],
                "mem_limit": d.get("mem_limit", "n/a"), "tail": tail, "wall_ms": wall_ms, "sandbox": mode}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── BigCodeBench (Week2-C0): 공식 이미지 안에서 공식 untrusted_check 로 판정 ─────────────────────
BCB_IMAGE_DEFAULT = "bigcodebench/bigcodebench-evaluate@sha256:a3cd34ec3840a49d6b7afb240f4bdd47c350bc5991043fd0a91773830f7cd405"  # v0.2.4, 2025-02-23
BCB_LIMITS = {"max_as_limit": 30 * 1024, "max_data_limit": 30 * 1024, "max_stack_limit": 10, "min_time_limit": 1.0, "gt_time_limit": 1.0}
#   ↑ 공식 evaluate 기본값(MB 단위 rlimit, min_time_limit 1s). 과제 타임아웃은 공식 max(240, gt)+1 = 241s.
BCB_TASK_TIMEOUT_S = 241.0


def bcb_docker_cmd(mount_dir: str, script: str) -> List[str]:
    """공식 이미지에서 script 를 python -I 로 실행하는 docker 명령. ENTRYPOINT(bigcodebench.evaluate) 를 덮는다."""
    if not shutil.which("docker"):
        raise RuntimeError("BigCodeBench 판정은 공식 Docker 이미지 안에서만 한다 — docker 실행 파일이 없습니다 (Windows 전사 금지)")
    image = os.getenv("HARMONET_BCB_IMAGE", BCB_IMAGE_DEFAULT)
    return ["docker", "run", "-i", "--rm", "--network", "none", "--memory", os.getenv("HARMONET_BCB_MEMORY", "8g"),
            "--cpus", os.getenv("HARMONET_BCB_CPUS", "2"), "-v", f"{mount_dir}:/w", "-w", "/w", "--entrypoint", "python3", image, "-I", script]


_INFRA_RE = re.compile(r"error during connect|Cannot connect to the Docker daemon|docker daemon|No such image|Unable to find image|"
                       r"pull access denied|manifest unknown|OCI runtime|failed to create|no space left|Error response from daemon", re.I)


def bcb_image() -> str:
    return os.getenv("HARMONET_BCB_IMAGE", BCB_IMAGE_DEFAULT)


def bcb_task_timeout_s() -> float:
    return float(os.getenv("HARMONET_BCB_TIMEOUT_S", BCB_TASK_TIMEOUT_S))   # 테스트에서만 줄인다


def _docker(args: List[str], timeout: float = 60.0, input_text: Optional[str] = None) -> subprocess.CompletedProcess:
    return subprocess.run(["docker"] + args, env=_min_env(), input=input_text, capture_output=True, text=True, timeout=timeout)


def docker_infra_check() -> Dict[str, Any]:
    """인프라 사전 점검 (D1 ②): docker 실행 파일 + 데몬 응답 + 이미지 digest 일치. 실패 항목이 있으면 RuntimeError."""
    if not shutil.which("docker"):
        raise RuntimeError("[bcb-preflight] docker 실행 파일이 없습니다")
    info = _docker(["info", "--format", "{{.ServerVersion}}"])
    if info.returncode != 0:
        raise RuntimeError("[bcb-preflight] docker 데몬 응답 없음: " + (info.stderr or info.stdout)[-200:])
    image = bcb_image()
    ins = _docker(["image", "inspect", image, "--format", "{{json .RepoDigests}}"])
    if ins.returncode != 0:
        raise RuntimeError(f"[bcb-preflight] 이미지 {image} 가 로컬에 없습니다: " + (ins.stderr or ins.stdout)[-200:])
    digests = json.loads(ins.stdout.strip() or "[]")
    want = image.split("@", 1)[1] if "@" in image else None
    if want and not any(d.endswith("@" + want) for d in digests):
        raise RuntimeError(f"[bcb-preflight] 이미지 digest 불일치: 요청 {want}, 로컬 {digests}")
    return {"server_version": info.stdout.strip(), "image": image, "repo_digests": digests}


def _run_bcb_harness(artifact: str, entry: str, tests: List[str]) -> Dict[str, Any]:
    """공식 이미지 컨테이너에서 하네스 실행 (D1 ④): docker create --name → start -a -i(stdin 으로 cfg) → 타임아웃 시 docker kill →
    finally docker rm -f. CLI 타임아웃과 컨테이너 종료를 동일시하지 않는다. 결과의 infra=True 는 데몬·이미지·컨테이너 시작 오류
    (후보 원인 aborted 와 구분)."""
    from pathlib import Path
    nonce = secrets.token_hex(16)
    name = f"harmonet_{nonce[:12]}"
    tmp = tempfile.mkdtemp(prefix="harmonet_bcb_")
    image = bcb_image()
    infra = False
    try:
        with open(os.path.join(tmp, "candidate.py"), "w", encoding="utf-8") as f:
            f.write(artifact + "\n")
        shutil.copy(Path(__file__).parent / "bcb_harness.py", os.path.join(tmp, "harness.py"))
        shutil.copy(Path(__file__).parent / "bcb_check.py", os.path.join(tmp, "bcb_check.py"))
        out_name = f"result_{nonce[:8]}.json"
        cfg = json.dumps({"nonce": nonce, "out_path": out_name, "entry_point": entry, "tests": tests, "limits": BCB_LIMITS})
        total_timeout = (bcb_task_timeout_s() + 60) * len(tests) + float(os.getenv("HARMONET_BCB_MARGIN_S", "90"))   # +60: 기대 수 계산 프로세스
        t0 = time.perf_counter()
        timed_out = False
        tail = ""
        if not shutil.which("docker"):
            raise RuntimeError("BigCodeBench 판정은 공식 Docker 이미지 안에서만 한다 — docker 실행 파일이 없습니다 (Windows 전사 금지)")
        cr = _docker(["create", "-i", "--name", name, "--network", "none", "--memory", os.getenv("HARMONET_BCB_MEMORY", "8g"),
                      "--cpus", os.getenv("HARMONET_BCB_CPUS", "2"), "-v", f"{tmp}:/w", "-w", "/w", "--entrypoint", "python3", image,
                      "-I", "harness.py"])
        if cr.returncode != 0:
            infra, tail = True, "docker create: " + (cr.stderr or cr.stdout)[-300:]
            rc = cr.returncode
        else:
            # 타임아웃 처리는 CLI 를 죽이는 게 아니라 컨테이너를 죽인다(docker kill) — Windows 에서 CLI kill 만으로는 파이프가 닫히지 않아
            # 컨테이너가 끝날 때까지 기다리게 된다(D1 ④ 에서 확인). stdout/stderr 는 파이프 대신 임시 파일(마운트 밖).
            with tempfile.TemporaryFile() as fo, tempfile.TemporaryFile() as fe:
                proc = subprocess.Popen(["docker", "start", "-a", "-i", name], env=_min_env(), stdin=subprocess.PIPE, stdout=fo, stderr=fe)
                try:
                    proc.stdin.write((cfg + "\n").encode("utf-8")); proc.stdin.close()
                except OSError:
                    pass
                try:
                    rc = proc.wait(timeout=total_timeout)
                except subprocess.TimeoutExpired:
                    timed_out, rc = True, None
                    try:
                        _docker(["kill", name], timeout=30)
                    except Exception:
                        pass
                    try:
                        proc.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        proc.kill(); proc.wait()
                fo.seek(0); fe.seek(0)
                out_txt, err_txt = fo.read().decode("utf-8", "replace"), fe.read().decode("utf-8", "replace")
                tail = "docker harness timeout" if timed_out else (err_txt or out_txt)[-300:]
        wall_ms = int((time.perf_counter() - t0) * 1000)
        out_path = os.path.join(tmp, out_name)
        data = None
        if os.path.exists(out_path):
            try:
                with open(out_path, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as exc:
                tail = f"result.json unreadable: {exc}"
        if not infra and data is None and not timed_out and rc != 0 and _INFRA_RE.search(tail or ""):
            infra = True                                  # 결과 없음 + docker 오류 코드 + 인프라 오류 서명 → 후보 탓이 아니다
        if timed_out:
            outcome = "timeout"
        elif data is None or data.get("nonce") != nonce:
            outcome = "aborted"
        elif any(e.startswith("setup:") for e in data.get("errors", [])) or data.get("n_modules", data.get("n_run")) != len(tests):
            outcome = "error"
        elif data.get("n_passed") == data.get("n_modules", data.get("n_run")):
            outcome = "pass"
        elif "timeout" in data.get("stats", []):
            outcome = "timeout"
        else:
            outcome = "fail"
        d = data or {}
        return {"outcome": outcome, "n_run": int(d.get("n_run", 0)), "n_passed": int(d.get("n_passed", 0)), "n_failed": int(d.get("n_failed", 0)),
                "n_modules": int(d.get("n_modules", d.get("n_run", 0))), "errors": list(d.get("errors", []))[:5], "stats": list(d.get("stats", [])),
                "official": d.get("official"), "tail": tail, "wall_ms": wall_ms, "sandbox": "docker:" + image, "infra": infra, "container": name}
    finally:
        try:
            _docker(["rm", "-f", name], timeout=60)
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


# ── MBPP+ (Week2-B0): 케이스 → 테스트 스니펫. 입력은 공식과 같이 복사 없이 그대로 넘긴다(untrusted_check 도 fn(*inp)).
_MBPP_TIMEOUT_PER_TASK = 60.0   # evalplus EVALPLUS_TIMEOUT_PER_TASK 기본값


def _mbpp_prelude() -> str:
    from pathlib import Path
    src = (Path(__file__).parent / "mbppplus_compare.py").read_text(encoding="utf-8")
    return src.replace("from __future__ import annotations", "") + "\nimport time as _time\n"


def _mbpp_tests(entry: str, cases: List[Dict[str, Any]]) -> List[str]:
    out = []
    for c in cases:
        lim = float(c["time_limit"])
        out.append(
            f"_inp = parse_literal({json.dumps(c['input'])})\n"
            f"_exp = parse_literal({json.dumps(c['expected'])})\n"
            f"_t0 = _time.perf_counter()\n"
            f"_out = {entry}(*_inp)\n"
            f"_dt = _time.perf_counter() - _t0\n"
            f"assert _dt <= {lim!r}, 'time limit %.2fs exceeded (%.2fs)' % ({lim!r}, _dt)\n"
            f"assert mbpp_match({entry!r}, _inp, _out, _exp, {float(c['atol'])!r}), 'mismatch'\n")
    return out


def _mbpp_timeout(cases: List[Dict[str, Any]]) -> float:
    # 공식 untrusted_check: timeout = min(60, Σ time_limits) + 1 (+1: fast_check=False)
    return min(_MBPP_TIMEOUT_PER_TASK, sum(float(c["time_limit"]) for c in cases)) + 2.0


def _normalize_tests(tests: Any) -> List[str]:
    if not tests:
        return []
    if isinstance(tests, str):
        return [tests]
    return [str(t) for t in tests if str(t).strip()]


def _verify(artifact: str, spec: Optional[Dict[str, Any]], tests_key: str, timeout_s: float) -> Dict[str, Any]:
    spec = spec or {}
    kind = spec.get("kind", "code")
    evidence = [_artifact_evidence(artifact)]
    if spec.get("extraction"):
        evidence.append(f"extraction={spec['extraction']}")
    method: List[str] = []

    if not artifact.strip():
        return _result("static", "error", ["empty artifact"] + evidence, method)

    if kind == "stdio":
        method.append("ast")
        try:
            tree = ast.parse(artifact)
        except SyntaxError as e:
            evidence.append(f"ast=syntax_error line {e.lineno}: {e.msg}")
            return _result("static", "error", evidence, method)
        flags = _exit_flags(tree)
        tests = spec.get(tests_key) or []
        if not tests:
            return _result("static", "no_tests", evidence, method, flags=flags)
        method.append("stdio_exec")
        h = _run_stdio_harness(artifact, [{"input": t["input"], "output": t["output"]} for t in tests],
                               per_test_timeout_s=float(spec.get("per_test_timeout_s", 10.0)))
        evidence.append(f"harness={h['outcome']} n_run={h['n_run']} n_passed={h['n_passed']} n_failed={h['n_failed']} mem_limit={h['mem_limit']}"
                        + (" errors=" + " | ".join(h["errors"]) if h["errors"] else "")
                        + (" notes=" + " | ".join(h["notes"]) if h["notes"] else "")
                        + (f" tail={h['tail']!r}" if h["outcome"] in ("timeout", "aborted") and h["tail"] else ""))
        return _result("functional", h["outcome"], evidence, method, flags=flags, n_run=h["n_run"], n_passed=h["n_passed"],
                       n_failed=h["n_failed"], wall_ms=h["wall_ms"], exec_count=h["n_run"], sandbox=h["sandbox"], mem_limit=h["mem_limit"])

    if kind == "bcb":
        method.append("ast")
        try:
            tree = ast.parse(artifact)
        except SyntaxError as e:
            evidence.append(f"ast=syntax_error line {e.lineno}: {e.msg}")
            return _result("static", "error", evidence, method)
        flags = _exit_flags(tree)
        defs = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
        entry = spec.get("entry_point")
        if entry and entry not in defs:
            evidence.append(f"entry_point={entry} missing")
            return _result("static", "error", evidence, method, flags=flags)
        tests = [t for t in (spec.get(tests_key) or []) if str(t).strip()]
        if not tests:
            return _result("static", "no_tests", evidence, method, flags=flags)
        method.append("bcb_official_untrusted_check")
        h = _run_bcb_harness(artifact, entry or "task_func", tests)
        evidence.append(f"harness={h['outcome']} n_modules={h['n_modules']} n_run={h['n_run']} n_passed={h['n_passed']} stats={h['stats']} "
                        f"official={h['official']}" + (" infra=True" if h["infra"] else "")
                        + (" errors=" + " | ".join(h["errors"]) if h["errors"] else "")
                        + (f" tail={h['tail']!r}" if h["outcome"] in ("timeout", "aborted", "error") and h["tail"] else ""))
        return _result("functional", h["outcome"], evidence, method, flags=flags, n_run=h["n_run"], n_passed=h["n_passed"],
                       n_failed=h["n_failed"], wall_ms=h["wall_ms"], exec_count=h["n_modules"], sandbox=h["sandbox"], infra=h["infra"],
                       container=h["container"], n_modules=h["n_modules"])

    if kind == "patch":
        from benchmark.swebench_g1 import _check_patch_applies  # git worktree + apply --check (러너와 동일 판정)
        from pathlib import Path
        method.append("apply_check")
        t0 = time.perf_counter()
        ok, out = _check_patch_applies(Path(spec["repo_dir"]), spec["base_commit"], artifact, timeout=int(timeout_s))
        wall = int((time.perf_counter() - t0) * 1000)
        evidence.append("apply_check=" + ("ok" if ok else "fail: " + out[-300:]))
        # ponytail: 패치의 테스트 실행은 SWE-bench 하네스(Docker)가 하므로 여기서는 apply 여부까지만 → level=apply, passed=False
        return _result("apply", "no_tests" if ok else "error", evidence, method, applied=ok, wall_ms=wall, exec_count=1, sandbox="subprocess")

    # ── code: AST 사전검사 ──
    method.append("ast")
    try:
        tree = ast.parse(artifact)
    except SyntaxError as e:
        evidence.append(f"ast=syntax_error line {e.lineno}: {e.msg}")
        return _result("static", "error", evidence, method)
    defs = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    evidence.append(f"ast=ok defs={sorted(defs)[:8]}")
    flags = _exit_flags(tree)
    if flags:
        evidence.append("flags=" + ",".join(flags))
    entry = spec.get("entry_point")
    if entry and entry not in defs:
        evidence.append(f"entry_point={entry} missing")
        return _result("static", "error", evidence, method, flags=flags)

    prelude = None
    if kind == "mbppplus":
        cases = spec.get(tests_key) or []
        if not entry:
            return _result("static", "error", evidence + ["mbppplus spec without entry_point"], method, flags=flags)
        tests = _mbpp_tests(entry, cases)
        prelude = _mbpp_prelude()
        timeout_s = _mbpp_timeout(cases)
        method.append("mbppplus_official_compare")
    else:
        tests = _normalize_tests(spec.get(tests_key))
    if not tests:
        return _result("static", "no_tests", evidence, method, flags=flags)

    # ── functional: 하네스 실행 ──
    method.append("test_exec")
    h = _run_harness(artifact, tests, timeout_s, prelude=prelude)
    evidence.append(f"harness={h['outcome']} n_run={h['n_run']} n_passed={h['n_passed']} n_failed={h['n_failed']}"
                    + (" errors=" + " | ".join(h["errors"]) if h["errors"] else "")
                    + (f" tail={h['tail']!r}" if h["outcome"] in ("timeout", "aborted") and h["tail"] else ""))
    return _result("functional", h["outcome"], evidence, method, flags=flags, n_run=h["n_run"], n_passed=h["n_passed"],
                   n_failed=h["n_failed"], wall_ms=h["wall_ms"], exec_count=1, sandbox=h["sandbox"])


def verify_visible(artifact: str, spec: Optional[Dict[str, Any]] = None, timeout_s: float = 60.0) -> Dict[str, Any]:
    """루프 안 검증기. spec["tests"](공개 테스트)만 본다. 행동 결정용 신호."""
    return _verify(artifact, spec, "tests", timeout_s)


def score_hidden(artifact: str, spec: Optional[Dict[str, Any]] = None, timeout_s: float = 60.0) -> Dict[str, Any]:
    """사후 채점기. spec["hidden_tests"] 를 본다. 에피소드 종료 후에만 호출하고 TaskState.score 에 trigger=post_hoc 로 기록."""
    r = _verify(artifact, spec, "hidden_tests", timeout_s)
    r["trigger"] = "post_hoc"
    return r


# 하위 호환 (A1 이름). 새 코드는 verify_visible 을 쓴다.
verify_artifact = verify_visible


if __name__ == "__main__":  # 최소 자체 점검
    good = "def add(a, b):\n    return a + b\n"
    r = verify_visible(good, {"kind": "code", "entry_point": "add", "tests": ["assert add(1, 2) == 3", "assert add(0, 0) == 0"]})
    assert r["passed"] and r["level"] == "functional" and r["outcome"] == "pass" and r["n_run"] == 2 and r["cost_tokens"] == 0, r
    r = verify_visible(good, {"kind": "code", "entry_point": "add"})
    assert not r["passed"] and r["level"] == "static" and r["outcome"] == "no_tests", r
    r = verify_visible(good, {"kind": "code", "entry_point": "sub"})
    assert not r["passed"] and "missing" in r["evidence"], r
    r = verify_visible("import sys\nsys.exit(0)\n", {"kind": "code", "tests": ["assert True"]})
    assert not r["passed"] and r["outcome"] == "error" and r["flags"], r
    r = score_hidden(good, {"kind": "code", "hidden_tests": ["assert add(1, 2) == 4"]})
    assert not r["passed"] and r["outcome"] == "fail" and r["trigger"] == "post_hoc", r
    assert extract_artifact("text\n```python\nx = 1\n```\nmore") == "x = 1"
    print("verify.py self-check OK")
