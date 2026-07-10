# core/calculator.py
"""
ISO5167 Corner Tap（RHG完全式）および ASME MFC-14M、JIS Z 8762:1995 による
オリフィス流量計算のコアモジュール（完全リファクタ版）

・計算モジュールとして純粋関数のみ提供
・適用判定（○/×）や不適合理由は GUI 側で実施
・計算不能時は None を返し、例外は外に投げない
"""

import math
import pandas as pd
from typing import Dict, Optional

from core.constants import (
    R, P_NORM, T_NORM, T_REF_DIM,
    MATERIALS_PLATE, MATERIALS_PIPE,
    Z_MODELS
)
from core.gas_database import (
    GAS_DATABASE,
    calculate_mixture_properties
)
from core.iso5167_rhg import (
    calculate_iso5167_with_rhg_uncertainty,
    calc_thick_plate_C_correction,
)
from core.plate_deflection import calc_plate_deflection_stress
from core.asme_mfc14m import (
    _calculate_asme_mfc14m_single_point,
)
from core.jis_z8762 import (
    _calculate_jis_z8762_single_point,
)
from core.asme_mfc14m_conformance import (
    check_asme_conformance,
)


# ============================================================
# 寸法補正
# ============================================================

def correct_dimension(original_mm: float, temp_degC: float, alpha: float):
    corrected = original_mm * (1 + alpha * (temp_degC - T_REF_DIM))
    rate = (corrected - original_mm) / max(original_mm, 0.01) * 100
    return corrected, rate


# ============================================================
# 密度計算
# ============================================================

def calc_density(P_Pa: float, T_K: float, M_kg_per_mol: float, Z):
    """圧縮係数 Z を用いた密度計算。Z が None の場合は理想気体（Z=1.0）で計算。"""
    try:
        Z_use = float(Z) if (Z is not None and float(Z) > 0) else 1.0
        return (P_Pa * M_kg_per_mol) / max(Z_use * R * T_K, 1e-10)
    except Exception:
        return None


# ============================================================
# ノルマル流量換算
# ============================================================

def calc_normal_flow(Qv_m3h: float, P1_Pa: float, T_K: float,
                     Z, Z_n=1.0):
    """ノルマル流量換算。Z が None の場合は Z=1.0 で計算（理想気体フォールバック）。"""
    try:
        Z_use   = float(Z)   if (Z   is not None and float(Z)   > 0) else 1.0
        Z_n_use = float(Z_n) if (Z_n is not None and float(Z_n) > 0) else 1.0
        return Qv_m3h * (P1_Pa / P_NORM) * (T_NORM / T_K) * (Z_use / Z_n_use)
    except Exception:
        return None


# ============================================================
# 永久圧力損失（ISO/JIS）
# ============================================================

def calc_permanent_pressure_loss_iso_jis(beta: float, deltaP_Pa: float) -> Optional[float]:
    """
    ISO 5167 / JIS Z 8762 の永久圧力損失（符号は規格上は負）
    ΔP_perm = ΔP * (1 - ((1 - β^4)/(1 - β^2))^2)
    ※ ここでは絶対値化せず、後段で abs を取るかどうかは呼び出し側に委ねてもよいが、
      本アプリでは「絶対値」を使うため、ここで abs を返す。
    """
    try:
        if beta is None:
            return None
        if beta <= 0.0 or beta >= 1.0:
            return None

        ratio = (1 - beta**4) / max((1 - beta**2), 1e-12)
        ppl_raw = deltaP_Pa * (1 - ratio**2)
        return abs(ppl_raw)
    except Exception:
        return None


# ============================================================
# ASME 永久圧力損失
# ============================================================

def calc_permanent_pressure_loss_asme(beta: float, D_mm: float, deltaP_Pa: float) -> Optional[float]:
    try:
        if D_mm is None:
            return None
        D_eff = max(6.0, min(D_mm, 40.0))
        K = 0.5 + 0.2 * (beta - 0.6) - 0.1 * (D_eff / 40.0)
        K = max(K, 0.0)
        return K * deltaP_Pa
    except Exception:
        return None


# ============================================================
# 共通：ガス物性・寸法補正・状態量
# ============================================================

