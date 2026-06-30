# core/asme_mfc14m.py
"""
ASME MFC-14M: Orifice Plates and Nozzles 用モジュール（完全リファクタ版）

・適用判定（○/×）や備考は一切行わない
・β, Re, D の範囲チェックもしない
・計算不能時は None を返し、例外は外に投げない
・calculator.py からは純粋計算モジュールとして呼び出される
"""

import math
from typing import Dict, Tuple


# ============================================================
# C 計算（Stolz式・純粋計算版）
# ============================================================

def calc_asme_mfc14m_C(
    beta: float,
    Re: float,
    D_mm: float,
    tap_type: str = "corner",
) -> Tuple[float, Dict]:
    """
    ASME MFC-14M-2003 コーナータップ用流出係数 C
    ISO 5167-2:2003 Reader-Harris/Gallagher (RHG) 式を採用
    （ASME MFC-14M-2003 は RHG 式を標準化）

    C = 0.5961 + 0.0261β² - 0.216β⁸
      + 0.000521(10⁶β/Re)^0.7
      + (0.0188 + 0.0063·A)·β^3.5·(10⁶/Re)^0.3
      + 0.043·(1 - 0.11·A)·β⁴/(1-β⁴)

    where A = (19000β/Re)^0.8
    """
    try:
        Re = max(Re, 100.0)

        A = (19000.0 * beta / Re) ** 0.8

        C = (
            0.5961
            + 0.0261 * beta**2
            - 0.216  * beta**8
            + 0.000521 * (1e6 * beta / Re) ** 0.7
            + (0.0188 + 0.0063 * A) * beta**3.5 * (1e6 / Re) ** 0.3
            + 0.043 * (1.0 - 0.11 * A) * beta**4 / max(1.0 - beta**4, 1e-9)
        )

        details = {
            "formula": "ASME MFC-14M-2003 / RHG corner tap",
            "beta": beta,
            "Re_D": Re,
            "D_mm": D_mm,
            "A": round(A, 6),
            "C_calculated": round(C, 6),
        }
        return C, details

    except Exception as e:
        return None, {"error": str(e)}


# ============================================================
# ε 計算（ASME 型膨張補正）
# ============================================================

def calc_asme_mfc14m_epsilon(
    beta: float,
    P1_kPa: float,
    deltaP_kPa: float,
    kappa: float,
) -> Tuple[float, Dict]:
    """
    ASME 系の膨張補正係数 ε 計算
    ※ P1<=0 などでも例外は投げず、計算不能時は epsilon=None
    """

    try:
        P1 = P1_kPa * 1000.0
        deltaP = deltaP_kPa * 1000.0

        # 下流圧力（単純差圧）
        P2 = max(P1 - deltaP, 1.0)
        pressure_ratio = P2 / max(P1, 1.0)

        epsilon = 1.0 - (0.351 + 0.256 * beta**4 + 0.93 * beta**8) * (
            1.0 - pressure_ratio**(1.0 / max(kappa, 0.1))
        )

        details = {
            "P1_Pa": P1,
            "P2_Pa": P2,
            "pressure_ratio": pressure_ratio,
            "epsilon": epsilon,
        }

        return epsilon, details

    except Exception as e:
        return None, {"error": str(e)}


# ============================================================
# 【内部関数】単点計算（calculator.py から呼び出し用）
# ============================================================

def _calculate_asme_mfc14m_single_point(
    beta: float,
    D_mm: float,
    P1_kPa: float,
    deltaP_kPa: float,
    kappa: float,
    rho_kg_m3: float,
) -> Dict:
    """
    ASME MFC-14M に基づく単点計算（内部関数）
    calculator.py の _calculate_single_point_iso5167() から呼び出し
    """

    try:
        # 初期値
        Re = 50000.0
        D_m = D_mm / 1000.0
        deltaP_Pa = deltaP_kPa * 1000.0

        max_iter = 300
        tol = 1e-6

        C = None
        epsilon = None
        Qv_m3h = None

        for _ in range(max_iter):
            # 1) C と ε を計算
            C, details_C = calc_asme_mfc14m_C(beta, Re, D_mm, tap_type="corner")
            epsilon, details_eps = calc_asme_mfc14m_epsilon(beta, P1_kPa, deltaP_kPa, kappa)

            if C is None or epsilon is None or rho_kg_m3 is None:
                Qv_m3h = None
                break

            # 2) 流量計算
            #    qv = C/√(1-β⁴) * ε * (π/4)*d² * √(2ΔP/ρ)
            d_m = beta * D_m
            Qv_m3s = (
                C / math.sqrt(max(1.0 - beta**4, 1e-9))
                * epsilon
                * (math.pi / 4.0) * d_m**2
                * math.sqrt(2.0 * deltaP_Pa / max(rho_kg_m3, 1.0e-12))
            )
            Qv_m3h = Qv_m3s * 3600.0

            # 3) Re を更新
            mu = 1.8e-5  # 空気の代表値
            v = Qv_m3s / (math.pi * D_m**2 / 4.0)
            Re_new = rho_kg_m3 * v * D_m / max(mu, 1.0e-12)

            # 4) 収束判定
            if abs(Re_new - Re) / max(Re, 1.0e-6) < tol:
                Re = Re_new
                break

            Re = Re_new

        return {
            "status": "SUCCESS",
            "message": "",
            "C_iso": C,
            "epsilon": epsilon,
            "Qv_m3h": Qv_m3h,
            "Re": Re,
            "uncertainty": None,
        }

    except Exception as e:
        return {
            "status": "SUCCESS",
            "message": str(e),
            "C_iso": None,
            "epsilon": None,
            "Qv_m3h": None,
            "Re": None,
            "uncertainty": None,
        }
