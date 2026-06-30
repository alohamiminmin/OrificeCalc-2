# utils/excel_export.py
"""
Excel 出力専用モジュール
GUI や core に依存しない
"""

import pandas as pd
import os
from datetime import datetime

#from utils.console_uncertainty_report import (
#    generate_console_uncertainty_report,
#    generate_uncertainty_trend_table
#)



def export_to_excel(
    df,
    correction_info,
    fit_results=None,
    output_path=None,
    mixture_composition=None,
    gas_name="",
):
    """
    df（10点計算結果）と補正情報を Excel に保存する
    不確かさ情報も Excel に出力する
    """

    # ---------------------------------------------------------
    # 保存先パスの決定
    # ---------------------------------------------------------
    if output_path is None:
        output_dir = "./excel_output"
        os.makedirs(output_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"orifice_result_{timestamp}.xlsx"
        output_path = os.path.join(output_dir, filename)

    # ---------------------------------------------------------
    # ExcelWriter で複数シート出力
    # ---------------------------------------------------------
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:

        # --- 10点計算結果 ---
        df.to_excel(writer, sheet_name="10点計算結果", index=True)

        # --- 補正情報 ---
        if correction_info is not None:
            corr_df = pd.DataFrame([correction_info])
        else:
            corr_df = pd.DataFrame([{"info": "補正情報なし"}])

        if "備考" in df.columns:
            corr_df["備考"] = df["備考"].iloc[0]

        corr_df.to_excel(writer, sheet_name="補正情報", index=False)

        # --- 混合ガス組成（カスタム混合またはプリセット混合） ---
        if mixture_composition:
            try:
                from core.gas_database import COMPONENT_DATABASE
                rows = []
                for formula, frac in mixture_composition.items():
                    comp_data = COMPONENT_DATABASE.get(formula, {})
                    rows.append({
                        "成分（式）":  formula,
                        "成分名":     comp_data.get("name", formula),
                        "モル分率":   round(frac, 6),
                        "モル%":      round(frac * 100, 3),
                        "M [g/mol]":  comp_data.get("M", ""),
                        "Tc [K]":     comp_data.get("Tc", ""),
                        "Pc [MPa]":   round(comp_data.get("Pc", 0) / 1e6, 4)
                                      if comp_data.get("Pc") else "",
                    })
                comp_df = pd.DataFrame(rows)
                comp_df.to_excel(writer, sheet_name="ガス組成", index=False)
            except Exception:
                pass

        # --- ガス組成シート（混合・単独ガス共通） ---
        _write_composition_sheet(writer, mixture_composition, gas_name)

    return output_path


def _write_composition_sheet(writer, mixture_composition, gas_name=""):
    """ガス組成シートを書き込む（単独ガスも対応）"""
    try:
        from core.gas_database import COMPONENT_DATABASE, GAS_DATABASE
        rows = []

        # 単独ガス：GAS_DATABASE の formula から 100% 組成を生成
        if not mixture_composition and gas_name:
            props = GAS_DATABASE.get(gas_name, {})
            formula = props.get("formula")
            if formula:
                mixture_composition = {formula: 1.0}

        if not mixture_composition:
            return

        for formula, frac in mixture_composition.items():
            cd = COMPONENT_DATABASE.get(formula, {})
            rows.append({
                "成分（式）":  formula,
                "成分名":      cd.get("name", formula),
                "モル分率":    round(frac, 6),
                "モル%":       round(frac * 100, 3),
                "M [g/mol]":   cd.get("M", ""),
                "kappa":       cd.get("kappa", ""),
                "Tc [K]":      cd.get("Tc", ""),
                "Pc [MPa]":    round(cd.get("Pc", 0) / 1e6, 4) if cd.get("Pc") else "",
                "omega":       cd.get("omega", ""),
                "mu_ref [μPa·s]": round(cd.get("mu_ref", 0) * 1e6, 3) if cd.get("mu_ref") else "",
            })
        pd.DataFrame(rows).to_excel(writer, sheet_name="ガス組成", index=False)
    except Exception:
        pass


def export_combustion_to_excel(result: dict, gas_name: str,
                                composition: dict, output_path: str = None,
                                nox_result: dict = None) -> str:
    """燃焼特性計算結果を Excel に出力（サーマルNOx対応）"""
    if output_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"./combustion_{ts}.xlsx"

    from core.gas_database import COMPONENT_DATABASE

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:

        # --- 成分別シート ---
        # 合計密度（混合密度）= Σ(xi × ρi)
        rho_mix = sum(
            frac * (result["components"].get(f, {}).get("density_kg_m3", 0.0))
            for f, frac in composition.items()
        )

        rows_comp = []
        for formula, frac in composition.items():
            r = result["components"].get(formula)
            is_c = bool(r and r.get("is_combustible"))
            exh = r.get("exhaust_composition", {}) if r else {}
            rho = r.get("density_kg_m3", "") if r else ""
            rows_comp.append({
                "成分（式）":   formula,
                "成分名":       COMPONENT_DATABASE.get(formula, {}).get("name", formula),
                "モル分率":     round(frac, 4),
                "モル%":        round(frac * 100, 2),
                "vol%":         round(frac * 100, 2),   # 同温同圧理想気体: vol% = mol%
                "密度 [kg/Nm³]": round(rho, 5) if isinstance(rho, float) else "",
                "HHV [MJ/Nm³]": r["HHV_MJ_Nm3"] if is_c else "",
                "LHV [MJ/Nm³]": r["LHV_MJ_Nm3"] if is_c else "",
                "理論空気量 [Nm³/Nm³]": r["theoretical_air_Nm3"] if is_c else "",
                "理論排ガス量 [Nm³/Nm³]": r["exhaust_total_Nm3"] if is_c else "",
                "排ガスCO2 [%]": exh.get("CO2", "") if is_c else "",
                "排ガスH2O [%]": exh.get("H2O", "") if is_c else "",
                "排ガスO2 [%]":  exh.get("O2",  "") if is_c else "",
                "排ガスSO2 [%]": exh.get("SO2", "") if is_c else "",
                "排ガスN2 [%]":  exh.get("N2",  "") if is_c else "",
                "断熱火炎温度 [℃]": r["T_adiabatic_C"] if is_c else "",
                "可燃性": "○" if is_c else "×",
                "備考": ("自己供給酸化剤" if formula == "O2" else
                         "希釈成分" if formula in ("N2", "CO2", "Ar", "He", "H2O") else ""),
            })
        pd.DataFrame(rows_comp).to_excel(writer, sheet_name="成分別燃焼特性", index=False)

        # --- トータルシート ---
        t = result["total"]
        exh_t = t.get("exhaust_composition", {})
        rows_total = [{
            "ガス名":          gas_name,
            "合計密度 [kg/Nm³]": round(rho_mix, 5),
            "HHV [MJ/Nm³]":   t["HHV_MJ_Nm3"],
            "LHV [MJ/Nm³]":   t["LHV_MJ_Nm3"],
            "可燃成分モル分率": t["combustible_frac"],
            "自己供給O2 [Nm³/Nm³]": t.get("o2_self_supplied_Nm3", 0.0),
            "理論空気量(外部追加分) [Nm³/Nm³]": t["theoretical_air_Nm3"],
            "実空気量 [Nm³/Nm³]": t["actual_air_Nm3"],
            "理論排ガス量 [Nm³/Nm³]": t["exhaust_total_Nm3"],
            "排ガスCO2 [%]":  exh_t.get("CO2", ""),
            "排ガスH2O [%]":  exh_t.get("H2O", ""),
            "排ガスO2 [%]":   exh_t.get("O2",  ""),
            "排ガスSO2 [%]":  exh_t.get("SO2", ""),
            "排ガスN2 [%]":   exh_t.get("N2",  ""),
            "排ガスAr [%]":   exh_t.get("Ar",  ""),
            "排ガスHe [%]":   exh_t.get("He",  ""),
            "断熱火炎温度 [℃]": t.get("T_adiabatic_C", ""),
        }]
        pd.DataFrame(rows_total).to_excel(writer, sheet_name="トータル燃焼特性", index=False)

        # --- サーマルNOxシート（nox_result が渡された場合） ---
        if nox_result:
            _write_nox_sheet(writer, nox_result)

    return output_path


def _write_nox_sheet(writer, nr: dict):
    """サーマルNOx結果シートを書き込む"""
    rows = [
        # ── 入力パラメータ ──
        {"項目": "【入力パラメータ】",       "値": "",                       "単位": ""},
        {"項目": "ガス瞬時流量",             "値": nr.get("Q_Nm3h"),         "単位": "Nm³/h"},
        {"項目": "燃焼噴出径",               "値": nr.get("D_burner_mm"),    "単位": "mm"},
        {"項目": "想定火炎長",               "値": nr.get("L_flame_m"),      "単位": "m"},
        {"項目": "空気過剰率 λ",             "値": nr.get("lambda"),         "単位": "-"},
        {"項目": "初期温度",                  "値": nr.get("T_init_C"),       "単位": "℃"},
        {"項目": "初期圧力",                  "値": nr.get("P_kPa"),          "単位": "kPa"},
        {"項目": "",                          "値": "",                       "単位": ""},
        # ── 火炎特性 ──
        {"項目": "【火炎特性】",              "値": "",                       "単位": ""},
        {"項目": "燃料噴出速度",              "値": nr.get("v_fuel_ms"),      "単位": "m/s"},
        {"項目": "推定火炎滞留時間",           "値": nr.get("tau_ms"),         "単位": "ms"},
        {"項目": "断熱火炎温度",              "値": nr.get("T_adiabatic_C"),  "単位": "℃"},
        {"項目": "",                          "値": "",                       "単位": ""},
        # ── NOx推定値 ──
        {"項目": "【サーマルNOx推定値】",     "値": "",                       "単位": ""},
        {"項目": "NOx（Zeldovich推定）",      "値": nr.get("NOx_thermal_ppm"), "単位": "ppm"},
        {"項目": "NOx（Zeldovich推定）",      "値": nr.get("NOx_thermal_mg_Nm3"), "単位": "mg/Nm³"},
        {"項目": "NOx（Cantera平衡上限）",    "値": nr.get("NOx_equilibrium_ppm"), "単位": "ppm"},
        {"項目": "NO（Cantera平衡）",         "値": nr.get("NO_equilibrium_ppm"),  "単位": "ppm"},
        {"項目": "",                          "値": "",                       "単位": ""},
        # ── 計算手法・注意事項 ──
        {"項目": "計算手法",                  "値": nr.get("method", ""),    "単位": ""},
        {"項目": "注意事項",
         "値": " / ".join(nr.get("warnings", [])) or "なし",
         "単位": ""},
        {"項目": "",                          "値": "",                       "単位": ""},
        {"項目": "【注記】",                  "値": "", "単位": ""},
        {"項目": "Zeldovich推定値",
         "値": "拡張Zeldovich機構（Cantera平衡でO/OHラジカル取得）による積分推定値。"
               "実際の火炎形状・乱流・燃料希釈等の影響は考慮していません。",
         "単位": ""},
        {"項目": "Cantera平衡上限",
         "値": "十分長い滞留時間での理論上限。実際のNOxはこの値を下回ります。",
         "単位": ""},
        {"項目": "mg/Nm³換算",
         "値": "NO分子量30 g/mol、0℃ 101.325kPa基準（1ppm = 1.338 mg/Nm³）",
         "単位": ""},
    ]
    pd.DataFrame(rows).to_excel(writer, sheet_name="サーマルNOx", index=False)