def _prepare_common_state(
    gas_name: str,
    D_original_mm: float,
    d_original_mm: float,
    plate_mat: str,
    pipe_mat: str,
    P1_kPa: float,
    deltaP_kPa: float,
    T_degC: float,
    z_model_name: str,
    mixture_composition: Optional[Dict[str, float]] = None,
):
    corr = {}

    # ガス物性
    if mixture_composition:
        mix = calculate_mixture_properties(mixture_composition)
        M_g = mix["M"]
        kappa = mix["kappa"]
        mu = mix["mu_ref"]
        gas_prop = mix
        gas_label = f"{gas_name}(mixture)"
    else:
        base = GAS_DATABASE[gas_name]
        M_g = base["M"]
        kappa = base["kappa"]
        mu = base["mu_ref"]
        gas_prop = base
        gas_label = gas_name

    M_kg = M_g / 1000.0

    # 寸法補正
    alpha_plate = MATERIALS_PLATE.get(plate_mat, 0.0)
    alpha_pipe = MATERIALS_PIPE.get(pipe_mat, 0.0)

    D_corr, rate_D = correct_dimension(D_original_mm, T_degC, alpha_pipe)
    d_corr, rate_d = correct_dimension(d_original_mm, T_degC, alpha_plate)

    beta_orig = d_original_mm / max(D_original_mm, 0.01)
    beta_corr = d_corr / max(D_corr, 0.01)
    rate_beta = (beta_corr - beta_orig) / max(beta_orig, 0.01) * 100

    # 状態量
    P1_Pa = P1_kPa * 1000.0
    deltaP_Pa = deltaP_kPa * 1000.0
    T_K = T_degC + 273.15

    Z_func = Z_MODELS.get(z_model_name, lambda P, T, prop: 1.0)
    Z_error = None
    try:
        Z = Z_func(P1_Pa, T_K, gas_prop)
        Z_n = Z_func(P_NORM, T_NORM, gas_prop)
    except Exception as ex:
        Z = None
        Z_n = None
        Z_error = f"{type(ex).__name__}: {ex}"

    # Z が None になった場合、CoolProp系モデルなら詳細な失敗理由を取得する
    if Z is None and z_model_name != "理想気体":
        if Z_error is None:
            try:
                from core.coolprop_models import get_last_z_error
                Z_error = get_last_z_error()
            except Exception:
                Z_error = None
        if Z_error is None:
            Z_error = f"{z_model_name}モデルがNoneを返しました（原因不明）"

    # Z の計算自体は成功したが、内部で別バックエンドへ自動フォールバック
    # した場合（例: HEOS混合ガスが特定成分ペアの相互作用データ不足で
    # 構築できず PR で計算した場合）は、エラーではなく情報注記として取得する
    Z_note = None
    if Z is not None and z_model_name != "理想気体":
        try:
            from core.coolprop_models import get_last_z_note
            Z_note = get_last_z_note()
        except Exception:
            Z_note = None

    rho = calc_density(P1_Pa, T_K, M_kg, Z)

    corr["密度ρ[kg/m³]"]  = rho
    corr["圧縮係数Z"]     = Z      # ← テーブル表示・_ensure_z_column で参照
    corr["Z計算エラー"]   = Z_error
    corr["Z計算注記"]     = Z_note

    # 補正情報を corr に格納（GUI 等で参照しやすくする）
    corr["補正後D[mm]"] = D_corr
    corr["補正後d[mm]"] = d_corr
    corr["D_corr"] = D_corr
    corr["d_corr"] = d_corr
    corr["beta_corr"] = beta_corr
    corr["rate_D[%]"] = rate_D
    corr["rate_d[%]"] = rate_d
    corr["rate_beta[%]"] = rate_beta

    return {
        "M_g": M_g,
        "M_kg": M_kg,
        "kappa": kappa,
        "mu": mu,
        "gas_prop": gas_prop,
        "gas_label": gas_label,
        "D_corr": D_corr,
        "d_corr": d_corr,
        "beta_orig": beta_orig,
        "beta_corr": beta_corr,
        "rate_D": rate_D,
        "rate_d": rate_d,
        "rate_beta": rate_beta,
        "P1_Pa": P1_Pa,
        "deltaP_Pa": deltaP_Pa,
        "T_K": T_K,
        "Z": Z,
        "Z_n": Z_n,
        "Z_error": Z_error,
        "Z_note": Z_note,
        "rho": rho,
        "corr": corr,
    }


# ============================================================
# 単点計算（ISO / ASME / JIS）※純粋計算版
# ============================================================

