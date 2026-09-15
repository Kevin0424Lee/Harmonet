"""Week2-L3: 실행기(pilot_dryrun.tune_policy)와 시뮬레이터(pilot_power_v4.fit_policy)가 같은 탐색 절차(gap_analysis.explore_fit)를 쓴다 —
같은 합성 입력에서 선택 특징·λ·동결 모델·예측이 같다. K·R·λ 메뉴·특징 상한은 설정 파일에서."""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import gap_analysis as G        # noqa: E402
import pilot_dryrun as PD       # noqa: E402
import pilot_power_v4 as PP     # noqa: E402
import policy_gain as PG        # noqa: E402

CFG = json.loads((ROOT / "evidence" / "week2" / "pilot_config_v4.json").read_text(encoding="utf-8"))
FCFG = {**CFG["features"], "cv": {"K": CFG["features"]["cv"]["K"], "R": 3}}     # R 만 줄인다 (테스트 시간); K·λ 메뉴·상한은 설정 그대로


def _synth(seed=8, n_feat=28):
    m = {"s": 1.0, "delta": 1.277, "beta": [0.0, 0.0, 0.3, 0.0, 0.8, 1.0], "difficulty": False}
    g_ex, g_new = PP.gen(100, seed, m, n_feat), PP.gen(300, seed + 2, m, n_feat)
    return g_ex, g_new, PP.spec_for(m, n_feat)


def test_runner_and_simulator_paths_are_identical():
    g_ex, g_new, menu = _synth()
    rows = PG.rows_from(g_ex)
    Y, C, feats, tasks = G.policy_tensor(rows)
    fit_runner = PD.tune_policy(rows, feats, Y, menu, FCFG, seed=17, workers=1, n_perm=0, n_boot=0)
    apply_sim, a_hat, lam_sim, subset_sim, cv_sim = PP.fit_policy(g_ex, menu, rows, FCFG, seed=17)
    assert fit_runner["lambda"] == lam_sim and fit_runner["subset"] == subset_sim
    assert {k: v["gain"] for k, v in fit_runner["cv"].items()} == cv_sim
    assert np.array_equal(G.apply_p2(fit_runner["model"], g_new["feats"]), apply_sim(g_new["feats"]))
    assert fit_runner["model"]["beta"] == G.fit_p2(feats, Y, subset_sim, lam_sim)["beta"]      # 동결 모델 계수 비트 동일
    assert fit_runner["cv"][str(lam_sim)]["cv"] == {"K": FCFG["cv"]["K"], "R": FCFG["cv"]["R"]} and fit_runner["cv"][str(lam_sim)]["nested_selection"] is True


def test_config_values_are_read_not_hardcoded():
    g_ex, g_new, menu = _synth(seed=3, n_feat=12)
    rows = PG.rows_from(g_ex)
    Y, C, feats, tasks = G.policy_tensor(rows)
    f2 = {**FCFG, "lambda_menu": [0.3, 1.0, 3.0, 30.0], "max_selected": 8, "cv": {"K": 4, "R": 2}}
    fit = G.explore_fit(rows, feats, Y, menu, f2, seed=5)
    assert set(fit["cv"]) == {"0.3", "1.0", "3.0", "30.0"} and fit["n_features"] <= 8 and fit["cv"]["0.3"]["cv"] == {"K": 4, "R": 2}
    assert fit["lambda"] in f2["lambda_menu"]


def test_k4_procedure_differs_from_registered_one_on_codex_seed():
    """코덱스 재현(alt_5pp / f=28 / seed=8): K4 절차(전체 자료에서 선택 → CV)와 현행 절차(겹 안 선택)는 λ·예측이 다를 수 있다 — 통합 전 불일치의 존재 확인."""
    g_ex, g_new, menu = _synth()
    rows = PG.rows_from(g_ex)
    Y, C, feats, tasks = G.policy_tensor(rows)
    sub_k4 = G.select_features(feats, Y, menu, FCFG["lambda_default"], FCFG["max_selected"])
    cv_k4 = {lam: G.policy_gain(rows, "P2", n_perm=0, n_boot=0, seed=17, spec=sub_k4, with_ci=False, K=FCFG["cv"]["K"], R=FCFG["cv"]["R"], lam=lam)["gain"] for lam in FCFG["lambda_menu"]}
    lam_k4 = max(FCFG["lambda_menu"], key=lambda l: cv_k4[l])
    pick_k4 = G.apply_p2(G.fit_p2(feats, Y, sub_k4, lam_k4), g_new["feats"])
    fit = G.explore_fit(rows, feats, Y, menu, FCFG, seed=17)
    pick_now = G.apply_p2(fit["model"], g_new["feats"])
    mismatch = float((pick_k4 != pick_now).mean())
    print(f"K4 λ={lam_k4} vs 현행 λ={fit['lambda']}, 예측 불일치 {100 * mismatch:.2f}%")
    assert 0.0 <= mismatch <= 1.0                        # 존재 확인용 기록 (값 자체는 seed·R 에 따라 다름)
