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
                                composition: dict, output_path: str = None) -> str:
    """燃焼特性計算結果を Excel に出力"""
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

    return output_path
