# core/constants.py
"""
計算ロジック専用の定数・物性モデル定義モジュール（完全リファクタ版）
GUI 依存なし
"""

import math
import numpy as np

# ============================================================
# 基本定数
# ============================================================

R = 8.314  # 気体定数 [J/(mol·K)]

T_REF_DIM = 20.0        # 寸法基準温度 [℃]
P_NORM = 101.325 * 1000 # ノルマル状態圧力 [Pa]
T_NORM = 273.15         # ノルマル状態温度 [K]

# ============================================================
# SGP 管内径データ（JIS G 3452）
# ============================================================

SGP_DIAMETERS = {
    "SGP 10A 3/8B": 12.7,
    "SGP 15A 1/2B": 16.1,
    "SGP 20A 3/4B": 21.6,
    "SGP 25A 1B": 27.6,
    "SGP 32A 1 1/4B": 35.7,
    "SGP 40A 1 1/2B": 41.6,
    "SGP 50A 2B": 52.9,
    "SGP 65A 2 1/2B": 67.9,
    "SGP 80A 3B": 80.7,
    "SGP 90A 3 1/2B": 93.2,
    "SGP 100A 4B": 105.3,
    "SGP 125A 5B": 130.8,
    "SGP 150A 6B": 155.2,
    "SGP 175A 7B": 180.1,
    "SGP 200A 8B": 204.7,
    "SGP 250A 10B": 254.2,
    "SGP 300A 12B": 304.7,
    "SGP 350A 14B": 339.8,
    "SGP 400A 16B": 390.6,
    "SGP 450A 18B": 441.4,
    "SGP 500A 20B": 492.2,
    "SGP その他": None
}

# ============================================================
# 材質の線膨張係数 [/℃]
# ============================================================

MATERIALS_PLATE = {
    "SGP": 11.7e-6, "STPG": 11.7e-6, "STKM": 11.7e-6, "SS400": 11.7e-6,
    "SUS304": 17.3e-6, "SUS316": 16.0e-6, "SUS310S": 15.9e-6,
    "銅": 16.5e-6, "真鍮": 19.0e-6, "アルミ": 23.0e-6,
    "FKM": 160e-6, "PE": 200e-6, "POM": 110e-6,
}

MATERIALS_PIPE = MATERIALS_PLATE.copy()

# ============================================================
# 成分臨界定数（Kay's rule 用）
# 出典: NIST, Reid et al., Poling et al.
# ============================================================
_COMP_CRIT = {
    # 化学式: (Tc [K], Pc [Pa], omega)
    "CH4":    (190.6, 4.600e6, 0.0115),
    "C2H6":   (305.3, 4.880e6, 0.0981),
    "C3H8":   (369.8, 4.250e6, 0.1523),
    "nC4H10": (425.1, 3.796e6, 0.2002),
    "iC4H10": (408.1, 3.629e6, 0.1808),
    "nC5H12": (469.7, 3.370e6, 0.2515),
    "iC5H12": (460.4, 3.381e6, 0.2275),
    "C6H14":  (507.6, 3.025e6, 0.3013),
    "N2":     (126.2, 3.390e6, 0.0397),
    "O2":     (154.6, 5.046e6, 0.0222),
    "CO2":    (304.1, 7.376e6, 0.2236),
    "H2S":    (373.2, 8.963e6, 0.0948),
    "CO":     (132.9, 3.499e6, 0.0481),
    "H2":     ( 33.2, 1.297e6, -0.216),
    "He":     (  5.2, 0.228e6, -0.382),
    "Ar":     (150.8, 4.874e6, 0.0000),
}

_OMEGA_DB = {k: v[2] for k, v in _COMP_CRIT.items()}


def _calc_critical_props(gas_prop):
    """
    composition があれば Kay's rule で Tc/Pc/omega を計算。
    なければ gas_prop の値をそのまま返す。
    Returns: (Tc [K], Pc [Pa], omega)
    """
    comp = gas_prop.get("composition")
    if comp:
        total = sum(comp.values())
        Tc    = sum(y/total * _COMP_CRIT[c][0] for c, y in comp.items() if c in _COMP_CRIT)
        Pc    = sum(y/total * _COMP_CRIT[c][1] for c, y in comp.items() if c in _COMP_CRIT)
        omega = sum(y/total * _COMP_CRIT[c][2] for c, y in comp.items() if c in _COMP_CRIT)
        return Tc, Pc, omega
    # 単独ガス: DB 値を使用
    return gas_prop.get("Tc"), gas_prop.get("Pc"), gas_prop.get("omega")


def _calc_omega(gas_prop):
    """後方互換用（Z_MODELS 外からも呼ばれる場合に備えて残す）"""
    _, _, omega = _calc_critical_props(gas_prop)
    return omega


