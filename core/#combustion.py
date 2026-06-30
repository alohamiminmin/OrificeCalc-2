"""
core/combustion.py
燃焼特性計算モジュール（Cantera 3.x + 解析計算）

対象: 可燃性ガスを含む単独ガスまたはカスタム混合ガス
計算項目:
  - 密度 [kg/m³]（CoolProp, 指定 T/P 条件）
  - 理論空気量 / 実際の空気量 [Nm³/Nm³]
  - 理論排ガス量 / 排ガス組成 [mol%]
  - 高位発熱量 HHV [MJ/Nm³]
  - 低位発熱量 LHV [MJ/Nm³]
  - 断熱火炎温度 [℃]（空気過剰率 λ 対応）
"""

from __future__ import annotations
import math
import os
import shutil
import tempfile
from typing import Dict, Optional


# ============================================================
# Cantera gri30.yaml ASCIIパス解決
#
# Windows 環境で Python が日本語ユーザー名フォルダ下にインストール
# されている場合、Cantera C++ レイヤーが ShiftJIS パスを UTF-8 で
# 読もうとして "utf-8 codec can't decode byte 0xaa" エラーが発生する。
# 回避策: gri30.yaml を ASCII パスの一時フォルダにコピーして使用する。
# ============================================================
_GRI30_SAFE_PATH: Optional[str] = None


def _get_gri30_path() -> str:
    """
    gri30.yaml への安全な（ASCII のみの）パスを返す。

    優先順位:
    1. CANTERA_DATA 環境変数が設定済み → そのパスを使用
    2. cantera パッケージ内 data/ が ASCII パス → そのまま使用
    3. 非 ASCII パス → %TEMP%/cantera_ascii/ にコピーして使用
    4. 判定不能 → "gri30.yaml"（Cantera 自力探索に委ねる）

    main.py で _setup_cantera_data() を実行済みの場合は
    ほぼ必ず 1. に該当する。
    """
    global _GRI30_SAFE_PATH
    if _GRI30_SAFE_PATH and os.path.isfile(_GRI30_SAFE_PATH):
        return _GRI30_SAFE_PATH

    # 1. CANTERA_DATA 環境変数が設定済みの場合
    env_data = os.environ.get("CANTERA_DATA")
    if env_data:
        candidate = os.path.join(env_data, "gri30.yaml")
        if os.path.isfile(candidate):
            _GRI30_SAFE_PATH = candidate
            return _GRI30_SAFE_PATH

    # 2/3. cantera パッケージから自力で探す
    try:
        import importlib.util
        spec = importlib.util.find_spec("cantera")
        if spec and spec.origin:
            ct_dir   = os.path.dirname(spec.origin)
            data_dir = os.path.join(ct_dir, "data")
            candidate = os.path.join(data_dir, "gri30.yaml")
            if os.path.isfile(candidate):
                if candidate.isascii():
                    _GRI30_SAFE_PATH = candidate
                    return _GRI30_SAFE_PATH
                # 非 ASCII パス → ASCII な一時ディレクトリにコピー
                tmp_dir = os.path.join(
                    tempfile.gettempdir(), "cantera_ascii"
                )
                os.makedirs(tmp_dir, exist_ok=True)
                dest = os.path.join(tmp_dir, "gri30.yaml")
                if not os.path.isfile(dest):
                    for fname in os.listdir(data_dir):
                        if fname.endswith(".yaml"):
                            shutil.copy2(
                                os.path.join(data_dir, fname),
                                os.path.join(tmp_dir, fname),
                            )
                _GRI30_SAFE_PATH = dest
                return _GRI30_SAFE_PATH
    except Exception:
        pass

    # 4. フォールバック: Cantera が自力で探す ("gri30.yaml" のまま)
    _GRI30_SAFE_PATH = "gri30.yaml"
    return _GRI30_SAFE_PATH

# ============================================================
# 定数
# ============================================================
NM3_PER_MOL   = 22.414e-3
MOL_PER_NM3   = 1 / NM3_PER_MOL
WATER_HVAP    = 44.01           # kJ/mol  蒸発潜熱
AIR_O2_FRAC   = 0.2095
AIR_N2_FRAC   = 0.7905
N2_PER_O2     = AIR_N2_FRAC / AIR_O2_FRAC  # ≈ 3.773