def _calculate_single_point_iso5167(
    gas_name: str,
    D_original_mm: float,
    d_original_mm: float,
    plate_mat: str,
    pipe_mat: str,
    P1_kPa: float,
    deltaP_kPa: float,
    T_degC: float,
    z_model_name: str,
    mixture_composition: Optional[Dict[str, float]] = None,
    include_uncertainty: bool = True,
    mode: str = "ISO_RHG",
    plate_thickness_mm: Optional[float] = None,   # ← プレート厚み
):

    common = _prepare_common_state(
        gas_name, D_original_mm, d_original_mm,
        plate_mat, pipe_mat,
        P1_kPa, deltaP_kPa,
        T_degC, z_model_name,
        mixture_composition,
    )

    M_g = common["M_g"]
    kappa = common["kappa"]
    mu = common["mu"]
    gas_label = common["gas_label"]
    D_corr = common["D_corr"]
    d_corr = common["d_corr"]
    beta_orig = common["beta_orig"]
    beta_corr = common["beta_corr"]
    rate_D = common["rate_D"]
    rate_d = common["rate_d"]
    rate_beta = common["rate_beta"]
    P1_Pa = common["P1_Pa"]
    deltaP_Pa = common["deltaP_Pa"]
    T_K = common["T_K"]
    Z = common["Z"]
    Z_n = common["Z_n"]
    Z_error = common.get("Z_error")
    Z_note = common.get("Z_note")
    rho = common["rho"]

    # Re 収束ループ（300回）
    D_m = D_corr / 1000.0
    Re = 50000.0
    last_result = None

    for _ in range(300):
        try:
            if mode == "ISO_RHG":
                result = calculate_iso5167_with_rhg_uncertainty(
                    gas_name=gas_name,
                    beta=beta_corr,
                    Re=Re,
                    D_mm=D_corr,
                    P1_kPa=P1_kPa,
                    deltaP_kPa=deltaP_kPa,
                    T_degC=T_degC,
                    kappa=kappa,
                    rho_kg_m3=rho,
                    z_factor=Z,
                    include_uncertainty=include_uncertainty,
                )

            elif mode == "ASME_MFC14M":
                result = _calculate_asme_mfc14m_single_point(
                    beta=beta_corr,
                    D_mm=D_corr,
                    P1_kPa=P1_kPa,
                    deltaP_kPa=deltaP_kPa,
                    kappa=kappa,
                    rho_kg_m3=rho,
                )

            elif mode == "JIS_Z8762":
                result = _calculate_jis_z8762_single_point(
                    beta=beta_corr,
                    D_mm=D_corr,
                    P1_kPa=P1_kPa,
                    deltaP_kPa=deltaP_kPa,
                    kappa=kappa,
                    rho_kg_m3=rho,
                    Re=Re,
                )

            else:
                # 未知モード → 全て None
                result = {
                    "status": "SUCCESS",
                    "C_iso": None,
                    "epsilon": None,
                    "Qv_m3h": None,
                    "Re": Re,
                    "uncertainty": None,
                }

            # ここでは status を見てエラー終了しない
            if result is None:
                last_result = {
                    "C_iso": None,
                    "epsilon": None,
                    "Qv_m3h": None,
                    "uncertainty": None,
                }
                break

            last_result = result
            Qv_m3h = result.get("Qv_m3h", None)

            if Qv_m3h is None or rho is None or mu is None:
                # Re 更新不能 → その時点の Re を採用して終了
                break

            Qv_m3s = Qv_m3h / 3600.0
            Re_new = 4 * rho * Qv_m3s / (math.pi * D_m * mu)

            if abs(Re_new - Re) / max(Re_new, 1e-12) < 1e-4:
                Re = Re_new
                break

            Re = Re_new

        except Exception:
            last_result = {
                "C_iso": None,
                "epsilon": None,
                "Qv_m3h": None,
                "uncertainty": None,
            }
            break

    if last_result is None:
        last_result = {
            "C_iso": None,
            "epsilon": None,
            "Qv_m3h": None,
            "uncertainty": None,
        }

    C_iso = last_result.get("C_iso", None)
    epsilon = last_result.get("epsilon", None)
    Qv_m3h = last_result.get("Qv_m3h", None)
    uncertainty = last_result.get("uncertainty", None)

    # ── プレート厚み補正（Spink 1978 / ISO TR 15377）──
    thick_corr_detail = None
    if plate_thickness_mm is not None and plate_thickness_mm > 0:
        k_corr, thick_corr_detail = calc_thick_plate_C_correction(
            t_mm=plate_thickness_mm,
            d_mm=d_corr,
            D_mm=D_corr,
        )
        if C_iso is not None and k_corr != 1.0:
            C_iso = C_iso * k_corr
            # Qv は C に比例するため同じ係数で補正
            if Qv_m3h is not None:
                Qv_m3h = Qv_m3h * k_corr

    # ── プレートたわみ量・最大曲げ応力（環状平板・外周固定/内周自由）──
    #    差圧ΔPによりプレートを曲げる荷重として計算する
    deflection_mm = None
    max_stress_MPa = None
    deflection_detail = None
    if plate_thickness_mm is not None and plate_thickness_mm > 0:
        deflection_mm, max_stress_MPa, deflection_detail = calc_plate_deflection_stress(
            D_mm=D_corr,
            d_mm=d_corr,
            t_mm=plate_thickness_mm,
            deltaP_kPa=deltaP_kPa,
            plate_mat=plate_mat,
        )

    # 永久圧力損失
    if mode in ("ISO_RHG", "JIS_Z8762"):
        ppl_Pa = calc_permanent_pressure_loss_iso_jis(beta_orig, deltaP_Pa)
    else:
        ppl_Pa = calc_permanent_pressure_loss_asme(beta_corr, D_corr, deltaP_Pa)

    # ノルマル流量
    Qn_Nm3h = None
    if Qv_m3h is not None and Z is not None and Z_n is not None:
        Qn_Nm3h = calc_normal_flow(Qv_m3h, P1_Pa, T_K, Z, Z_n)

    row = {
        "差圧[kPa]": deltaP_kPa,
        "流出係数C": C_iso,
        "膨張補正係数ε": epsilon,
        "体積流量[m³/h]": Qv_m3h,
        "ノルマル流量[Nm³/h]": Qn_Nm3h,
        "レイノルズ数Re": Re,
        "密度ρ[kg/m³]": rho,
        "圧縮係数Z": Z,
        "Z計算エラー": Z_error,
        "Z計算注記": Z_note,
        "β": beta_corr,
        "補正後D[mm]": D_corr,
        "補正後d[mm]": d_corr,
        "計算モード": mode,
        "永久圧力損失[Pa]": ppl_Pa,
        "永久圧力損失[kPa]": None if ppl_Pa is None else ppl_Pa / 1000.0,
        "永久圧力損失比ΔPperm/ΔP": None if ppl_Pa is None else ppl_Pa / max(deltaP_Pa, 1e-12),
    }

    if thick_corr_detail is not None:
        row["板厚t[mm]"] = plate_thickness_mm
        row["板厚補正係数k"] = thick_corr_detail.get("k_corr")
        row["板厚補正Δα[%]"] = thick_corr_detail.get("delta_C_pct")

    if deflection_detail is not None:
        row["たわみ量[mm]"] = deflection_mm
        row["最大曲げ応力[MPa]"] = max_stress_MPa

    if include_uncertainty and uncertainty:
        u = uncertainty
        row.update({
            "標準不確かさ[%]": u.get("u_Q_rel_pct"),
            "拡張不確かさ[m3/h]": u.get("U_Q_abs"),
            "拡張不確かさ[%]": u.get("U_Q_rel_pct"),
            "信頼区間下限[m3/h]": u.get("Q_lower_95"),
            "信頼区間上限[m3/h]": u.get("Q_upper_95"),
            "有効自由度": u.get("nu_eff"),
            "カバレッジ係数": u.get("k_eff"),
        })

    correction_info = {
        "計算モード": mode,
        "流体": gas_label,
        "分子量[g/mol]": M_g,
        "比熱比κ": kappa,
        "上流圧力P1[kPa]": P1_kPa,
        "流体温度[℃]": T_degC,
        "D基準→補正[mm]": f"{D_original_mm:.5f} → {D_corr:.5f} ({rate_D:.5f}%)",
        "d基準→補正[mm]": f"{d_original_mm:.5f} → {d_corr:.5f} ({rate_d:.5f}%)",
        "β基準→補正": f"{beta_orig:.5f} → {beta_corr:.5f} ({rate_beta:.5f}%)",
        "補正後D[mm]": D_corr,
        "補正後d[mm]": d_corr,
        "プレート厚み補正": thick_corr_detail,
        "プレートたわみ計算": deflection_detail,
    }

    return pd.DataFrame([row]), common["corr"], correction_info, "OK"


