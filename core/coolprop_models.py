# core/coolprop_models.py
"""
CoolProp バックエンドによる圧縮係数 Z および密度計算モジュール。

このモジュールは core/constants.py から動的 import される
（未インストール環境では ImportError → 全関数が None を返すフォールバックに切替）。

対応バックエンド
  HEOS       : Helmholtz EOS。単独ガスは純物質 EOS、混合ガスは
               内部的に GERG-2008 由来の混合則（departure function）を
               用いた高精度計算となる。
  GERG-2008  : 天然ガス用混合則。本アプリでは HEOS と同一関数で扱う
               （CoolProp の HEOS バックエンドが混合ガスに対して
               GERG-2008 の departure function を使用するため等価）。
  SRK        : Soave-Redlich-Kwong（CoolProp 内蔵）
  PR         : Peng-Robinson（CoolProp 内蔵）

単位
  P_Pa : 絶対圧力 [Pa]
  T    : 温度 [K]
  gas_prop : GAS_DATABASE / calculate_mixture_properties の戻り値
             - 単独ガス: "formula" キーを持つ
             - 混合ガス: "composition" キー（{formula: mol_fraction}）を持つ

NOTE: CoolProp.CoolProp は意図的にモジュール先頭ではなく各関数内で
      遅延 import している（_cp() を参照）。CoolProp の Cython 拡張
      （.pyd）はサイズが大きく、特に Windows 環境では Authenticode
      署名検証で証明書失効リスト（CRL/OCSP）をネットワーク照会する
      ことがあり、社内プロキシ環境ではこれが数十秒〜数分のタイム
      アウトを引き起こす場合がある。core/constants.py がモジュール
      読み込み時に本モジュールを import するため、ここで即時 import
      していると「アプリのウィンドウを開く前に必ず CoolProp の DLL
      ロードが完了するまで待たされる」状態になり、ウィンドウが
      表示されるまで毎回数分かかる不具合の原因になっていた。
      遅延 import にすることで、実際に HEOS 等の Z 計算が呼ばれる
      まで CoolProp はロードされず、アプリ起動（ウィンドウ表示）は
      常に即座に行われる。
"""

from __future__ import annotations
from typing import Dict, Optional, Any


def _cp():
    """CoolProp.CoolProp を遅延 import して返す。"""
    import CoolProp.CoolProp as CP
    return CP



# ============================================================
# 化学式 → CoolProp 流体名マッピング
# gas_database.CP_NAME_MAP と同一内容（循環 import を避けるため複製）
# ============================================================
_CP_NAMES: Dict[str, str] = {
    "CH4":     "Methane",
    "C2H6":    "Ethane",
    "C3H8":    "Propane",
    "nC4H10":  "n-Butane",
    "iC4H10":  "IsoButane",
    "nC5H12":  "n-Pentane",
    "iC5H12":  "Isopentane",
    "C6H14":   "n-Hexane",
    "N2":      "Nitrogen",
    "O2":      "Oxygen",
    "CO2":     "CarbonDioxide",
    "H2S":     "HydrogenSulfide",
    "CO":      "CarbonMonoxide",
    "H2":      "Hydrogen",
    "He":      "Helium",
    "Ar":      "Argon",
    "H2O":     "Water",
    "DME":     "DimethylEther",
}


def _resolve_components(gas_prop: Dict[str, Any]):
    """gas_prop から (formula リスト, mole分率リスト) を組み立てる。"""
    comp = gas_prop.get("composition")
    if comp:
        total = sum(comp.values())
        if total <= 0:
            return None, None
        formulas = [f for f in comp if f in _CP_NAMES]
        if not formulas:
            return None, None
        fracs = [comp[f] / total for f in formulas]
        return formulas, fracs

    formula = gas_prop.get("formula")
    if formula and formula in _CP_NAMES:
        return [formula], [1.0]

    return None, None


