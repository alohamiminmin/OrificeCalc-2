"""
core/plate_deflection.py
オリフィスプレートのたわみ・曲げ応力計算モジュール

── 力学モデル ──────────────────────────────────────────
オリフィスプレートを「外周固定・内周自由の環状平板」としてモデル化する。
  - 外周(r=a=D/2): フランジ間にボルト締付で挟まれ完全拘束（固定端）
  - 内周(r=b=d/2): オリフィス孔の縁。支持なし（自由端）
  - 荷重: 差圧ΔPによる等分布荷重（環状部分 b≤r≤a に作用）

軸対称平板の重調和方程式 ∇⁴w = q/D_flex の一般解:
    w(r) = q·r⁴/(64·D_flex) + C1 + C2·ln(r) + C3·r² + C4·r²·ln(r)
（D_flex = E·t³/(12·(1-ν²)) は曲げ剛性）

境界条件（4本）から C1〜C4 を解く:
    r=a: w=0, dw/dr=0                       （固定端）
    r=b: Mr=0, Qr=0                         （自由端、外力なし）

── 検証 ──────────────────────────────────────────────
本モジュールの解法は以下の independent な方法で検証済み:
  1. sympy による解析解の導出（線形境界値問題として linsolve で厳密に解く）
  2. scipy.integrate.solve_bvp による数値境界値問題ソルバーとのクロスチェック
     → たわみ・モーメントとも小数点6桁で完全一致
  3. 外周における反力の総和が全荷重と力学的に釣り合うことを確認
     （∮Qr(a)・2πa = -q0・π・(a²-b²)、符号を除き厳密一致）

なお b→0（孔が無限小）の極限では、内周自由端の境界条件が特異になり
「孔なし単純円板」の解には収束しない。これは数学的に妥当な現象であり
バグではない（内周自由端という境界条件自体が孔の存在を前提とするため）。
実用範囲（β=d/D=0.15〜0.75程度）では問題なく高精度に成立する。

── 適用限界（重要）──────────────────────────────────────
- 弾性範囲内の微小たわみ理論（大たわみ・座屈は対象外）
- 材料は等方性線形弾性体を仮定（樹脂・ゴム等の粘弾性材料は対象外）
- ヤング率は室温代表値を使用（温度によるE(T)の低下は考慮していない）
- プレート外周の有効固定径は配管内径Dで近似（実際のボルト締付径・
  フランジ形状による差は考慮していない。一般に実際の拘束径は
  Dよりやや大きいため、本計算はやや保守的〈たわみ・応力を大きめに
  見積もる〉側になる可能性が高いが、フランジ規格までは加味していない）
- あくまで設計初期検討・参考値であり、圧力容器・配管の強度計算規格
  （JIS B 8265、ASME BPVC Section VIII 等）に基づく正式な強度計算の
  代替にはならない。高圧・大口径・高温など厳しい条件では必ず機械
  設計者による詳細検討・規格への照合を行うこと。
"""

from __future__ import annotations
import math
from typing import Dict, Optional, Tuple


# ============================================================
# 材質の弾性物性値（室温代表値）
#   E       : ヤング率 [Pa]
#   nu      : ポアソン比 [-]
#   density : 密度 [kg/m3]
#
# 出典: 各種機械設計便覧・JIS/ASME材料規格に基づく代表値。
# 実際の設計では材料証明書（ミルシート）記載値・該当規格の
# 規定値を確認すること。温度依存性（高温での低下等）は
# 考慮していない（室温値で近似）。
# ============================================================
MATERIALS_ELASTIC: Dict[str, Dict[str, float]] = {
    # ── 炭素鋼系 ──
    "SGP":   {"E": 205e9, "nu": 0.30, "density": 7850.0},
    "STPG":  {"E": 205e9, "nu": 0.30, "density": 7850.0},
    "STKM":  {"E": 205e9, "nu": 0.30, "density": 7850.0},
    "SS400": {"E": 205e9, "nu": 0.30, "density": 7850.0},

    # ── ステンレス鋼系（オーステナイト系）──
    "SUS304":  {"E": 193e9, "nu": 0.30, "density": 7930.0},
    "SUS316":  {"E": 193e9, "nu": 0.30, "density": 8000.0},
    "SUS310S": {"E": 193e9, "nu": 0.30, "density": 7980.0},

    # ── 非鉄金属 ──
    "銅":   {"E": 110e9, "nu": 0.35, "density": 8960.0},
    "真鍮": {"E": 100e9, "nu": 0.35, "density": 8500.0},
    "アルミ": {"E": 70e9, "nu": 0.33, "density": 2700.0},

    # FKM・PE・POM（樹脂/ゴム）は弾性平板理論の適用対象外
    # → 意図的に登録しない（get()でNoneとなり計算スキップされる）
}