# ============================================================
# 燃焼反応データ（1 mol 燃料あたり）
# (o2_mol, co2_mol, h2o_mol, so2_mol)
# ============================================================
_COMB: Dict[str, tuple] = {
    "CH4":    (2.0, 1, 2, 0),
    "C2H6":   (3.5, 2, 3, 0),
    "C3H8":   (5.0, 3, 4, 0),
    "nC4H10": (6.5, 4, 5, 0),
    "iC4H10": (6.5, 4, 5, 0),
    "nC5H12": (8.0, 5, 6, 0),
    "iC5H12": (8.0, 5, 6, 0),
    "C6H14":  (9.5, 6, 7, 0),
    "CO":     (0.5, 1, 0, 0),
    "H2":     (0.5, 0, 1, 0),
    "H2S":    (1.5, 0, 1, 1),
    "DME":    (3.0, 2, 3, 0),
}

# ============================================================
# 不燃成分（燃焼に消費されず排ガスへそのまま希釈成分として通過する）
#   N2, CO2, Ar, He, H2O など。
#   O2 はここには含めない（自己酸化剤として別途特別扱いするため）。
# ============================================================
_INERT_FORMULAS = {"N2", "CO2", "Ar", "He", "H2O"}

# ============================================================
# HHV [kJ/mol]（ISO 6976 / NIST）
# ============================================================
_HHV_KJ_MOL: Dict[str, float] = {
    "CH4":    890.63,  "C2H6":   1560.69, "C3H8":   2219.17,
    "nC4H10": 2877.40, "iC4H10": 2868.20, "nC5H12": 3535.77,
    "iC5H12": 3528.83, "C6H14":  4194.95,
    "CO":     282.98,  "H2":     285.83,  "H2S":    562.01,
    "DME":    1460.40,
}

# ============================================================
# Cantera 種名マッピング（GRI-Mech 3.0）
# ============================================================
_CT_FUEL: Dict[str, str] = {
    "CH4": "CH4", "C2H6": "C2H6", "C3H8": "C3H8",
    "CO":  "CO",  "H2":   "H2",
}
_OXIDIZER = "O2:0.2095, N2:0.7905, AR:0.0093"


# ============================================================
# 密度計算（CoolProp → 理想気体フォールバック）
# ============================================================
def get_component_density(formula: str, T_K: float,
                          P_Pa: float) -> Optional[float]:
    """指定条件での密度 [kg/m³] を返す"""
    try:
        import CoolProp.CoolProp as CP
        from core.coolprop_models import _CP_NAMES
        cp_name = _CP_NAMES.get(formula)
        if cp_name:
            AS = CP.AbstractState("HEOS", cp_name)
            try:
                AS.specify_phase(CP.iphase_gas)
                AS.update(CP.PT_INPUTS, P_Pa, T_K)
            except Exception:
                AS = CP.AbstractState("HEOS", cp_name)
                AS.update(CP.PT_INPUTS, P_Pa, T_K)
            return float(AS.rhomass())
    except Exception:
        pass
    # 理想気体近似
    from core.gas_database import COMPONENT_DATABASE
    M = COMPONENT_DATABASE.get(formula, {}).get("M", 28.97)
    return P_Pa * (M / 1000) / (8.31446 * T_K)


# ============================================================
# Cantera 断熱火炎温度（λ 対応、初期 T/P 反映）
# ============================================================
def _adiabatic_T_cantera(formula_ct: str,
                         lambda_val: float = 1.0,
                         T_K: float = 298.15,
                         P_Pa: float = 101325.0) -> Optional[float]:
    try:
        import cantera as ct
        gas = ct.Solution(_get_gri30_path())
        phi = 1.0 / max(lambda_val, 0.01)   # φ = 1/λ
        gas.set_equivalence_ratio(phi, fuel=formula_ct, oxidizer=_OXIDIZER)
        gas.TP = T_K, P_Pa
        gas.equilibrate("HP")
        return gas.T
    except Exception:
        return None


def _adiabatic_T_analytical(formula: str,
                             lambda_val: float = 1.0,
                             T_K: float = 298.15,
                             P_Pa: float = 101325.0) -> Optional[float]:
    """解析近似（C4+ 等 gri30 非対応ガス用）。初期温度 T_K を起点に加算する。
    圧力 P_Pa は理想気体近似の断熱火炎温度（定圧反応）には現れないが、
    引数として受け取り Cantera 版と同じ呼び出しシグネチャを保つ。
    """
    comb = _COMB.get(formula)
    hhv  = _HHV_KJ_MOL.get(formula)
    if comb is None or hhv is None:
        return None
    o2, co2, h2o, so2 = comb
    n2 = lambda_val * o2 * N2_PER_O2
    o2e = (lambda_val - 1) * o2
    lhv_kj = hhv - h2o * WATER_HVAP
    n_prod = co2 + h2o + so2 + n2 + o2e
    Cp_mix = (co2*54 + h2o*36 + so2*45 + n2*30 + o2e*33) / max(n_prod, 1)
    # λ > 1 では希釈されるため Tad は低下。初期温度 T_K を起点に加算する。
    Tad = T_K + lhv_kj * 1000 / (n_prod * Cp_mix)
    return Tad


