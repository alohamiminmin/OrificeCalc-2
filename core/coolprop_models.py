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
    "NH3":     "Ammonia",
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


# HEOS混合ガスが構築できない場合の自動フォールバック先バックエンド。
# Peng-Robinsonは汎用結合則（kij=0）を用いるため、特定成分ペアの
# 実験データが無くても計算できる。本アプリは低圧ガス配管（既定で
# 1次圧 10kPaG 程度まで）が主用途であり、この圧力域では実在気体
# 補正そのものが小さいため、HEOSほど高精度でなくとも実用上十分な
# 精度が得られる。
_HEOS_MIXTURE_FALLBACK_BACKEND = "PR"


def _build_state(backend: str, gas_prop: Dict[str, Any]):
    """
    指定バックエンドの AbstractState を構築（流体名未解決なら None）。

    HEOS で複数成分の混合ガスを構築する際、CoolProp は成分ペアごとの
    二成分相互作用パラメータ（GERG-2008 departure function 用）を
    必要とする。DME や NH3 のように実験データが少ない成分は、N2・O2・
    CH4 など極めて一般的な成分との組み合わせであってもこのデータが
    登録されておらず、AbstractState の構築自体が
    ValueError（"Could not match the binary pair ..."）で失敗する。
    この場合、相互作用パラメータを必要としない汎用立方状態方程式
    （Peng-Robinson）に自動フォールバックし、_last_z_note にその旨を
    記録する（計算自体は継続し、エラー扱いにはしない）。
    """
    global _last_z_note
    formulas, fracs = _resolve_components(gas_prop)
    if not formulas:
        return None

    cp_names = [_CP_NAMES[f] for f in formulas]
    fluid_str = "&".join(cp_names)
    is_mixture = len(cp_names) > 1

    CP = _cp()

    try:
        AS = CP.AbstractState(backend, fluid_str)
        if is_mixture:
            AS.set_mole_fractions(fracs)
        return AS
    except Exception as ex:
        if backend == "HEOS" and is_mixture:
            try:
                AS = CP.AbstractState(_HEOS_MIXTURE_FALLBACK_BACKEND, fluid_str)
                AS.set_mole_fractions(fracs)
                _last_z_note = (
                    f"HEOS(GERG-2008相当)が成分間の相互作用データ不足のため構築できず、"
                    f"{_HEOS_MIXTURE_FALLBACK_BACKEND}(Peng-Robinson)で計算しました"
                    f"（成分: {', '.join(formulas)}）"
                )
                return AS
            except Exception:
                pass  # フォールバックも失敗 → 元の例外を呼び出し元へ伝播
        raise


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


# ============================================================
# 直近のZ計算失敗理由（診断用）
#   CoolProp呼び出しの例外は握りつぶして None を返す設計のため、
#   「なぜNoneになったか」をGUI側で表示できるようにここに保持する。
#   tkinterはシングルスレッドGUIのため、グローバル変数で問題ない。
# ============================================================
_last_z_error: Optional[str] = None

# 直近の計算で発生した「エラーではないが利用者に伝えるべき注記」
#   例: HEOS混合ガスが特定成分ペアの相互作用データ不足で構築できず、
#       Peng-Robinson(PR)へ自動フォールバックした場合など。
#   計算自体は成功している（Z/密度は有効な値を返す）ため _last_z_error
#   とは区別し、GUI側は警告ではなく情報として表示する。
_last_z_note: Optional[str] = None


def get_last_z_error() -> Optional[str]:
    """直近の calc_Z_* 呼び出しでZがNoneになった理由を返す（無ければNone）。"""
    return _last_z_error


def get_last_z_note() -> Optional[str]:
    """直近の calc_Z_*/calc_rho_* 呼び出しで発生した情報注記を返す（無ければNone）。"""
    return _last_z_note


def _calc_Z_backend(backend: str, P_Pa: float, T: float,
                     gas_prop: Dict[str, Any]) -> Optional[float]:
    global _last_z_error, _last_z_note
    _last_z_error = None
    _last_z_note = None
    try:
        if P_Pa is None or T is None or T <= 0 or P_Pa <= 0:
            _last_z_error = f"圧力または温度が不正です (P={P_Pa}, T={T})"
            return None
        AS = _build_state(backend, gas_prop)
        if AS is None:
            _last_z_error = ("CoolPropが対応する流体名を解決できませんでした"
                              "（未対応成分が含まれる可能性があります）")
            return None
        if not _update_with_phase_fallback(AS, P_Pa, T):
            _last_z_error = ("CoolPropの状態計算(update)に失敗しました"
                              "（相領域外・過飽和の可能性）")
            return None
        Z = AS.compressibility_factor()
        if Z is None or Z <= 0:
            _last_z_error = f"CoolPropが不正なZ値を返しました: {Z}"
            return None
        return float(Z)
    except ModuleNotFoundError as ex:
        _last_z_error = f"CoolPropがインストールされていません: {ex}"
        return None
    except Exception as ex:
        _last_z_error = f"{backend}計算で例外発生: {type(ex).__name__}: {ex}"
        return None


def _calc_rho_backend(backend: str, P_Pa: float, T: float,
                       gas_prop: Dict[str, Any]) -> Optional[float]:
    global _last_z_note
    _last_z_note = None
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
