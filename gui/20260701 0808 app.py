# gui/app_with_mixture.py
# 【完全統合版】完全な計算機能 + 混合ガスUI

import os
import sys
import logging
import threading
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import pandas as pd

from core.calculator import calculate_10steps_iso5167
from core.constants import SGP_DIAMETERS, Z_MODEL_INFO
from core.gas_database import (
    get_available_gases,
    get_component_list,
    get_preset_mixtures,
    validate_composition,
    create_custom_mixture,
    get_mixture_composition,
)

from utils.excel_export import export_to_excel
from tksheet import Sheet
from utils.uncertainty_calculator_iso import add_iso_uncertainty_columns


# ---------------------------------------------------------------
# ログ設定
#   --windowed（コンソール無し）の EXE では標準出力が存在しないため、
#   計算経過やエラーは print() ではなく logging 経由でファイルへ出す。
#   sys.stdout / sys.stderr の状態に左右されないため、
#   PyInstaller の --windowed ビルドでも安全に動作する。
# ---------------------------------------------------------------
def _get_log_path() -> str:
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, "orifice_calc.log")


logger = logging.getLogger("orifice_calc")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    try:
        _handler = logging.FileHandler(_get_log_path(), encoding="utf-8")
    except Exception:
        _handler = logging.NullHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(_handler)




MATERIAL_OPTIONS = [
    "SGP", "STPG", "STKM",
    "SUS304", "SUS316", "SUS310S",
    "銅", "真鍮", "アルミ",
    "SS400", "FKM", "PE", "POM"
]


def _export_combustion_to_excel(result, gas_name, composition, mixture_sl_cm_s=None):
    """燃焼特性の Excel 出力（モジュールレベルヘルパー）"""
    import tkinter.filedialog as fd
    import tkinter.messagebox as mb
    from datetime import datetime
    from utils.excel_export import export_combustion_to_excel

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = fd.asksaveasfilename(
        title="燃焼特性 Excel 保存",
        initialfile=f"combustion_{ts}.xlsx",
        defaultextension=".xlsx",
        filetypes=[("Excel files", "*.xlsx")],
    )
    if not path:
        return
    try:
        export_combustion_to_excel(result, gas_name, composition, path,
                                    mixture_sl_cm_s=mixture_sl_cm_s)
        mb.showinfo("完了", f"保存しました:\n{path}")
    except Exception as e:
        mb.showerror("エラー", str(e))