# ============================================================
# 単一成分の燃焼特性計算
# ============================================================
def calc_single_combustion(formula: str,
                           lambda_val: float = 1.0,
                           T_K: float = 273.15,
                           P_Pa: float = 101325.0) -> Dict:
    """
    1 成分の燃焼特性。
    不燃成分も密度を返す（is_combustible=False）。
    """
    from core.gas_database import COMPONENT_DATABASE
    name  = COMPONENT_DATABASE.get(formula, {}).get("name", formula)
    rho   = get_component_density(formula, T_K, P_Pa)
    rho_r = round(rho, 5) if rho else None

    comb = _COMB.get(formula)
    hhv  = _HHV_KJ_MOL.get(formula)

    if comb is None or hhv is None:
        return {"formula": formula, "name": name,
                "is_combustible": False, "density_kg_m3": rho_r}

    o2, co2, h2o, so2 = comb

    # 発熱量
    factor = MOL_PER_NM3 / 1000
    HHV = hhv * factor
    LHV = (hhv - h2o * WATER_HVAP) * factor

    # 空気量
    air_stoich  = o2 / AIR_O2_FRAC
    air_actual  = lambda_val * air_stoich

    # 排ガス（λ ≥ 1 完全燃焼）
    o2_excess   = max(lambda_val - 1, 0) * o2
    n2_total    = lambda_val * o2 * N2_PER_O2
    exhaust_mol = co2 + h2o + so2 + o2_excess + n2_total

    exh_raw = {"CO2": co2, "H2O": h2o, "N2": n2_total}
    if so2 > 0:     exh_raw["SO2"] = so2
    if o2_excess > 0: exh_raw["O2"] = o2_excess
    exh_pct = {k: round(v / exhaust_mol * 100, 2) for k, v in exh_raw.items() if v > 0}

    # 断熱火炎温度（初期温度 T_K・初期圧力 P_Pa を反映）
    ct_name = _CT_FUEL.get(formula)
    Tad     = (_adiabatic_T_cantera(ct_name, lambda_val, T_K, P_Pa) if ct_name
               else _adiabatic_T_analytical(formula, lambda_val, T_K, P_Pa))
    Tad_C   = round(Tad - 273.15, 0) if Tad else None

    return {
        "formula":             formula,
        "name":                name,
        "is_combustible":      True,
        "density_kg_m3":       rho_r,
        "HHV_MJ_Nm3":         round(HHV, 3),
        "LHV_MJ_Nm3":         round(LHV, 3),
        "HHV_kJ_mol":         round(hhv, 2),
        "theoretical_air_Nm3": round(air_stoich, 4),
        "actual_air_Nm3":      round(air_actual, 4),
        "exhaust_total_Nm3":  round(exhaust_mol, 4),
        "exhaust_composition": exh_pct,
        "T_adiabatic_C":       Tad_C,
    }


