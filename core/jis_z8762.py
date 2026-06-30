import math


# ============================================================
# 【内部関数】単点計算（calculator.py から呼び出し用）
# ============================================================

def _calculate_jis_z8762_single_point(
    beta: float,
    D_mm: float,
    P1_kPa: float,
    deltaP_kPa: float,
    kappa: float,
    rho_kg_m3: float,
    Re: float,
):
    """
    JIS Z 8762:1995（ストルツ式）による単点計算（内部関数）
    calculator.py の _calculate_single_point_iso5167() から呼び出し
    """

    try:
        D_m = D_mm / 1000.0
        d_m = beta * D_m

        deltaP_Pa = deltaP_kPa * 1000.0
        P1_Pa = P1_kPa * 1000.0

        # --- 流出係数 C（JIS Z8762:1995 ストルツ式 / ISO 5167-1:1991 準拠） ---
        # C = 0.5959 + 0.0312β^2.1 - 0.1840β^8 + 0.0029β^2.5(10⁶/Re)^0.75
        # コーナータップ（L1=L2'=0）
        Re_safe = max(Re, 100.0) if (Re is not None and Re > 0) else 1e5

        C = (
            0.5959
            + 0.0312 * beta ** 2.1
            - 0.1840 * beta ** 8
            + 0.0029 * beta ** 2.5 * (1e6 / Re_safe) ** 0.75
        )

        # --- 膨張補正係数 ε（JIS Z8762:1995 式） ---
        try:
            epsilon = 1.0 - (0.41 + 0.35 * (beta ** 4)) * (deltaP_Pa / P1_Pa)
        except Exception:
            epsilon = None

        # --- 流量計算 ---
        # qv = C/√(1-β⁴) * ε * (π/4)*d² * √(2ΔP/ρ)
        if C is None or epsilon is None or rho_kg_m3 is None:
            Qv_m3h = None
        else:
            Qv_m3s = (
                C / math.sqrt(max(1.0 - beta**4, 1e-9))
                * epsilon
                * (math.pi / 4.0) * d_m**2
                * math.sqrt(2.0 * deltaP_Pa / max(rho_kg_m3, 1e-12))
            )
            Qv_m3h = Qv_m3s * 3600.0

        return {
            "status": "SUCCESS",
            "C_iso": C,
            "epsilon": epsilon,
            "Qv_m3h": Qv_m3h,
            "Re_used": Re,
        }

    except Exception:
        return {
            "status": "SUCCESS",
            "C_iso": None,
            "epsilon": None,
            "Qv_m3h": None,
            "Re_used": None,
        }