def _build_state(backend: str, gas_prop: Dict[str, Any]):
    """指定バックエンドの AbstractState を構築（流体名未解決なら None）。"""
    formulas, fracs = _resolve_components(gas_prop)
    if not formulas:
        return None

    cp_names = [_CP_NAMES[f] for f in formulas]
    fluid_str = "&".join(cp_names)

    CP = _cp()
    AS = CP.AbstractState(backend, fluid_str)
    if len(cp_names) > 1:
        AS.set_mole_fractions(fracs)
    return AS


def _update_with_phase_fallback(AS, P_Pa: float, T: float) -> bool:
    """
    気相を優先して状態を確定する。
    常温常圧で液相安定な成分（水蒸気・重質炭化水素等）が混合・単独で
    含まれる場合は、まず気相を強制してみて、それが物理的に解けない
    （過飽和など）場合は相指定なしで再試行する。
    戻り値: 状態更新に成功したかどうか
    """
    CP = _cp()
    try:
        AS.specify_phase(CP.iphase_gas)
        AS.update(CP.PT_INPUTS, P_Pa, T)
        return True
    except Exception:
        pass

    try:
        AS.specify_phase(CP.iphase_not_imposed)
    except Exception:
        pass

    try:
        AS.update(CP.PT_INPUTS, P_Pa, T)
        return True
    except Exception:
        return False


def _calc_Z_backend(backend: str, P_Pa: float, T: float,
                     gas_prop: Dict[str, Any]) -> Optional[float]:
    try:
        if P_Pa is None or T is None or T <= 0 or P_Pa <= 0:
            return None
        AS = _build_state(backend, gas_prop)
        if AS is None:
            return None
        if not _update_with_phase_fallback(AS, P_Pa, T):
            return None
        Z = AS.compressibility_factor()
        if Z is None or Z <= 0:
            return None
        return float(Z)
    except Exception:
        return None


def _calc_rho_backend(backend: str, P_Pa: float, T: float,
                       gas_prop: Dict[str, Any]) -> Optional[float]:
    try:
        if P_Pa is None or T is None or T <= 0 or P_Pa <= 0:
            return None
        AS = _build_state(backend, gas_prop)
        if AS is None:
            return None
        if not _update_with_phase_fallback(AS, P_Pa, T):
            return None
        rho = AS.rhomass()
        if rho is None or rho <= 0:
            return None
        return float(rho)
    except Exception:
        return None


# ============================================================
# Z_MODELS から呼ばれる公開関数
#   署名: calc_Z_xxx(P_Pa, T, gas_prop) -> float | None
# ============================================================

def calc_Z_HEOS(P_Pa: float, T: float, gas_prop: Dict[str, Any]) -> Optional[float]:
    """
    Helmholtz EOS。
    単独ガス: 純物質 HEOS。
    混合ガス: CoolProp の HEOS バックエンドが混合則として
              GERG-2008 の departure function を用いるため、
              事実上 GERG-2008 と同等の精度になる。
    """
    return _calc_Z_backend("HEOS", P_Pa, T, gas_prop)


def calc_Z_GERG2008(P_Pa: float, T: float, gas_prop: Dict[str, Any]) -> Optional[float]:
    """GERG-2008（天然ガス混合則）。実装上は HEOS バックエンドと等価。"""
    return _calc_Z_backend("HEOS", P_Pa, T, gas_prop)


def calc_Z_SRK(P_Pa: float, T: float, gas_prop: Dict[str, Any]) -> Optional[float]:
    """Soave-Redlich-Kwong（CoolProp 内蔵実装）。"""
    return _calc_Z_backend("SRK", P_Pa, T, gas_prop)


def calc_Z_PR_coolprop(P_Pa: float, T: float, gas_prop: Dict[str, Any]) -> Optional[float]:
    """Peng-Robinson（CoolProp 内蔵実装）。"""
    return _calc_Z_backend("PR", P_Pa, T, gas_prop)


# ============================================================
# 密度計算（core/combustion.py 等から利用）
# ============================================================

def calc_rho_HEOS(P_Pa: float, T: float, gas_prop: Dict[str, Any]) -> Optional[float]:
    """HEOS バックエンドによる密度 [kg/m³]。"""
    return _calc_rho_backend("HEOS", P_Pa, T, gas_prop)