class OrificeCalculatorApp:
    """完全機能 + 混合ガス対応版"""

    def __init__(self, root):
        self.root = root
        self.root.title("オリフィス計算（完全機能・混合ガス対応版）")
        self.root.geometry("900x980")

        # 結果保持
        self.df_result = None
        self.correction_info = None

        self.df_iso = None
        self.df_jis = None
        self.df_asme = None

        self.corr_iso = None
        self.corr_jis = None
        self.corr_asme = None
        
        # 混合ガス関連
        self.fluid_mode_var = tk.StringVar(value="single")
        self.current_gas_name = None
        self.current_mixture_props = None
        self.current_custom_composition = None  # カスタム組成を確実に保持するための変数

        self._build_ui()

    # ---------------------------------------------------------
    # GUI 構築
    # ---------------------------------------------------------
    def _build_ui(self):
        frame = ttk.LabelFrame(self.root, text="入力条件")
        frame.pack(fill="x", padx=10, pady=10)

        # --- 流体選択方式（ラジオボタン）---
        ttk.Label(frame, text="流体選択:").grid(row=0, column=0, sticky="e", padx=5)
        
        fluid_frame = ttk.Frame(frame)
        fluid_frame.grid(row=0, column=1, columnspan=2, sticky="w", padx=5)
        
        ttk.Radiobutton(fluid_frame, text="単一ガス", variable=self.fluid_mode_var, 
                       value="single", command=self._on_fluid_mode_change).pack(side="left", padx=5)
        ttk.Radiobutton(fluid_frame, text="カスタム混合", variable=self.fluid_mode_var, 
                       value="custom", command=self._on_fluid_mode_change).pack(side="left", padx=5)

        # --- ガス選択 ---
        ttk.Label(frame, text="流体:").grid(row=1, column=0, sticky="e", padx=5)
        self.gas_var = tk.StringVar(value="空気")
        self.gas_combo = ttk.Combobox(
            frame,
            textvariable=self.gas_var,
            width=30,
            state="readonly"
        )
        self.gas_combo.grid(row=1, column=1, columnspan=2, padx=5, pady=5)
        self.gas_combo.bind("<<ComboboxSelected>>", self._on_gas_selected)
        
        # 混合ガス情報表示
        self.mixture_info_label = ttk.Label(frame, text="", foreground="blue")
        self.mixture_info_label.grid(row=1, column=3, sticky="w", padx=10)
        
        self._update_gas_combo()

        # 配管材質
        ttk.Label(frame, text="配管材質").grid(row=2, column=0, sticky="e", padx=5)
        self.pipe_mat_var = tk.StringVar(value="SGP")
        self.pipe_mat_combo = ttk.Combobox(
            frame,
            textvariable=self.pipe_mat_var,
            values=MATERIAL_OPTIONS,
            state="readonly",
            width=12
        )
        self.pipe_mat_combo.grid(row=2, column=1, sticky="w")

        # プレート材質
        ttk.Label(frame, text="プレート材質").grid(row=3, column=0, sticky="e", padx=5)
        self.plate_mat_var = tk.StringVar(value="SUS304")
        self.plate_mat_combo = ttk.Combobox(
            frame,
            textvariable=self.plate_mat_var,
            values=MATERIAL_OPTIONS,
            state="readonly",
            width=12
        )
        self.plate_mat_combo.grid(row=3, column=1, sticky="w")

        # --- SGP 呼び径 ---
        ttk.Label(frame, text="配管口径 (SGP):").grid(row=1, column=3, sticky="e", padx=5)
        self.pipe_size_var = tk.StringVar(value="SGP 50A 2B")
        pipe_combo = ttk.Combobox(
            frame,
            textvariable=self.pipe_size_var,
            values=list(SGP_DIAMETERS.keys()),
            width=20,
            state="readonly",
        )
        pipe_combo.grid(row=1, column=4, padx=5, pady=5)
        pipe_combo.bind("<<ComboboxSelected>>", self._on_pipe_size)

        # --- 寸法 ---
        ttk.Label(frame, text="内径D[mm]:").grid(row=2, column=3, sticky="e", padx=5)
        self.D_var = tk.DoubleVar(value=52.9)
        self.D_entry = ttk.Entry(frame, textvariable=self.D_var, width=10, font=("Arial", 11))
        self.D_entry.grid(row=2, column=4, padx=5, pady=5)
        self.D_entry.bind("<KeyRelease>", self._on_D_changed)

        ttk.Label(frame, text="孔径d[mm]:").grid(row=3, column=3, sticky="e", padx=5)
        self.d_var = tk.DoubleVar(value=13.0)
        self.d_entry = ttk.Entry(frame, textvariable=self.d_var, width=10, font=("Arial", 11))
        self.d_entry.grid(row=3, column=4, padx=5, pady=5)
        self.d_entry.bind("<KeyRelease>", self._on_D_changed)

        # 入力値確認表示
        self.label_input_display = ttk.Label(frame, text="", foreground="blue", 
                                             font=("Arial", 10, "bold"), background="lightyellow")
        self.label_input_display.grid(row=4, column=3, columnspan=2, sticky="ew", padx=5, pady=5)

        # --- 圧力・温度 ---
        ttk.Label(frame, text="上流圧力P1[kPa]:").grid(row=4, column=0, sticky="e", padx=5)
        self.P1_var = tk.DoubleVar(value=111.3)
        self.P1_entry = ttk.Entry(frame, textvariable=self.P1_var, width=10, font=("Arial", 11))
        self.P1_entry.grid(row=4, column=1, padx=5, pady=5)

        ttk.Label(frame, text="最大差圧ΔP[kPa]:").grid(row=5, column=0, sticky="e", padx=5)
        self.deltaP_var = tk.DoubleVar(value=10.0)
        self.deltaP_entry = ttk.Entry(frame, textvariable=self.deltaP_var, width=10, font=("Arial", 11))
        self.deltaP_entry.grid(row=5, column=1, padx=5, pady=5)

        ttk.Label(frame, text="温度t[℃]:").grid(row=6, column=0, sticky="e", padx=5)
        self.T_var = tk.DoubleVar(value=20.0)
        self.T_entry = ttk.Entry(frame, textvariable=self.T_var, width=10, font=("Arial", 11))
        self.T_entry.grid(row=6, column=1, padx=5, pady=5)

        # --- Zモデル ---
        ttk.Label(frame, text="Zモデル(密度算出式):").grid(row=5, column=3, sticky="e", padx=5)
        self.z_model_var = tk.StringVar(value="HEOS")
        z_combo = ttk.Combobox(
            frame,
            textvariable=self.z_model_var,
            values=["HEOS", "理想気体"],
            width=20,
            state="readonly",
        )
        z_combo.grid(row=5, column=4, padx=5, pady=5)

        # --- ボタン ---
        button_frame = ttk.Frame(frame)
        button_frame.grid(row=6, column=3, columnspan=2, pady=10)
        ttk.Button(button_frame, text="10点計算実行", command=self.run_calculation).pack(side="left", padx=5)
        ttk.Button(button_frame, text="入力値リセット", command=self._reset_inputs).pack(side="left", padx=5)
        ttk.Button(button_frame, text="Excel 出力", command=self.export_excel).pack(side="left", padx=5)
        ttk.Button(button_frame, text="🔥 燃焼特性", command=self.show_combustion).pack(side="left", padx=5)

        # --- 表表示 ---
        self.table_frame = ttk.Frame(self.root)
        self.table_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.tree = None
        self.df_result = None

        # --- テキスト表示（不確かさレポート等） ---
        #self.text = tk.Text(self.root, height=20)
        #self.text.pack(fill="both", expand=True, padx=10, pady=10)

        self._update_input_display()

    # ---------------------------------------------------------
    # 混合ガス関連メソッド
    # ---------------------------------------------------------
    def _on_fluid_mode_change(self):
        """流体選択方式が変更された"""
        self._update_gas_combo()
        # カスタム混合はトグル選択と同時にダイアログを開く
        if self.fluid_mode_var.get() == "custom":
            self.root.after(100, self._create_custom_mixture)

    def _update_gas_combo(self):
        """ガスComboboxを更新"""
        from core.gas_database import GAS_DATABASE
        mode = self.fluid_mode_var.get()

        if mode == "single":
            # 純物質 + 空気のみ（13A・LPGなどプリセット混合は除外）
            single_names = ["空気"] + [
                n for n, v in GAS_DATABASE.items()
                if not v.get("is_mixture")
            ]
            self.gas_combo["values"] = single_names
            self.gas_var.set("空気")
            self.mixture_info_label.config(text="")

        elif mode == "custom":
            # カスタム混合（ダイアログで作成）
            self.gas_combo["values"] = ["カスタム混合ガス"]
            self.gas_var.set("カスタム混合ガス")
            self.mixture_info_label.config(text="←「カスタム混合ガス作成」を選択してください",
                                           foreground="gray")
    
    def _on_gas_selected(self, event=None):
        """ガスが選択された"""
        gas_name = self.gas_var.get()
        
        if self.fluid_mode_var.get() == "custom" and "カスタム混合" in gas_name:
            self._create_custom_mixture()
            return
        
        self.current_gas_name = gas_name
        self._update_mixture_info()
    
    def _update_mixture_info(self):
        """混合ガス情報を表示"""
        mode = self.fluid_mode_var.get()
        gas_name = self.current_gas_name or self.gas_var.get()
        
        if mode == "preset":
            comp = get_mixture_composition(gas_name)
            if comp:
                comp_str = ", ".join([f"{k}:{v*100:.1f}%" for k, v in list(comp.items())[:3]])
                self.mixture_info_label.config(
                    text=f"組成: {comp_str}...", 
                    foreground="blue"
                )
    
    def _create_custom_mixture(self):
        """カスタム混合ガスを作成（全18成分・リアルタイム合計・プリセット読込）"""
        from core.gas_database import (COMPONENT_DATABASE, get_mixture_names,
                                       get_mixture_composition)
        dialog = tk.Toplevel(self.root)
        dialog.title("カスタム混合ガス作成")
        dialog.resizable(False, True)

        # ── オリフィスGUI左隣に配置し、移動に追従 ──
        def _place_dialog():
            self.root.update_idletasks()
            mx = self.root.winfo_x()
            my = self.root.winfo_y()
            dialog.geometry(f"340x640+{mx - 340 - 4}+{my}")

        def _follow_dialog(event=None):
            if not dialog.winfo_exists():
                return
            mx = self.root.winfo_x()
            my = self.root.winfo_y()
            dh = dialog.winfo_height()
            dialog.geometry(f"340x{dh}+{mx - 340 - 4}+{my}")

        _place_dialog()
        self.root.bind("<Configure>", _follow_dialog)
        dialog.protocol("WM_DELETE_WINDOW",
                        lambda: [self.root.unbind("<Configure>"), dialog.destroy()])

        dialog.grab_set()

        # タイトル
        ttk.Label(dialog, text="成分と組成（モル%）を入力",
                  font=("", 10, "bold")).pack(pady=(8, 2))

        # プリセット読込
        pf = ttk.Frame(dialog)
        pf.pack(fill="x", padx=10, pady=(0, 2))
        ttk.Label(pf, text="プリセット読込:").pack(side="left")
        preset_var = tk.StringVar()
        pcb = ttk.Combobox(pf, textvariable=preset_var,
                           values=get_mixture_names(), width=18, state="readonly")
        pcb.pack(side="left", padx=4)

        # リアルタイム合計ラベル
        total_var = tk.StringVar(value="合計: 0.0 %")
        total_lbl = ttk.Label(dialog, textvariable=total_var,
                              font=("", 9, "bold"), foreground="gray")
        total_lbl.pack()

        # スクロール可能フレーム
        outer = ttk.Frame(dialog)
        outer.pack(fill="both", expand=True, padx=8, pady=2)
        cv = tk.Canvas(outer, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=cv.yview)
        frm = ttk.Frame(cv)
        frm.bind("<Configure>",
                 lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.create_window((0, 0), window=frm, anchor="nw")
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        cv.bind_all("<MouseWheel>",
                    lambda e: cv.yview_scroll(-1*(e.delta//120), "units"))

        # ヘッダ
        ttk.Label(frm, text="成分", font=("", 9, "bold"),
                  width=20, anchor="e").grid(row=0, column=0, padx=(6,2), pady=2)
        ttk.Label(frm, text="モル%", font=("", 9, "bold"),
                  width=8).grid(row=0, column=1, padx=(2,6), pady=2)

        components = get_component_list()
        entries: dict = {}

        def _update_total(*_):
            t = sum(v.get() for v in entries.values())
            total_var.set(f"合計: {t:.1f} %")
            color = "darkgreen" if 99.0 <= t <= 101.0 else (
                    "darkorange" if t > 0 else "gray")
            total_lbl.configure(foreground=color)

        for i, comp in enumerate(components, start=1):
            jp = COMPONENT_DATABASE.get(comp, {}).get("name", comp)
            ttk.Label(frm, text=f"{jp} ({comp})",
                      anchor="e", width=22).grid(row=i, column=0, padx=(6,2), pady=3)
            var = tk.DoubleVar(value=0.0)
            var.trace_add("write", _update_total)
            entries[comp] = var
            ttk.Entry(frm, textvariable=var, width=9,
                      justify="right").grid(row=i, column=1, padx=(2,6), pady=3)

        # プリセット読込処理
        def _load_preset(*_):
            name = preset_var.get()
            if not name:
                return
            comp = get_mixture_composition(name)
            if not comp:
                return
            for f, var in entries.items():
                var.set(round(comp.get(f, 0) * 100, 2))
        pcb.bind("<<ComboboxSelected>>", _load_preset)

        # ボタン
        bf = ttk.Frame(dialog)
        bf.pack(fill="x", padx=8, pady=(4, 8))

        def _create():
            raw = {c: v.get() for c, v in entries.items() if v.get() > 0}
            if not raw:
                messagebox.showerror("エラー", "少なくとも1つの成分を入力してください")
                return
            total = sum(raw.values())
            if not (99.0 <= total <= 101.0):
                messagebox.showerror(
                    "エラー",
                    f"組成の合計が100%になるように入力してください。\n現在の合計: {total:.1f}%")
                return
            comp_frac = {c: v / total for c, v in raw.items()}
            mixture = create_custom_mixture(comp_frac, "カスタム混合ガス")
            if mixture:
                self.current_mixture_props      = mixture
                self.current_custom_composition = comp_frac
                self.current_gas_name           = "カスタム混合ガス"
                self.gas_combo.set("カスタム混合ガス")
                self.mixture_info_label.config(
                    text=f"M={mixture.get('M',0):.3f} g/mol, κ={mixture.get('kappa',0):.4f}",
                    foreground="darkgreen")
                self.root.unbind("<Configure>")
                dialog.destroy()

        ttk.Button(bf, text="作成", command=_create).pack(
            side="left", expand=True, padx=6)
        ttk.Button(bf, text="キャンセル", command=dialog.destroy).pack(
            side="left", expand=True, padx=6)

    # ---------------------------------------------------------
    # イベントハンドラ（既存）
    # ---------------------------------------------------------
    def _on_pipe_size(self, event=None):
        size = self.pipe_size_var.get()
        D = SGP_DIAMETERS.get(size)
        if D is not None:
            self.D_var.set(D)
            self.D_entry.delete(0, tk.END)
            self.D_entry.insert(0, str(D))
            self._on_D_changed()

    def _on_D_changed(self, event=None):
        try:
            D = self.D_var.get()
            d = self.d_var.get()
            
            if D > 0 and d > 0 and d < D:
                beta = d / D
                msg = f"✓ D={D:.2f}mm  |  d={d:.2f}mm  |  β={beta:.5f}"
                self.label_input_display.config(text=msg, foreground="darkgreen")
            else:
                self.label_input_display.config(text="⚠ 入力値が不正", foreground="orange")
        except:
            pass

    def _update_input_display(self):
        self._on_D_changed()
    
    def _reset_inputs(self):
        self.D_var.set(52.9)
        self.d_var.set(13.0)
        self.P1_var.set(111.3)
        self.deltaP_var.set(10.0)
        self.T_var.set(20.0)
        self._update_input_display()
        messagebox.showinfo("完了", "入力値をリセットしました")

    # ---------------------------------------------------------
    # 計算実行（混合ガス対応）
    # ---------------------------------------------------------
    def run_calculation(self):
        try:
            gas_name = self.current_gas_name or self.gas_var.get()
            D_mm = self.D_var.get()
            d_mm = self.d_var.get()
            P1_kPa = self.P1_var.get()
            max_deltaP_kPa = self.deltaP_var.get()
            T_degC = self.T_var.get()
            z_model_name = self.z_model_var.get()

            if D_mm <= 0 or d_mm <= 0 or d_mm >= D_mm:
                messagebox.showerror("入力エラー", "D と d の値が不正です")
                return

            mixture_composition = None
            mode = self.fluid_mode_var.get()
            
            if mode == "preset":
                mixture_composition = get_mixture_composition(gas_name)
            elif mode == "custom":
                # カスタム作成画面で確保した分数を渡す
                if self.current_custom_composition:
                    mixture_composition = self.current_custom_composition
                elif self.current_mixture_props and isinstance(self.current_mixture_props, dict):
                    mixture_composition = self.current_mixture_props.get('composition')

            logger.info("=" * 70)
            logger.info(f"【計算開始】流体: {gas_name}")
            logger.info(f"D={D_mm}mm, d={d_mm}mm, β={d_mm/D_mm:.4f}")
            if mixture_composition:
                logger.info(f"組成: {', '.join([f'{k}:{v*100:.1f}%' for k, v in list(mixture_composition.items())])}")
            logger.info("=" * 70)

            # ---------------------------------------------------------
            # ISO 計算
            # ---------------------------------------------------------
            logger.info("ISO 計算実行中...")
            df_iso, corr_iso, _, msg_iso = calculate_10steps_iso5167(
                gas_name, D_mm, d_mm, "SUS304", "SGP",
                P1_kPa, max_deltaP_kPa, T_degC, z_model_name,
                include_uncertainty=True, mode="ISO_RHG",
                mixture_composition=mixture_composition
            )

            if df_iso is None:
                logger.warning(f"ISO 計算で問題発生: {msg_iso}")
                cols = [
                    "差圧[kPa]", "流出係数C", "膨張補正係数ε",
                    "体積流量[m³/h]", "ノルマル流量[Nm³/h]",
                    "レイノルズ数Re", "密度ρ[kg/m³]", "圧縮係数Z",
                    "β", "補正後D[mm]", "補正後d[mm]", "計算モード",
                ]
                df_iso = pd.DataFrame([{c: None for c in cols} for _ in range(10)])
                corr_iso = {}

            df_iso["内径D[mm]"] = D_mm
            df_iso["孔径d[mm]"] = d_mm
            df_iso = self._ensure_z_column(df_iso, corr_iso, z_model_name)
            df_iso = add_iso_uncertainty_columns(df_iso)

            # ---------------------------------------------------------
            # JIS 計算
            # ---------------------------------------------------------
            logger.info("JIS 計算実行中...")
            df_jis, corr_jis, _, msg_jis = calculate_10steps_iso5167(
                gas_name, D_mm, d_mm, "SUS304", "SGP",
                P1_kPa, max_deltaP_kPa, T_degC, z_model_name,
                include_uncertainty=False, mode="JIS_Z8762",
                mixture_composition=mixture_composition
            )

            if df_jis is None:
                cols = [
                    "差圧[kPa]", "流出係数C", "膨張補正係数ε",
                    "体積流量[m³/h]", "ノルマル流量[Nm³/h]",
                    "レイノルズ数Re", "密度ρ[kg/m³]", "圧縮係数Z",
                    "β", "補正後D[mm]", "補正後d[mm]", "計算モード",
                ]
                df_jis = pd.DataFrame([{c: None for c in cols} for _ in range(10)])
                corr_jis = {}

            df_jis["内径D[mm]"] = D_mm
            df_jis["孔径d[mm]"] = d_mm
            df_jis = self._ensure_z_column(df_jis, corr_jis, z_model_name)

            # ---------------------------------------------------------
            # ASME 計算
            # ---------------------------------------------------------
            logger.info("ASME 計算実行中...")
            df_asme, corr_asme, _, msg_asme = calculate_10steps_iso5167(
                gas_name, D_mm, d_mm, "SUS304", "SGP",
                P1_kPa, max_deltaP_kPa, T_degC, z_model_name,
                include_uncertainty=False, mode="ASME_MFC14M",
                mixture_composition=mixture_composition
            )

            if df_asme is None:
                cols = [
                    "差圧[kPa]", "流出係数C", "膨張補正係数ε",
                    "体積流量[m³/h]", "ノルマル流量[Nm³/h]",
                    "レイノルズ数Re", "密度ρ[kg/m³]", "圧縮係数Z",
                    "β", "補正後D[mm]", "補正後d[mm]", "計算モード",
                ]
                df_asme = pd.DataFrame([{c: None for c in cols} for _ in range(10)])
                corr_asme = {}

            df_asme["内径D[mm]"] = D_mm
            df_asme["孔径d[mm]"] = d_mm
            df_asme = self._ensure_z_column(df_asme, corr_asme, z_model_name)

            # ---------------------------------------------------------
            # 保存と表示構築
            # ---------------------------------------------------------
            self.df_iso = df_iso
            self.df_jis = df_jis
            self.df_asme = df_asme
            self.corr_iso = corr_iso
            self.corr_jis = corr_jis
            self.corr_asme = corr_asme
            self.correction_info = corr_iso

            rows = []

            def _append_block(df, mode_key, label):
                if df is None or df.empty:
                    rows.append({"規格": label, "適合": "×", "備考": "計算結果なし", "差圧[kPa]": None})
                    return

                valid_mask = pd.to_numeric(df.get("差圧[kPa]"), errors="coerce").notnull()
                
                if not valid_mask.any():
                    rows.append({"規格": label, "適合": "×", "備考": "計算不能（物性値や条件を確認してください）", "差圧[kPa]": None})
                    return
                
                df_local = df[valid_mask].copy()

                for _, r in df_local.iterrows():
                    row = r.to_dict()
                    note = self._make_note(
                        mode_key,
                        row.get("β"), row.get("補正後D[mm]"),
                        row.get("レイノルズ数Re"), row.get("圧縮係数Z"),
                        row.get("流出係数C"), row.get("膨張補正係数ε"),
                        row.get("体積流量[m³/h]")
                    )
                    fit_mark = "○" if ("適用範囲内" in note) else "×"
                    row_ordered = {
                        "規格": label,
                        "適合": fit_mark,
                        "備考": note,
                    }
                    row_ordered.update(row)
                    rows.append(row_ordered)

            _append_block(df_iso, "ISO_RHG", "ISO 5167 RHG完全式")
            _append_block(df_jis, "JIS_Z8762", "JIS Z 8762:1995")
            _append_block(df_asme, "ASME_MFC14M", "ASME MFC-14M")

            COLUMN_ORDER = [
                "規格", "適合", "備考",
                "差圧[kPa]", "流出係数C", "膨張補正係数ε",
                "体積流量[m³/h]", "ノルマル流量[Nm³/h]",
                "レイノルズ数Re", "密度ρ[kg/m³]", "圧縮係数Z", "Zモデル",
                "β", "補正後D[mm]", "補正後d[mm]",
                #"計算モード", "永久圧力損失[Pa]", 
                "永久圧力損失[kPa]",
                #"永久圧力損失比ΔPperm/ΔP",
            ]

            df_all = pd.DataFrame(rows)
            df_display = df_all.reindex(columns=COLUMN_ORDER).reset_index(drop=True)

            # ---------------------------------------------------------
            # GUI構築（スクロールバーの端固定問題を解消）
            # ---------------------------------------------------------
            for widget in self.table_frame.winfo_children():
                widget.destroy()

            # コンテナを使って layout を制御
            tree_container = ttk.Frame(self.table_frame)
            tree_container.pack(fill="both", expand=True)

            # Treeview とスクロールバー
            tree = ttk.Treeview(tree_container, columns=COLUMN_ORDER, show="headings", height=15)
            vsb = ttk.Scrollbar(tree_container, orient="vertical", command=tree.yview)
            hsb = ttk.Scrollbar(tree_container, orient="horizontal", command=tree.xview)

            # grid を使用して厳密に配置
            tree.grid(row=0, column=0, sticky="nsew")
            vsb.grid(row=0, column=1, sticky="ns")
            hsb.grid(row=1, column=0, sticky="ew")

            tree_container.grid_columnconfigure(0, weight=1)
            tree_container.grid_rowconfigure(0, weight=1)

            tree.configure(yscroll=vsb.set, xscroll=hsb.set)

            # 列幅の強制固定 (すべての列を50に)
            for c in COLUMN_ORDER:
                tree.heading(c, text=c)
                tree.column(c, width=50, anchor="center", stretch=False)
                
            # タグの設定（赤色の定義）
            # Windows の ttk "vista" テーマはタグ foreground を無視するため
            # "clam" か "default" で上書きしてから tag_configure する
            _style = ttk.Style()
            try:
                _style.theme_use("clam")
            except Exception:
                pass
            tree.tag_configure("ok", foreground="black")
            tree.tag_configure("ng", foreground="red")

            # データ挿入
            for row in df_display.itertuples(index=False):
                values = ["-" if pd.isnull(x) else x for x in row]

                # 「適合」列 (index 1) が "×" なら ng
                tag = "ng" if str(values[1]) == "×" else "ok"

                tree.insert("", "end", values=values, tags=(tag,))



            
            self.tree = tree
            self.df_result = df_display

        except Exception as e:
            logger.exception("計算中にエラーが発生しました")
            messagebox.showerror("エラー", f"計算中にエラーが発生しました:\n{e}\n\n詳細は orifice_calc.log を確認してください。")
            return

    # ---------------------------------------------------------
    # ユーティリティ
    # ---------------------------------------------------------
    def _ensure_z_column(self, df: pd.DataFrame, corr: dict, z_model_name: str) -> pd.DataFrame:
        if df is None:
            return df

        # HEOS の場合：可燃成分を含む混合ガスのみ "GERG-2008"、それ以外は "HEOS"
        display_name = z_model_name
        if z_model_name == "HEOS":
            try:
                from core.combustion import COMBUSTIBLE_FORMULAS
                from core.gas_database import GAS_DATABASE

                mode = self.fluid_mode_var.get()
                comp = None

                if mode == "custom":
                    comp = getattr(self, "current_custom_composition", None)
                else:
                    gas = GAS_DATABASE.get(self.gas_var.get(), {})
                    comp = gas.get("composition")   # None なら単独ガス

                # 可燃成分が 1 種でも含まれれば GERG-2008
                if comp and any(f in COMBUSTIBLE_FORMULAS for f in comp):
                    display_name = "GERG-2008"
                else:
                    display_name = "HEOS"   # 単独ガス・不燃混合は HEOS のまま
            except Exception:
                display_name = "HEOS"

        try:
            df["Zモデル"] = display_name
        except Exception:
            df["Zモデル"] = [display_name] * len(df)

        if "圧縮係数Z" not in df.columns:
            z_from_corr = None
            try:
                if corr and isinstance(corr, dict):
                    z_from_corr = corr.get("圧縮係数Z") or corr.get("Z")
            except Exception:
                z_from_corr = None

            if z_from_corr is not None:
                try:
                    df["圧縮係数Z"] = float(z_from_corr)
                except Exception:
                    df["圧縮係数Z"] = [z_from_corr] * len(df)
            else:
                df["圧縮係数Z"] = [None] * len(df)

        return df

    def _make_note(self, mode, beta, D, Re, Z, C, epsilon, Qv):
        notes = []

        if Z is None or pd.isnull(Z):
            notes.append("Z が計算できません")
        if C is None or pd.isnull(C):
            notes.append("流出係数Cが計算不能")
        if epsilon is None or pd.isnull(epsilon):
            notes.append("膨張補正係数εが計算不能")
        if Qv is None or pd.isnull(Qv):
            notes.append("流量Qvが計算不能")

        if mode == "ISO_RHG":
            if not (0.1 <= beta <= 0.75):
                notes.append("β が ISO の適用範囲外 (0.1〜0.75)")
            if not (50 <= D <= 1000):
                notes.append("D が ISO の適用範囲外 (50〜1000mm)")
            if Re is None or pd.isnull(Re) or Re < 5000:
                notes.append("Re < 5000 (ISO 下限)")

        elif mode == "ASME_MFC14M":
            if not (0.1 <= beta <= 0.75):
                notes.append("β が ASME の適用範囲外 (0.1〜0.75)")
            if not (12 <= D <= 40):
                notes.append("D が ASME MFC-14M-2003 の適用範囲外 (12〜40mm)")
            if Re is None or pd.isnull(Re) or Re < 5000:
                notes.append("Re < 5000 (ASME 下限)")

        elif mode == "JIS_Z8762":
            if not (0.2 <= beta <= 0.75):
                notes.append("β が JIS の適用範囲外 (0.2〜0.75)")
            if not (50 <= D <= 1000):
                notes.append("D が JIS の適用範囲外 (50〜1000mm)")
            if Re is None or pd.isnull(Re) or Re < 5000:
                notes.append("Re < 5000 (JIS 下限)")

        if len(notes) == 0:
            return "適用範囲内"
        else:
            return " / ".join(notes)

    def show_combustion(self):
        """燃焼特性ウィンドウを表示（T/P/λ 設定付き）"""
        try:
            from core.combustion import (
                calc_mixture_combustion,
                get_literature_burning_velocity,
                calc_mixture_burning_velocity,
            )
            from core.gas_database import COMPONENT_DATABASE
        except ImportError as e:
            messagebox.showerror("エラー", f"Cantera が必要です:\npip install cantera\n\n{e}")
            return

        # ── 入力条件取得 ──
        mode     = getattr(self, "fluid_mode_var", tk.StringVar()).get()
        gas_name = getattr(self, "current_gas_name", "")
        comp = None

        if mode == "custom" and getattr(self, "current_custom_composition", None):
            comp = self.current_custom_composition
        else:
            from core.gas_database import GAS_DATABASE
            props = GAS_DATABASE.get(gas_name, {})
            formula = props.get("formula")
            if formula:
                comp = {formula: 1.0}
            elif props.get("composition"):
                comp = props["composition"]

        if not comp:
            messagebox.showinfo("情報", "ガスを選択してから実行してください")
            return

        # ── ウィンドウ ──
        win = tk.Toplevel(self.root)
        win.title(f"燃焼特性 — {gas_name}")
        win.geometry("960x900")
        win.resizable(True, True)

        # ── 条件入力フレーム（燃焼特性） ──
        cond_frame = ttk.LabelFrame(win, text="計算条件（燃焼特性）")
        cond_frame.pack(fill="x", padx=10, pady=(8, 2))

        ttk.Label(cond_frame, text="温度 [℃]:").grid(row=0, column=0, padx=8, pady=4, sticky="e")
        T_var = tk.DoubleVar(value=0.0)
        ttk.Entry(cond_frame, textvariable=T_var, width=10).grid(row=0, column=1, padx=4)

        ttk.Label(cond_frame, text="絶対圧力 [kPa]:").grid(row=0, column=2, padx=8, sticky="e")
        P_var = tk.DoubleVar(value=101.325)
        ttk.Entry(cond_frame, textvariable=P_var, width=10).grid(row=0, column=3, padx=4)

        ttk.Label(cond_frame, text="空気過剰率 λ:").grid(row=0, column=4, padx=8, sticky="e")
        lam_var = tk.DoubleVar(value=1.0)
        ttk.Entry(cond_frame, textvariable=lam_var, width=8).grid(row=0, column=5, padx=4)

        # ── 結果フレーム ──
        result_frame = ttk.Frame(win)
        result_frame.pack(fill="both", expand=True, padx=10, pady=4)

        # 成分別テーブル
        ttk.Label(result_frame, text="■ 成分別",
                  font=("", 9, "bold")).pack(anchor="w")

        cols = (
            "成分",
            "日本語名",
            "モル[%]",
            "密度[kg/m³]",
            "HHV[MJ/Nm³]",
            "LHV[MJ/Nm³]",
            "理論空気量[Nm³/Nm³]",
            "実空気量[Nm³/Nm³]",
            "排ガス量[Nm³/Nm³]",
            "CO2[%]",
            "H2O[%]",
            "O2[%]",
            "N2[%]",
            "SO2[%]",
            "断熱火炎温度[℃]",
            "最大燃焼速度[cm/s]",
            "φ@最大",
        )

        tree_f = ttk.Frame(result_frame)
        tree_f.pack(fill="x")
        tree = ttk.Treeview(tree_f, columns=cols, show="headings", height=8)
        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, width=82, anchor="center")
        tree.column("成分",    width=70)
        tree.column("日本語名", width=105)
        xsb = ttk.Scrollbar(tree_f, orient="horizontal", command=tree.xview)
        tree.configure(xscrollcommand=xsb.set)
        tree.pack(fill="x")
        xsb.pack(fill="x")

        # トータル
        ttk.Label(result_frame, text="■ トータル",
                  font=("", 9, "bold")).pack(anchor="w", pady=(8,0))
        total_lbl = ttk.Label(result_frame, text="", justify="left",
                              font=("Consolas", 9))
        total_lbl.pack(anchor="w", padx=16)

        # ── 混合ガス全体の層流燃焼速度（重い計算のため明示ボタン操作） ──
        sl_frame = ttk.LabelFrame(result_frame, text="■ 混合ガス全体の燃焼速度")
        sl_frame.pack(fill="x", padx=0, pady=(8, 4))

        sl_result_lbl = ttk.Label(
            sl_frame, justify="left", font=("Consolas", 9),
            text="  未計算（左の「設定条件の空気比λで計算」ボタンを押してください）"
        )
        sl_result_lbl.pack(anchor="w", padx=8, pady=(2, 4))

        def _run_burning_velocity():
            T_K  = T_var.get() + 273.15
            P_Pa = P_var.get() * 1000.0
            lam  = max(lam_var.get(), 0.01)

            sl_btn.config(state="disabled")
            sl_result_lbl.config(
                text="  計算中...（1 次元火炎構造を解くため数十秒〜1 分程度かかります。"
                     "しばらくお待ちください）"
            )

            def worker():
                res = calc_mixture_burning_velocity(
                    comp, lambda_val=lam, T_K=T_K, P_Pa=P_Pa
                )

                def apply_result():
                    sl_btn.config(state="normal")
                    if res["ok"]:
                        win._last_sl_cm_s = res["Sl_cm_s"]
                        sl_result_lbl.config(text=(
                            f"  層流燃焼速度 Sl = {res['Sl_cm_s']:.2f} cm/s"
                            f"　（条件: T={T_var.get():.1f}℃, "
                            f"P={P_var.get():.3f} kPa(abs), λ={lam:.2f}）"
                        ))
                    else:
                        win._last_sl_cm_s = None
                        sl_result_lbl.config(
                            text=f"  計算できませんでした: {res['reason']}"
                        )

                # Tkinter の UI 更新は必ずメインスレッドから行う
                win.after(0, apply_result)

            threading.Thread(target=worker, daemon=True).start()

        sl_btn = ttk.Button(
            sl_frame,
            text="⚠ 設定条件の空気比λで計算（重い処理・数十秒〜1分）",
            command=_run_burning_velocity,
        )
        sl_btn.pack(anchor="w", padx=8, pady=(0, 6))

        def recalc():
            """条件変更時に再計算"""
            T_K  = T_var.get() + 273.15
            P_Pa = P_var.get() * 1000.0
            lam  = max(lam_var.get(), 0.01)

            result = calc_mixture_combustion(comp, lambda_val=lam,
                                             T_K=T_K, P_Pa=P_Pa)
            if not result:
                return

            # テーブル更新
            for row in tree.get_children():
                tree.delete(row)

            for formula, frac in comp.items():
                r = result["components"].get(formula, {})
                exh = r.get("exhaust_composition", {})
                is_c = r.get("is_combustible", False)

                disp_name = COMPONENT_DATABASE.get(formula, {}).get("name", formula)
                if not is_c:
                    if formula == "O2":
                        disp_name += "（自己供給酸化剤）"
                    elif formula in ("N2", "CO2", "Ar", "He", "H2O"):
                        disp_name += "（希釈成分）"

                sl_lit = get_literature_burning_velocity(formula)

                vals = (
                    formula,
                    disp_name,
                    round(comp.get(formula, 0) * 100, 2),
                    f"{r.get('density_kg_m3',''):.5f}" if r.get("density_kg_m3") else "-",
                    f"{r['HHV_MJ_Nm3']:.3f}" if is_c else "-",
                    f"{r['LHV_MJ_Nm3']:.3f}" if is_c else "-",
                    f"{r['theoretical_air_Nm3']:.3f}" if is_c else "-",
                    f"{r['actual_air_Nm3']:.3f}"      if is_c else "-",
                    f"{r['exhaust_total_Nm3']:.3f}"   if is_c else "-",
                    exh.get("CO2","") if is_c else "-",
                    exh.get("H2O","") if is_c else "-",
                    exh.get("O2","")  if is_c else "-",
                    exh.get("N2","")  if is_c else "-",
                    exh.get("SO2","") if is_c else "-",
                    r.get("T_adiabatic_C","") if is_c else "-",
                    sl_lit["sl_max_cm_s"] if sl_lit else "-",
                    sl_lit["phi_at_max"]  if sl_lit else "-",
                )
                tree.insert("", "end", values=vals,
                            tags=("comb" if is_c else "inert",))
            tree.tag_configure("inert", foreground="gray")

            # トータル更新
            t   = result["total"]
            exh = t.get("exhaust_composition", {})
            o2_self = t.get("o2_self_supplied_Nm3", 0.0)
            o2_line = (f"  成分中の自己供給O2: {o2_self:.4f} Nm³/Nm³ "
                       f"（外部空気量から差し引き済み）\n" if o2_self > 0 else "")
            rho_mix = sum(
                frac * result["components"].get(f, {}).get("density_kg_m3", 0.0)
                for f, frac in comp.items()
            )
            total_lbl.config(text=(
                f"  密度: {rho_mix:.5f} kg/Nm³\n"
                f"  HHV: {t['HHV_MJ_Nm3']:.4f} MJ/Nm³    "
                f"LHV: {t['LHV_MJ_Nm3']:.4f} MJ/Nm³\n"
                f"{o2_line}"
                f"  理論空気量(外部追加分): {t['theoretical_air_Nm3']:.4f} Nm³/Nm³    "
                f"実空気量(λ={lam:.2f}): {t['actual_air_Nm3']:.4f} Nm³/Nm³\n"
                f"  排ガス量: {t['exhaust_total_Nm3']:.4f} Nm³/Nm³    "
                f"断熱火炎温度: {t.get('T_adiabatic_C','N/A')} ℃\n"
                f"  排ガス組成: {exh}"
            ))
            win._last_result = result

            # 条件が変わった可能性があるため、燃焼速度の表示は未計算状態に戻す
            # （古い条件での Sl 値が新しい T/P/λ の結果と混在して見えるのを防ぐ）
            win._last_sl_cm_s = None
            sl_result_lbl.config(
                text="  未計算（「設定条件の空気比λで計算」ボタンを押してください）"
            )

        ttk.Button(cond_frame, text="再計算",
                   command=recalc).grid(row=0, column=6, padx=12)

        # Excel 出力
        def _export():
            if hasattr(win, "_last_result"):
                _export_combustion_to_excel(
                    win._last_result, gas_name, comp,
                    mixture_sl_cm_s=getattr(win, "_last_sl_cm_s", None),
                )
        ttk.Button(cond_frame, text="Excel 出力",
                   command=_export).grid(row=0, column=7, padx=12)

        # 初期計算
        recalc()

    def export_excel(self):
        if self.df_result is None:
            messagebox.showwarning("警告", "先に計算を実行してください。")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"orifice_result_{timestamp}.xlsx"

        file_path = filedialog.asksaveasfilename(
            title="Excel ファイルの保存先を選択してください",
            initialfile=default_name,
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx")],
        )

        if not file_path:
            return

        # 現在のガスの組成を取得（カスタム混合 or プリセット混合）
        mixture_composition = None
        mode = self.fluid_mode_var.get()
        if mode == "custom" and self.current_custom_composition:
            mixture_composition = self.current_custom_composition
        elif mode == "preset":
            from core.gas_database import get_mixture_composition
            mixture_composition = get_mixture_composition(
                getattr(self, "current_gas_name", ""))

        try:
            output_path = export_to_excel(
                df=self.df_result,
                correction_info=self.correction_info,
                fit_results=None,
                output_path=file_path,
                mixture_composition=mixture_composition,
                gas_name=getattr(self, "current_gas_name", ""),
            )
            messagebox.showinfo("完了", f"Excel に保存しました:\n{output_path}")

        except Exception as e:
            messagebox.showerror("エラー", f"Excel 出力中にエラーが発生しました:\n{e}")


if __name__ == "__main__":
    root = tk.Tk()
    app = OrificeCalculatorApp(root)
    root.mainloop()
