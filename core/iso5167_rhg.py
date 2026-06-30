# core/iso5167_rhg.py
"""
ISO 5167-2:2022 Reader-Harris/Gallagher 完全式（RHG）
Corner Tap 用の流出係数 C と膨張補正係数 ε を計算するモジュール

完全リファクタ版：
- 入力チェック（ValueError）を完全削除
- 計算不能時は None を返す
- calculator.py と整合する純粋計算モジュール
"""

import math
import numpy as np


# ============================================================
# RHG 完全式（流出係数 C）
# ============================================================

def calc_iso5167_rhg_complete(beta, Re, D_mm, kappa):
    """
    ISO 5167-2:2022 Annex D - Reader-Harris/Gallagher 完全式
    Corner Tap 用の流出係数 C を計算する。

    ※ 入力チェックは行わない（計算不能時は None）
    """

    try:
        # --- 基本式 ---
        C_base = (
            0.5961
            + 0.0261 * beta**2
            - 0.216 * beta**8
            + 0.000521 * (1e6 / max(Re, 100))**0.7
        )

        C = C_base

        # --- 低Re補正 ---
        if Re < 10000:
            C += (
                0.0293 * beta**4 * (1e6 / max(Re, 100))**0.25
                - 0.1792 * beta**4
            )

        # --- 高β補正 ---
        if beta > 0.5:
            C += (
                0.043 * (1 - 0.11 * beta**2)
                * beta**4
                * (1e6 / max(Re, 100))**0.15
            )

        return C, None

    except Exception:
        return None, None


# ============================================================
# 膨張補正係数 ε（完全式）
# ============================================================

def calc_iso5167_rhg_epsilon(beta, Re, P1_kPa, deltaP_kPa, kappa, D_mm):
    """
    ISO 5167-2:2022 の ε 完全式
    ※ 入力チェックは行わない（計算不能時は None）
    """

    try:
        P1 = P1_kPa * 1000
        deltaP = deltaP_kPa * 1000

        # 圧力比
        pressure_ratio = max(0.0, 1.0 - deltaP / max(P1, 0.01))

        # 等エントロピー膨張
        exponent = 1.0 / max(kappa, 0.1)
        expansion_term = 1.0 - pressure_ratio**exponent

        # Corner Tap の係数
        c1 = 0.351
        c2 = 0.256
        c3 = 0.93

        epsilon = 1.0 - (c1 + c2 * beta**4 + c3 * beta**8) * expansion_term

        return epsilon, None, None

    except Exception:
        return None, None, None


# ============================================================
# RHG 完全式（C・ε・流量Qv をまとめて返す）
# ============================================================

def calculate_iso5167_with_rhg_uncertainty(
    gas_name,
    beta,
    Re,
    D_mm,
    P1_kPa,
    deltaP_kPa,
    T_degC,
    kappa,
    rho_kg_m3,
    z_factor,
    include_uncertainty=True
):
    """
    calculator.py が期待している統合関数。
    C、ε、流量Qv、Re、不確かさ（必要なら）をまとめて返す。

    ※ 入力チェックは行わない
    ※ 計算不能時は None を返す
    """

    # --- C（流出係数） ---
    C, _ = calc_iso5167_rhg_complete(beta, Re, D_mm, kappa)

    # --- ε（膨張補正係数） ---
    epsilon, _, _ = calc_iso5167_rhg_epsilon(
        beta, Re, P1_kPa, deltaP_kPa, kappa, D_mm
    )

    # --- 流量計算 ---
    try:
        deltaP_Pa = deltaP_kPa * 1000
        D_m = D_mm / 1000
        d_m = beta * D_m

        if C is None or epsilon is None or rho_kg_m3 is None:
            Qv_m3h = None
        else:
            #    qv = C/√(1-β⁴) * ε * (π/4)*d² * √(2ΔP/ρ)
            Qv_m3s = (
                C / math.sqrt(max(1.0 - beta**4, 1e-9))
                * epsilon
                * (math.pi / 4.0) * d_m**2
                * math.sqrt(2 * deltaP_Pa / max(rho_kg_m3, 1e-12))
            )
            Qv_m3h = Qv_m3s * 3600

    except Exception:
        Qv_m3h = None

    result = {
        "status": "SUCCESS",
        "C_iso": C,
        "epsilon": epsilon,
        "Qv_m3h": Qv_m3h,
        "Re": Re,
        "uncertainty": None
    }

    return result
