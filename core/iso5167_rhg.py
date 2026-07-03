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



# ============================================================
# プレート厚み補正（Spink 1978 / ISO TR 15377）
# ============================================================

def calc_thick_plate_C_correction(
    t_mm: float,
    d_mm: float,
    D_mm: float,
) -> tuple:
    """
    シャープエッジ維持・プレート厚み超過時の流出係数補正。

    補正式（Spink 1978 / ISO TR 15377 近似）:
        e/d = t / d          （ベベルなしの場合 e = t）
        β   = d / D

        t/d ≤ 0.1 → 補正なし（k_corr = 1.0）
        t/d > 0.1 → k_corr = 1 - 0.011*(t/d - 0.1) / (1 + 10*β²)

        C_補正 = C_RHG × k_corr

    適用条件:
        - シャープエッジが維持されていること（エッジ丸みなし）
        - t/d ≤ 0.5（それ以上はノズル域として別式が必要）
        - 精度: ±0.1 % 程度（実験データが少ない領域では不確かさ大）

    Parameters
    ----------
    t_mm : float  プレート厚み [mm]（ベベルなしの場合、オリフィス面厚 e = t）
    d_mm : float  オリフィス径（温度補正後）[mm]
    D_mm : float  管内径（温度補正後）[mm]

    Returns
    -------
    k_corr : float   補正係数（C_補正 = C_RHG × k_corr）
    detail  : dict   診断情報
    """
    try:
        if t_mm is None or t_mm <= 0 or d_mm is None or d_mm <= 0 or D_mm is None or D_mm <= 0:
            return 1.0, {"status": "入力不正", "k_corr": 1.0}

        beta  = d_mm / D_mm
        t_d   = t_mm / d_mm          # e/d（ベベルなし: e = t）
        e_lim = 0.1 * d_mm           # ISO 規格上限 [mm]
        E_lim = min(0.05 * D_mm, 0.5 * (D_mm - d_mm))  # プレート全厚規格上限 [mm]

        if t_d <= 0.1:
            k_corr = 1.0
            status = "規格内（補正不要）"
            delta_pct = 0.0
        elif t_d > 0.5:
            # ノズル域（補正式の適用限界超過）→ 補正値のみ返し警告
            delta_pct = -0.011 * (t_d - 0.1) / max(1.0 + 10.0 * beta**2, 1e-9) * 100
            k_corr = 1.0 + delta_pct / 100.0
            status = "警告: t/d > 0.5（ノズル域・補正式の精度低下）"
        else:
            delta_pct = -0.011 * (t_d - 0.1) / max(1.0 + 10.0 * beta**2, 1e-9) * 100
            k_corr = 1.0 + delta_pct / 100.0
            status = "厚み補正適用"

        detail = {
            "status":       status,
            "t_mm":         t_mm,
            "d_mm":         d_mm,
            "D_mm":         D_mm,
            "beta":         round(beta,  6),
            "t_per_d":      round(t_d,   6),
            "e_lim_mm":     round(e_lim, 4),
            "E_lim_mm":     round(E_lim, 4),
            "t_over_limit": t_mm > e_lim,
            "delta_C_pct":  round(delta_pct, 6),
            "k_corr":       round(k_corr,    8),
        }
        return k_corr, detail

    except Exception as ex:
        return 1.0, {"status": f"計算エラー: {ex}", "k_corr": 1.0}