def calc_Z_RedlichKwong(P_Pa, T, gas_prop):
    """P_Pa [Pa]、T [K]、gas_prop: GAS_DATABASE エントリ"""
    try:
        Tc, Pc, _ = _calc_critical_props(gas_prop)
        if Tc is None or Pc is None or T <= 0 or Pc <= 0:
            return 1.0

        # P_Pa はすでに Pa 単位（calculator.py から Pa で渡される）
        a = 0.42748 * (R**2 * Tc**2.5) / Pc
        b = 0.08664 * R * Tc / Pc

        A = a * P_Pa / (R**2 * T**2.5)
        B = b * P_Pa / (R * T)

        coeff = [1, -1, A - B - B**2, -A * B]
        roots = np.roots(coeff)
        real_roots = [r.real for r in roots if abs(r.imag) < 1e-8 and r.real > 0.01]

        return min(real_roots) if real_roots else 1.0
    except:
        return 1.0


def calc_Z_PengRobinson(P_Pa, T, gas_prop):
    """P_Pa [Pa]、T [K]、gas_prop: GAS_DATABASE エントリ"""
    try:
        Tc, Pc, omega = _calc_critical_props(gas_prop)
        if Tc is None or Pc is None or omega is None or T <= 0 or Pc <= 0:
            return 1.0

        # P_Pa はすでに Pa 単位（calculator.py から Pa で渡される）
        Tr = T / Tc
        alpha = (1 + (0.37464 + 1.54226 * omega - 0.26992 * omega**2) * (1 - math.sqrt(Tr)))**2

        a = 0.45724 * (R * Tc)**2 / Pc * alpha
        b = 0.07780 * R * Tc / Pc

        A = a * P_Pa / (R * T)**2
        B = b * P_Pa / (R * T)

        coeff = [
            1,
            -(1 - B),
            (A - 3 * B**2 - 2 * B),
            -(A * B - B**2 - B**3)
        ]

        roots = np.roots(coeff)
        real_roots = [r.real for r in roots if abs(r.imag) < 1e-8 and r.real > 0.01]

        return min(real_roots) if real_roots else 1.0
    except:
        return 1.0


# --- AGA8 Gross（NIST 公式移植） ---
from core.aga8_detail import calc_aga8_detail_z

def calc_Z_AGA8(P_Pa, T, gas_prop):
    return calc_aga8_detail_z(P_Pa, T, gas_prop)

# --- CoolProp ベースのモデル群（未インストール時は None を返すだけ） ---
try:
    from core.coolprop_models import (
        calc_Z_HEOS,
        calc_Z_PR_coolprop,
        calc_Z_SRK,
        calc_Z_GERG2008,
    )
except Exception:
    def calc_Z_HEOS(P_Pa, T, prop):       return None  # type: ignore
    def calc_Z_PR_coolprop(P_Pa, T, prop): return None  # type: ignore
    def calc_Z_SRK(P_Pa, T, prop):        return None  # type: ignore
    def calc_Z_GERG2008(P_Pa, T, prop):   return None  # type: ignore


# ============================================================
# Z モデル辞書
#   キー   : GUI コンボ・Excel 出力に表示される名称
#   値     : calc func(P_Pa, T_K, gas_prop) -> float | None
# ============================================================
Z_MODELS = {
    "理想気体":          lambda P_Pa, T, prop: 1.0,
    "Redlich-Kwong":    calc_Z_RedlichKwong,   # 手動実装
    "Peng-Robinson":    calc_Z_PengRobinson,   # 手動実装
    "SRK":              calc_Z_SRK,            # Soave-Redlich-Kwong (CoolProp)
    "PR (CoolProp)":    calc_Z_PR_coolprop,    # Peng-Robinson (CoolProp)
    "HEOS":             calc_Z_HEOS,           # Helmholtz EOS 純物質 (CoolProp)
    "GERG-2008":        calc_Z_HEOS,           # HEOS の混合ガス版 = GERG-2008
    "AGA8 Gross":       calc_Z_AGA8,           # NIST AGA8 Gross 移植
}

# ============================================================
# Zモデル説明（GUI 用）
# ============================================================

Z_MODEL_INFO = {
    "理想気体": {
        "name": "Ideal Gas (Z=1)",
        "recommended_for": "空気・N₂・O₂（常温常圧）",
        "notes": "常温常圧では誤差 0.1% 以下。高圧では非推奨。",
    },

    "Redlich-Kwong": {
        "name": "Redlich–Kwong (RK)",
        "recommended_for": "CO₂・高温低圧の炭化水素",
        "notes": "古いモデル。低温高圧では誤差が大きい。",
    },

    "Peng-Robinson": {
        "name": "Peng–Robinson (PR)",
        "recommended_for": "炭化水素（CH₄, C₂H₆, C₃H₈, DME, H₂ など）",
        "notes": "現代的で安定。高圧域でも破綻しにくい。",
    },

    "AGA8 Detail": {
        "name": "AGA8 Detail（軽量高速版）",
        "recommended_for": "天然ガス・LNG（国別組成）",
        "notes": "天然ガス専用の高精度状態方程式。CH₄=70〜98% の混合ガスに最適。",
    },
}