# ============================================================
# 混合ガスの燃焼特性計算
# ============================================================
def calc_mixture_combustion(composition: Dict[str, float],
                            lambda_val: float = 1.0,
                            T_K: float = 273.15,
                            P_Pa: float = 101325.0) -> Dict:
    """
    混合ガスの燃焼特性（成分別 + トータル）

    可燃性成分だけでなく、カスタム成分に含まれる不燃成分
    （N2, CO2, Ar, He, H2O 等）も希釈成分として排ガスに反映する。
    また O2 が含まれる場合は自己供給酸化剤として扱い、
    外部から追加する空気量（理論空気量）から差し引く。
    O2 が燃焼に必要な量を超えて含まれる場合は、その超過分が
    排ガス中の残存 O2 として残る。

    Parameters
    ----------
    composition : {formula: mol_fraction}（合計 1.0 に正規化）
    lambda_val  : 空気過剰率 λ（デフォルト 1.0、外部から追加する空気にのみ適用）
    T_K, P_Pa   : 密度計算条件・断熱火炎温度の初期条件
    """
    total = sum(composition.values())
    if total <= 0:
        return {}
    comp_norm = {k: v / total for k, v in composition.items()}

    results = {}
    t_HHV = t_LHV = 0.0
    combustible_frac = 0.0

    # 1 mol 燃料ガス（混合ガス全体）あたりの O2 要求量・生成物量を集計
    o2_required_total = 0.0   # 可燃成分が完全燃焼するために必要な O2 [mol]
    co2_total = h2o_total = so2_total = 0.0

    # 燃料ガス中にもともと含まれる不燃成分（希釈成分として排ガスへ通過）
    inert_in_fuel: Dict[str, float] = {}
    o2_in_fuel = 0.0

    for formula, frac in comp_norm.items():
        r = calc_single_combustion(formula, lambda_val, T_K, P_Pa)
        results[formula] = r

        if r.get("is_combustible"):
            combustible_frac += frac
            t_HHV += frac * r["HHV_MJ_Nm3"]
            t_LHV += frac * r["LHV_MJ_Nm3"]

            o2, co2, h2o, so2 = _COMB[formula]
            o2_required_total += frac * o2
            co2_total += frac * co2
            h2o_total += frac * h2o
            so2_total += frac * so2

        elif formula == "O2":
            # 燃料ガス中の O2 ：自己供給酸化剤
            o2_in_fuel += frac

        elif formula in _INERT_FORMULAS:
            # 不燃成分（N2, CO2, Ar, He, H2O）：希釈成分として排ガスへそのまま通過
            inert_in_fuel[formula] = inert_in_fuel.get(formula, 0.0) + frac

    # ---- 酸化剤バランス ----
    # 燃料ガス中の O2 がまず燃焼に使われ、不足分のみ外部空気で供給する。
    o2_from_air_stoich = max(o2_required_total - o2_in_fuel, 0.0)
    # 燃料中の O2 が必要量を超えていれば、その超過分は反応せず排ガスに残る。
    o2_fuel_excess = max(o2_in_fuel - o2_required_total, 0.0)

    air_stoich = o2_from_air_stoich / AIR_O2_FRAC      # 外部から追加する理論空気量
    air_actual = lambda_val * air_stoich                # 空気過剰率 λ を適用した実際の空気量

    n2_from_air = air_actual * AIR_N2_FRAC
    o2_excess_from_air = max(lambda_val - 1, 0.0) * o2_from_air_stoich

    # ---- 排ガス組成（mol, 1 mol 燃料ガスあたり） ----
    e_CO2 = co2_total
    e_H2O = h2o_total
    e_SO2 = so2_total
    e_O2  = o2_excess_from_air + o2_fuel_excess
    e_N2  = n2_from_air + inert_in_fuel.get("N2", 0.0)
    e_CO2 += inert_in_fuel.get("CO2", 0.0)
    e_H2O += inert_in_fuel.get("H2O", 0.0)
    e_Ar  = inert_in_fuel.get("Ar", 0.0)
    e_He  = inert_in_fuel.get("He", 0.0)

    t_exh = e_CO2 + e_H2O + e_SO2 + e_O2 + e_N2 + e_Ar + e_He

    exh_comp_t: Dict[str, float] = {}
    if t_exh > 0:
        for k, v in [("CO2", e_CO2), ("H2O", e_H2O), ("SO2", e_SO2),
                     ("O2", e_O2), ("N2", e_N2), ("Ar", e_Ar), ("He", e_He)]:
            if v > 0:
                exh_comp_t[k] = round(v / t_exh * 100, 2)

    # 燃料ガス中の O2 を含む理論／実際の空気量（"追加で必要な空気"として報告）
    t_air_s = round(air_stoich, 4)
    t_air_a = round(air_actual, 4)

    # 混合ガスの断熱火炎温度（Cantera、燃料中の不燃成分・自己供給 O2 を反映）
    Tad_mix = _calc_mixture_Tad_cantera(comp_norm, lambda_val, T_K, P_Pa)
    if Tad_mix is None:
        Tad_mix = _calc_mixture_Tad_analytical(
            comp_norm, lambda_val, T_K,
            o2_required_total, o2_in_fuel, inert_in_fuel,
            co2_total, h2o_total, so2_total,
        )

    return {
        "components": results,
        "total": {
            "HHV_MJ_Nm3":          round(t_HHV, 4),
            "LHV_MJ_Nm3":          round(t_LHV, 4),
            "combustible_frac":    round(combustible_frac, 4),
            "theoretical_air_Nm3": t_air_s,
            "actual_air_Nm3":      t_air_a,
            "exhaust_total_Nm3":   round(t_exh, 4),
            "exhaust_composition": exh_comp_t,
            "T_adiabatic_C":       Tad_mix,
            "o2_self_supplied_Nm3": round(o2_in_fuel, 4),
        }
    }