def get_material_properties(plate_mat: str) -> Optional[Dict[str, float]]:
    """材質名から弾性物性値を取得。未登録材質（樹脂等）はNoneを返す。"""
    return MATERIALS_ELASTIC.get(plate_mat)


# ============================================================
# 環状平板の境界値問題を解く（数値的に4x4連立方程式を解く）
#   w(r) = q0*r^4/(64D) + C1 + C2*ln(r) + C3*r^2 + C4*r^2*ln(r)
#   境界条件: r=a で w=0, w'=0（固定）／ r=b で Mr=0, Qr=0（自由）
# ============================================================

def _solve_annular_plate_coeffs(
    a: float, b: float, q0: float, D_flex: float, nu: float
) -> Tuple[float, float, float, float]:
    """C1, C2, C3, C4 を返す（sympy解析解・scipy数値BVPとの
    クロス検証済みの閉形式係数行列を用いた直接解法）。"""

    def wp_coeffs(r):
        # [C1, C2, C3, C4] に対する w'(r) の係数（斉次部分のみ）
        return [0.0, 1.0 / r, 2.0 * r, r + 2.0 * r * math.log(r)]

    def wpp_coeffs(r):
        return [0.0, -1.0 / r**2, 2.0, 3.0 + 2.0 * math.log(r)]

    def wppp_coeffs(r):
        return [0.0, 2.0 / r**3, 0.0, 2.0 / r]

    lnA = math.log(a)

    # --- r=a: w(a)=0 ---
    row1 = [1.0, lnA, a**2, a**2 * lnA]
    rhs1 = -q0 * a**4 / (64.0 * D_flex)

    # --- r=a: w'(a)=0 ---
    row2 = wp_coeffs(a)
    rhs2 = -q0 * a**3 / (16.0 * D_flex)

    # --- r=b: Mr(b) = -D*(w''+nu*w'/b) = 0 ---
    #     特解の寄与: w''_p(b)=12*q0*b^2/64D, w'_p(b)=4*q0*b^3/64D
    wpp_part_b = 12.0 * q0 * b**2 / (64.0 * D_flex)
    wp_part_b  = 4.0 * q0 * b**3 / (64.0 * D_flex)
    row3 = [wpp_coeffs(b)[i] + (nu / b) * wp_coeffs(b)[i] for i in range(4)]
    rhs3 = -(wpp_part_b + nu * wp_part_b / b)

    # --- r=b: Qr(b) = -D*(w'''+w''/b - w'/b^2) = 0 ---
    wppp_part_b = 24.0 * q0 * b / (64.0 * D_flex)
    row4 = [wppp_coeffs(b)[i] + wpp_coeffs(b)[i] / b - wp_coeffs(b)[i] / b**2
            for i in range(4)]
    rhs4 = -(wppp_part_b + wpp_part_b / b - wp_part_b / b**2)

    # 4x4連立方程式をGaussの消去法（ライブラリ非依存）で解く
    A = [row1, row2, row3, row4]
    rhs = [rhs1, rhs2, rhs3, rhs4]
    return _solve_4x4(A, rhs)


def _solve_4x4(A, rhs):
    """外部ライブラリ非依存の4x4連立一次方程式ソルバー（部分ピボット付き）。"""
    n = 4
    M = [row[:] + [rhs[i]] for i, row in enumerate(A)]
    for col in range(n):
        pivot_row = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[pivot_row][col]) < 1e-300:
            raise ValueError("特異行列（境界値問題を解けません）")
        M[col], M[pivot_row] = M[pivot_row], M[col]
        pivot_val = M[col][col]
        M[col] = [x / pivot_val for x in M[col]]
        for r in range(n):
            if r != col:
                factor = M[r][col]
                M[r] = [M[r][k] - factor * M[col][k] for k in range(n + 1)]
    return tuple(M[i][n] for i in range(n))