# ============================================================
# 10点計算（ISO / ASME / JIS）※必ず df を返す
# ============================================================

def calculate_10steps_iso5167(
    gas_name: str,
    D_original_mm: float,
    d_original_mm: float,
    plate_mat: str,
    pipe_mat: str,
    P1_kPa: float,
    max_deltaP_kPa: float,
    T_degC: float,
    z_model_name: str,
    mixture_composition: Optional[Dict[str, float]] = None,
    include_uncertainty: bool = True,
    mode: str = "ISO_RHG",
    plate_thickness_mm: Optional[float] = None,   # ← プレート厚み
):

    rows = []
    correction_info_first = None

    for i in range(1, 11):
        dp = max_deltaP_kPa * i / 10.0

        df_point, corr_info, corr_detail, msg = _calculate_single_point_iso5167(
            gas_name, D_original_mm, d_original_mm,
            plate_mat, pipe_mat,
            P1_kPa, dp,
            T_degC, z_model_name,
            mixture_composition,
            include_uncertainty,
            mode=mode,
            plate_thickness_mm=plate_thickness_mm,   # ← 渡す
        )

        if correction_info_first is None:
            correction_info_first = corr_detail

        # --- 安全策：df_point に補正後列が無ければ corr_detail または入力値で埋める ---
        try:
            if df_point is None or df_point.empty:
                cols = [
                    "差圧[kPa]", "流出係数C", "膨張補正係数ε",
                    "体積流量[m³/h]", "ノルマル流量[Nm³/h]",
                    "レイノルズ数Re", "密度ρ[kg/m³]", "圧縮係数Z",
                    "β", "補正後D[mm]", "補正後d[mm]", "計算モード",
                ]
                df_point = pd.DataFrame([{c: None for c in cols}])
                df_point.at[0, "差圧[kPa]"] = dp

            # 補正後D
            if "補正後D[mm]" not in df_point.columns or df_point["補正後D[mm]"].isnull().all():
                val = None
                if corr_info and isinstance(corr_info, dict):
                    val = corr_info.get("D_corr") or corr_info.get("補正後D[mm]") or corr_info.get("D基準→補正[mm]")
                if val is None and corr_detail and isinstance(corr_detail, dict):
                    val = corr_detail.get("D_corr") or corr_detail.get("補正後D[mm]") or corr_detail.get("D基準→補正[mm]")
                if val is None:
                    val = D_original_mm
                df_point["補正後D[mm]"] = val

            # 補正後d
            if "補正後d[mm]" not in df_point.columns or df_point["補正後d[mm]"].isnull().all():
                val = None
                if corr_info and isinstance(corr_info, dict):
                    val = corr_info.get("d_corr") or corr_info.get("補正後d[mm]")
                if val is None and corr_detail and isinstance(corr_detail, dict):
                    val = corr_detail.get("d_corr") or corr_detail.get("補正後d[mm]")
                if val is None:
                    val = d_original_mm
                df_point["補正後d[mm]"] = val

            # β が無ければ補正後で再計算して埋める
            if "β" not in df_point.columns or df_point["β"].isnull().all():
                try:
                    df_point["β"] = df_point["補正後d[mm]"].astype(float) / df_point["補正後D[mm]"].astype(float)
                except Exception:
                    df_point["β"] = None

            # 差圧列が無ければ埋める
            if "差圧[kPa]" not in df_point.columns:
                df_point["差圧[kPa]"] = dp
            else:
                df_point["差圧[kPa]"] = df_point["差圧[kPa]"].fillna(dp)

        except Exception:
            # ここで失敗しても次の点に進む
            pass

        rows.append(df_point)

    # 結合
    df = pd.concat(rows, ignore_index=True)
    df.index = [f"{mode} #{i+1}" for i in range(len(df))]

    # 最終チェック：欠損があれば入力元で埋める
    if "補正後D[mm]" not in df.columns:
        df["補正後D[mm]"] = D_original_mm
    else:
        df["補正後D[mm]"] = df["補正後D[mm]"].fillna(D_original_mm)

    if "補正後d[mm]" not in df.columns:
        df["補正後d[mm]"] = d_original_mm
    else:
        df["補正後d[mm]"] = df["補正後d[mm]"].fillna(d_original_mm)

    # β 列が欠けている場合は補正後から計算
    if "β" not in df.columns:
        try:
            df["β"] = df["補正後d[mm]"].astype(float) / df["補正後D[mm]"].astype(float)
        except Exception:
            df["β"] = None
    else:
        df["β"] = df["β"].fillna(df["補正後d[mm]"].astype(float) / df["補正後D[mm]"].astype(float))

    return df, correction_info_first, {}, "10点計算完了"