def _calc_cantera_equilibrium(comp_norm: Dict[str, float],
                               lambda_val: float = 1.0,
                               T_K: float = 298.15,
                               P_Pa: float = 101325.0) -> Optional[Dict]:
    """
    Cantera HP 平衡計算を実行し、断熱火炎温度・燃焼後組成・NOx 平衡値を一括返却。

    Returns None  : gri30 非対応成分が含まれる場合、またはエラー時
    Returns dict  :
        T_adiabatic_C, T_adiabatic_K
        NOx_eq_ppm, NO_eq_ppm
        xO2, xN2, xH2O, xO, xOH
    """
    try:
        import cantera as ct
        gas = ct.Solution(_get_gri30_path())
        species_names = set(gas.species_names)

        for formula, frac in comp_norm.items():
            if frac <= 0:
                continue
            if formula in _CT_FUEL or formula in ("N2", "O2"):
                continue
            if formula in ("CO2", "H2O") and formula in species_names:
                continue
            return None  # Ar・He・DME・C4 以上など非対応

        o2_required = sum(frac * _COMB[f][0]
                          for f, frac in comp_norm.items() if f in _COMB)
        if o2_required <= 0:
            return None

        o2_in_fuel  = comp_norm.get("O2", 0.0)
        o2_from_air = max(o2_required - o2_in_fuel, 0.0)
        air_actual  = lambda_val * o2_from_air / AIR_O2_FRAC

        fuel_parts = {f: frac for f, frac in comp_norm.items() if frac > 0}
        air_moles  = {"O2": air_actual * AIR_O2_FRAC,
                      "N2": air_actual * AIR_N2_FRAC,
                      "AR": air_actual * 0.0093}
        mix = dict(fuel_parts)
        for k, v in air_moles.items():
            mix[k] = mix.get(k, 0.0) + v

        mix_str = ", ".join(f"{k}:{v}" for k, v in mix.items() if v > 0)
        gas.TPX = T_K, P_Pa, mix_str
        gas.equilibrate("HP")

        return {
            "T_adiabatic_C": round(gas.T - 273.15, 0),
            "T_adiabatic_K": gas.T,
            "NOx_eq_ppm":    (gas["NO"].X[0] + gas["NO2"].X[0]) * 1e6,
            "NO_eq_ppm":     gas["NO"].X[0] * 1e6,
            "xO2":  float(gas["O2"].X[0]),
            "xN2":  float(gas["N2"].X[0]),
            "xH2O": float(gas["H2O"].X[0]),
            "xO":   float(gas["O"].X[0]),
            "xOH":  float(gas["OH"].X[0]),
        }
    except Exception:
        return None


def _calc_mixture_Tad_cantera(comp_norm: Dict[str, float],
                               lambda_val: float = 1.0,
                               T_K: float = 298.15,
                               P_Pa: float = 101325.0) -> Optional[float]:
    """既存呼び出し元との互換を維持するラッパー。断熱火炎温度のみを返す。"""
    result = _calc_cantera_equilibrium(comp_norm, lambda_val, T_K, P_Pa)
    return result["T_adiabatic_C"] if result else None


def _calc_mixture_Tad_analytical(comp_norm: Dict[str, float],
                                  lambda_val: float,
                                  T_K: float,
                                  o2_required_total: float,
                                  o2_in_fuel: float,
                                  inert_in_fuel: Dict[str, float],
                                  co2_total: float,
                                  h2o_total: float,
                                  so2_total: float) -> Optional[float]:
    """
    Cantera が使えない場合の解析近似（gri30 非対応成分を含む混合ガス用）。
    1 mol 燃料ガス全体の燃焼によるエンタルピーバランスから、
    不燃成分・自己供給 O2 を含めた断熱火炎温度を推定する。
    """
    if o2_required_total <= 0:
        return None

    hhv_total = sum(frac * _HHV_KJ_MOL[f]
                    for f, frac in comp_norm.items() if f in _HHV_KJ_MOL)
    lhv_total = hhv_total - h2o_total * WATER_HVAP
    if lhv_total <= 0:
        return None

    o2_from_air = max(o2_required_total - o2_in_fuel, 0.0)
    o2_fuel_excess = max(o2_in_fuel - o2_required_total, 0.0)
    air_stoich = o2_from_air / AIR_O2_FRAC
    air_actual = lambda_val * air_stoich

    n2_from_air = air_actual * AIR_N2_FRAC
    o2_excess_from_air = max(lambda_val - 1, 0.0) * o2_from_air

    n_co2 = co2_total + inert_in_fuel.get("CO2", 0.0)
    n_h2o = h2o_total + inert_in_fuel.get("H2O", 0.0)
    n_so2 = so2_total
    n_o2  = o2_excess_from_air + o2_fuel_excess
    n_n2  = n2_from_air + inert_in_fuel.get("N2", 0.0)
    n_ar  = inert_in_fuel.get("Ar", 0.0)
    n_he  = inert_in_fuel.get("He", 0.0)

    n_prod = n_co2 + n_h2o + n_so2 + n_o2 + n_n2 + n_ar + n_he
    if n_prod <= 0:
        return None

    # モル比熱 [J/mol/K]（近似値、Ar/He は単原子分子として He≈21, Ar≈21）
    Cp_mix = (n_co2*54 + n_h2o*36 + n_so2*45 + n_o2*33
              + n_n2*30 + n_ar*21 + n_he*21) / n_prod

    Tad = T_K + lhv_total * 1000 / (n_prod * Cp_mix)
    return round(Tad - 273.15, 0)