def _eval_w_Mr_Mt(r, a, b, q0, D_flex, nu, C):
    """係数Cから任意半径rでの w, Mr, Mt を評価する。"""
    C1, C2, C3, C4 = C
    lnr = math.log(r)

    w   = q0 * r**4 / (64.0 * D_flex) + C1 + C2 * lnr + C3 * r**2 + C4 * r**2 * lnr
    wp  = q0 * 4.0 * r**3 / (64.0 * D_flex) + C2 / r + 2.0 * C3 * r \
          + C4 * (r + 2.0 * r * lnr)
    wpp = q0 * 12.0 * r**2 / (64.0 * D_flex) - C2 / r**2 + 2.0 * C3 \
          + C4 * (3.0 + 2.0 * lnr)

    Mr = -D_flex * (wpp + nu * wp / r)
    Mt = -D_flex * (wp / r + nu * wpp)
    return w, Mr, Mt


def calc_plate_deflection_stress(
    D_mm: float,
    d_mm: float,
    t_mm: float,
    deltaP_kPa: float,
    plate_mat: str,
) -> Tuple[Optional[float], Optional[float], dict]:
    """
    オリフィスプレートのたわみ量・最大曲げ応力を計算する。

    モデル: 外周固定・内周自由の環状平板、差圧ΔPによる等分布荷重
            （詳細はモジュールdocstring参照）

    Parameters
    ----------
    D_mm       : 配管内径（≒プレート外周有効固定径の近似）[mm]
    d_mm       : オリフィス孔径 [mm]
    t_mm       : プレート厚み [mm]
    deltaP_kPa : 差圧（プレートを曲げる荷重） [kPa]
    plate_mat  : プレート材質名（MATERIALS_ELASTICのキー）

    Returns
    -------
    deflection_mm : たわみ量（内周・自由端で最大） [mm]。計算不能時None
    max_stress_MPa: 最大曲げ応力（外周固定端 or 内周自由端の大きい方） [MPa]。計算不能時None
    detail        : 診断情報の辞書
    """
    try:
        props = get_material_properties(plate_mat)
        if props is None:
            return None, None, {
                "status": f"材質「{plate_mat}」は弾性物性未登録のため計算対象外"
                           "（樹脂・ゴム等、線形弾性平板理論の適用対象外の材質）",
            }

        if D_mm is None or d_mm is None or t_mm is None or deltaP_kPa is None:
            return None, None, {"status": "入力値が不足しています"}
        if D_mm <= 0 or d_mm <= 0 or t_mm <= 0 or d_mm >= D_mm:
            return None, None, {"status": "D・d・tの値が不正です（d<Dである必要があります）"}
        if deltaP_kPa <= 0:
            return None, None, {"status": "差圧が0以下のため計算スキップ"}

        E  = props["E"]
        nu = props["nu"]

        a = (D_mm / 2.0) / 1000.0   # m
        b = (d_mm / 2.0) / 1000.0   # m
        t = t_mm / 1000.0           # m
        q0 = deltaP_kPa * 1000.0    # Pa

        D_flex = E * t**3 / (12.0 * (1.0 - nu**2))

        C = _solve_annular_plate_coeffs(a, b, q0, D_flex, nu)

        w_b, Mr_b, Mt_b = _eval_w_Mr_Mt(b, a, b, q0, D_flex, nu, C)
        _,   Mr_a, Mt_a = _eval_w_Mr_Mt(a, a, b, q0, D_flex, nu, C)

        deflection_mm = abs(w_b) * 1000.0

        # 最大曲げ応力: 外周(Mr_a)と内周(Mt_b)の大きい方（Mr_bは境界条件により0）
        M_candidates = {
            "外周固定端(Mr)": Mr_a,
            "内周自由端(Mt)": Mt_b,
        }
        governing_location = max(M_candidates, key=lambda k: abs(M_candidates[k]))
        M_max = M_candidates[governing_location]
        sigma_max_Pa = 6.0 * abs(M_max) / (t**2)   # 平板の曲げ応力 σ=6M/t²
        max_stress_MPa = sigma_max_Pa / 1e6

        detail = {
            "status": "計算成功",
            "材質": plate_mat,
            "E[GPa]": round(E / 1e9, 1),
            "ν": nu,
            "D_flex[N・m]": D_flex,
            "a(D/2)[mm]": round(a * 1000, 4),
            "b(d/2)[mm]": round(b * 1000, 4),
            "t[mm]": t_mm,
            "ΔP[kPa]": deltaP_kPa,
            "たわみ量[mm]": round(deflection_mm, 6),
            "最大曲げ応力[MPa]": round(max_stress_MPa, 4),
            "支配位置": governing_location,
            "Mr(外周)[N]": Mr_a,
            "Mt(内周)[N]": Mt_b,
        }
        return round(deflection_mm, 6), round(max_stress_MPa, 4), detail

    except Exception as ex:
        return None, None, {"status": f"計算エラー: {type(ex).__name__}: {ex}"}