# ============================================================
# 可燃ガス判定
# ============================================================
def is_combustible(formula: str) -> bool:
    return formula in _COMB

COMBUSTIBLE_FORMULAS = set(_COMB.keys())


# ============================================================
# サーマルNOx推定（拡張Zeldovich + Cantera 平衡）
# ============================================================

# gri30 で扱える成分のCantera名マッピング
_CT_NOX_MAP: Dict[str, str] = {
    "CH4": "CH4", "C2H6": "C2H6", "C3H8": "C3H8",
    "CO": "CO",   "H2": "H2",
    "N2": "N2",   "O2": "O2",
    "CO2": "CO2", "H2O": "H2O",
}

# 可燃成分の理論O2消費量 [mol O2 / mol 燃料成分]
_O2_REQ: Dict[str, float] = {
    "CH4": 2.0, "C2H6": 3.5, "C3H8": 5.0, "nC4H10": 6.5, "iC4H10": 6.5,
    "nC5H12": 8.0, "iC5H12": 8.0, "C6H14": 9.5,
    "CO": 0.5,  "H2": 0.5,  "H2S": 1.5, "DME": 3.0,
}


def _build_ct_mix_string(comp_norm: Dict[str, float],
                          lambda_val: float) -> Optional[str]:
    """
    混合ガス組成 + 空気（λ考慮）をCantera用の組成文字列に変換する。
    gri30 非対応成分（nC4H10 以上の重質炭化水素・H2S・DME 等）が
    有意量（> 0.1 mol%）含まれる場合は None を返す。
    """
    # gri30 非対応成分チェック
    gri30_unsupported = {"nC4H10", "iC4H10", "nC5H12", "iC5H12",
                          "C6H14", "H2S", "DME"}
    for formula, frac in comp_norm.items():
        if frac > 0.001 and formula in gri30_unsupported:
            return None

    o2_req   = sum(comp_norm.get(f, 0) * o2 for f, o2 in _O2_REQ.items())
    o2_fuel  = comp_norm.get("O2", 0.0)
    o2_air   = max(o2_req - o2_fuel, 0.0)
    air_act  = lambda_val * o2_air / AIR_O2_FRAC

    mix: Dict[str, float] = {}
    for formula, frac in comp_norm.items():
        ct_name = _CT_NOX_MAP.get(formula)
        if ct_name and frac > 0:
            mix[ct_name] = mix.get(ct_name, 0.0) + frac

    mix["O2"] = mix.get("O2", 0.0) + air_act * AIR_O2_FRAC
    mix["N2"] = mix.get("N2", 0.0) + air_act * AIR_N2_FRAC
    mix["AR"] = mix.get("AR", 0.0) + air_act * 0.0093

    return ", ".join(f"{k}:{v}" for k, v in mix.items() if v > 0)


def calc_thermal_nox(
    composition:  Dict[str, float],
    lambda_val:   float,
    T_K:          float,
    P_Pa:         float,
    Q_Nm3h:       float,
    D_burner_mm:  float,
    L_flame_m:    float,
    cantera_eq:   Optional[Dict] = None,
) -> Dict:
    """
    サーマルNOx 3モデル推定（カスタム混合ガス対応）

    Parameters
    ----------
    composition   : {formula: mol_fraction}
    lambda_val    : 空気過剰率 λ
    T_K           : 初期温度 [K]
    P_Pa          : 初期圧力 [Pa]
    Q_Nm3h        : ガス瞬時流量 [Nm³/h]（燃料ガスのみ）
    D_burner_mm   : 燃焼噴出径 [mm]
    L_flame_m     : 想定火炎長 [m]
    cantera_eq    : _calc_cantera_equilibrium() の結果を外部から渡せる（省略時は内部計算）

    Returns
    -------
    dict
        NOx_zeldovich_ppm   : 拡張Zeldovich（T_ad一定）[ppm]
        NOx_cooling_ppm     : 後炎冷却モデル（現実的推定）[ppm]
        NOx_equilibrium_ppm : Cantera平衡上限 [ppm]（gri30非対応時はNone）
        NOx_thermal_mg_Nm3  : 冷却モデル値の mg/Nm³ 換算
        ...火炎特性・入力サマリ・warnings
    """
    import math as _math
    import numpy as _np

    # ── 正規化 ──
    total = sum(composition.values())
    if total <= 0:
        return {"error": "組成が空です"}
    comp_norm = {k: v / total for k, v in composition.items()}

    warnings: list = []

    # ── 実体積流量・燃料噴出速度・滞留時間 ──
    T_norm, P_norm = 273.15, 101325.0
    D_m   = D_burner_mm * 1e-3
    A_m2  = _math.pi * (D_m / 2) ** 2
    Q_m3s = Q_Nm3h / 3600.0 * (T_K / T_norm) * (P_norm / P_Pa)
    v_fuel = Q_m3s / max(A_m2, 1e-12)
    tau_s  = L_flame_m / max(v_fuel, 0.01)

    # ── Cantera 平衡解（外部から渡されなければ内部計算） ──
    eq = cantera_eq
    if eq is None:
        eq = _calc_cantera_equilibrium(comp_norm, lambda_val, T_K, P_Pa)

    if eq is not None:
        T_ad      = eq["T_adiabatic_K"]
        NOx_eq    = eq["NOx_eq_ppm"]
        NO_eq     = eq["NO_eq_ppm"]
        xO2_post  = eq["xO2"]
        xN2_post  = eq["xN2"]
        xH2O_post = eq["xH2O"]
        xO_post   = eq["xO"]
        xOH_post  = eq["xOH"]
        method = "Cantera平衡（gri30.yaml）+ 拡張Zeldovich積分"
    else:
        # 解析フォールバック
        warnings.append(
            "gri30非対応成分を含むため Cantera をスキップ。解析近似で推定します。"
        )
        T_ad_C = _calc_mixture_Tad_analytical(
            comp_norm, lambda_val, T_K,
            o2_required_total=sum(comp_norm.get(f,0)*_COMB[f][0] for f in comp_norm if f in _COMB),
            o2_in_fuel=comp_norm.get("O2", 0.0),
            inert_in_fuel={f: comp_norm[f] for f in ("N2","CO2","Ar","He","H2O") if f in comp_norm},
            co2_total=sum(comp_norm.get(f,0)*_COMB[f][1] for f in comp_norm if f in _COMB),
            h2o_total=sum(comp_norm.get(f,0)*_COMB[f][2] for f in comp_norm if f in _COMB),
            so2_total=sum(comp_norm.get(f,0)*_COMB[f][3] for f in comp_norm if f in _COMB),
        )
        T_ad  = (T_ad_C or 1800.0) + 273.15
        NOx_eq    = None
        NO_eq     = None
        xO2_post  = max(0.0, lambda_val - 1.0) * 0.05
        xN2_post  = 0.71
        xH2O_post = 0.10
        xO_post   = 0.0
        xOH_post  = 0.0
        method = "解析近似（Cantera非対応成分）+ 拡張Zeldovich積分"

    # ── ラジカル濃度（Cantera取得 or 部分平衡近似） ──
    R = 8.314
    C_tot = P_Pa / (R * T_ad)

    if xO_post > 0:
        C_O  = xO_post  * C_tot
        C_OH = xOH_post * C_tot
    else:
        P_atm  = P_Pa / 101325.0
        Kp_O   = _math.exp(-59380 / T_ad + 10.66) if T_ad > 1000 else 1e-20
        xO2e   = max(xO2_post, 1e-6)
        xO_    = _math.sqrt(max(Kp_O * xO2e / P_atm, 0))
        C_O    = xO_ * C_tot
        Kp_OH  = _math.exp(-17400 / T_ad + 9.8) if T_ad > 1000 else 1e-20
        xOH_   = _math.sqrt(max(Kp_OH * xH2O_post * xO2e / P_atm, 0))
        C_OH   = xOH_ * C_tot

    C_O2 = xO2_post * C_tot
    C_N2 = xN2_post * C_tot

    # Zeldovich 速度定数
    k1 = 1.8e8  * _math.exp(-38370 / T_ad)
    k2 = 1.8e4  * T_ad * _math.exp(-4680 / T_ad)
    k3 = 3.8e7  * _math.exp(-85 / T_ad)

    # ── Model A: Zeldovich 積分（T_ad 一定） ──
    denom_A  = 1.0 + k1 * C_O / max(k2 * C_O2 + k3 * C_OH, 1e-30)
    dNO_dt_A = 2.0 * k1 * C_O * C_N2 / denom_A
    C_NO_A   = dNO_dt_A * tau_s
    NO_zel   = C_NO_A / max(C_tot, 1e-30) * 1e6
    if NOx_eq is not None:
        NO_zel = min(NO_zel, NOx_eq)

    # ── Model B: 後炎冷却モデル（温度履歴積分） ──
    # 火炎帯(0 → tau_flame): T_init → T_ad に線形昇温
    # 後炎帯(tau_flame → tau_s): T_ad から T_ad*0.65 に線形冷却（壁面冷却等）
    # → 実燃焼炉の典型的な温度履歴を簡易模擬
    tau_flame = tau_s * 0.15
    tau_post  = tau_s * 0.85
    n_steps   = 80

    C_NO_B = 0.0
    phases = [
        # (t_start, t_end, T_start, T_end)
        (0,         tau_flame, T_K + (T_ad - T_K) * 0.5, T_ad),
        (tau_flame, tau_s,     T_ad,                      T_ad * 0.65),
    ]
    for t0, t1, Ts, Te in phases:
        if t1 <= t0:
            continue
        for i in range(n_steps // 2):
            dt   = (t1 - t0) / (n_steps // 2)
            frac = (i + 0.5) / (n_steps // 2)
            T_i  = Ts + (Te - Ts) * frac

            if T_i < 1200:   # 1200K以下はNO生成無視
                continue

            C_t = P_Pa / (R * T_i)
            # O,OH をアレニウス型でT_adからスケール
            scale_O  = _math.exp(max(-20, -10000 * (1/T_i - 1/T_ad)))
            scale_OH = _math.exp(max(-20, -5000  * (1/T_i - 1/T_ad)))
            C_O_i  = C_O  * scale_O
            C_OH_i = C_OH * scale_OH
            C_O2_i = xO2_post * C_t
            C_N2_i = xN2_post * C_t

            k1i = 1.8e8 * _math.exp(-38370 / T_i)
            k2i = 1.8e4 * T_i * _math.exp(-4680 / T_i)
            k3i = 3.8e7 * _math.exp(-85 / T_i)
            dn  = 1.0 + k1i * C_O_i / max(k2i * C_O2_i + k3i * C_OH_i, 1e-30)
            C_NO_B += 2.0 * k1i * C_O_i * C_N2_i / dn * dt

    NO_cool = C_NO_B / max(C_tot, 1e-30) * 1e6
    if NOx_eq is not None:
        NO_cool = min(NO_cool, NOx_eq)

    # mg/Nm³ 換算（NO 分子量 30, 0℃ 1atm 基準: 1ppm = 30/22.414 mg/Nm³）
    NO_MG = 30.0 / 22.414
    NOx_mg = NO_cool * NO_MG

    # 高温警告
    if T_ad > 2200 + 273.15:
        warnings.append(
            f"断熱火炎温度 {T_ad-273.15:.0f}℃ は極めて高温。Zeldovich 誤差が大きくなります。"
        )
    if v_fuel > 50:
        warnings.append(f"燃料噴出速度 {v_fuel:.1f} m/s が高速です。")

    return {
        # 入力サマリ
        "Q_Nm3h":       Q_Nm3h,
        "D_burner_mm":  D_burner_mm,
        "L_flame_m":    L_flame_m,
        "lambda":       lambda_val,
        "T_init_C":     round(T_K - 273.15, 1),
        "P_kPa":        round(P_Pa / 1000, 3),
        # 火炎特性
        "v_fuel_ms":    round(v_fuel, 3),
        "tau_ms":       round(tau_s * 1000, 2),
        "T_adiabatic_C": round(T_ad - 273.15, 1),
        "T_adiabatic_K": round(T_ad, 1),
        # NOx 3モデル
        "NOx_zeldovich_ppm":    round(NO_zel,  1),   # T_ad一定Zeldovich
        "NOx_cooling_ppm":      round(NO_cool, 1),   # 後炎冷却モデル（推奨）
        "NOx_equilibrium_ppm":  round(NOx_eq,  1) if NOx_eq  is not None else None,
        "NO_equilibrium_ppm":   round(NO_eq,   1) if NO_eq   is not None else None,
        # 代表値（後炎冷却モデル）
        "NOx_thermal_ppm":      round(NO_cool, 1),
        "NOx_thermal_mg_Nm3":   round(NOx_mg,  1),
        # 補足
        "method":   method,
        "warnings": warnings,
    }

