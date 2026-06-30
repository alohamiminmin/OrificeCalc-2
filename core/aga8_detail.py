# core/aga8_detail.py
"""
AGA8 Part 1 GROSS 方程式による圧縮係数 Z 計算

NIST AGA8 公式実装（Gross.cpp）を Python に忠実移植
出典: https://github.com/usnistgov/AGA8
著者: Eric W. Lemmon (NIST), Ian H. Bell (NIST)

インターフェース: calc_aga8_detail_z(P_Pa, T_K, gas_prop)
  - constants.py の Z_MODELS に登録済みの関数シグネチャに合わせる
  - 内部では P を kPa に変換して Gross 方程式を適用
"""

import math

# ============================================================
# 成分インデックス（Gross.cpp と同じ順序, 1-indexed）
# ============================================================
# 1:CH4  2:N2   3:CO2  4:C2H6  5:C3H8  6:iC4  7:nC4
# 8:iC5  9:nC5 10:C6  11:C7   12:C8   13:C9  14:C10
# 15:H2  16:O2  17:CO  18:H2O  19:H2S  20:He  21:Ar

COMP_INDEX = {
    "CH4":    1,  "N2":     2,  "CO2":    3,
    "C2H6":   4,  "C3H8":   5,  "iC4H10": 6,  "nC4H10": 7,
    "iC5H12": 8,  "nC5H12": 9,  "C6H14": 10,  "C7H16": 11,
    "C8H18": 12,  "C9H20": 13,  "C10H22":14,
    "H2":    15,  "O2":    16,  "CO":    17,
    "H2O":   18,  "H2S":   19,  "He":   20,   "Ar":   21,
}

NcGross = 21
epsilon = 1e-15

# ============================================================
# SetupGross: 係数初期化（Gross.cpp の SetupGross を移植）
# ============================================================

RGross = 8.31451

# 分子量 [g/mol]
MMiGross = [0] * (NcGross + 1)  # 1-indexed
MMiGross[1]  = 16.043    # CH4
MMiGross[2]  = 28.0135   # N2
MMiGross[3]  = 44.01     # CO2
MMiGross[4]  = 30.07     # C2H6
MMiGross[5]  = 44.097    # C3H8
MMiGross[6]  = 58.123    # iC4H10
MMiGross[7]  = 58.123    # nC4H10
MMiGross[8]  = 72.15     # iC5H12
MMiGross[9]  = 72.15     # nC5H12
MMiGross[10] = 86.177    # C6H14
MMiGross[11] = 100.204   # C7H16
MMiGross[12] = 114.231   # C8H18
MMiGross[13] = 128.258   # C9H20
MMiGross[14] = 142.285   # C10H22
MMiGross[15] = 2.0159    # H2
MMiGross[16] = 31.9988   # O2
MMiGross[17] = 28.01     # CO
MMiGross[18] = 18.0153   # H2O
MMiGross[19] = 34.082    # H2S
MMiGross[20] = 4.0026    # He
MMiGross[21] = 39.948    # Ar

# 発熱量 [kJ/mol] @ 298.15 K (AGA-5, 2009)
xHN = [0.0] * (NcGross + 1)  # 1-indexed
xHN[1]  = 890.63   # CH4
xHN[2]  = 0.0      # N2
xHN[3]  = 0.0      # CO2
xHN[4]  = 1560.69  # C2H6
xHN[5]  = 2219.17  # C3H8
xHN[6]  = 2868.2   # iC4H10
xHN[7]  = 2877.4   # nC4H10
xHN[8]  = 3528.83  # iC5H12
xHN[9]  = 3535.77  # nC5H12
xHN[10] = 4194.95  # C6H14
xHN[11] = 4853.43  # C7H16
xHN[12] = 5511.8   # C8H18
xHN[13] = 6171.15  # C9H20
xHN[14] = 6829.77  # C10H22
xHN[15] = 285.83   # H2
xHN[16] = 0.0      # O2
xHN[17] = 282.98   # CO
xHN[18] = 44.016   # H2O
xHN[19] = 562.01   # H2S
xHN[20] = 0.0      # He
xHN[21] = 0.0      # Ar

# ビリアル係数の温度多項式係数 (i,j) = (2,2),(2,3),(3,3)
# b[i][j] = b0 + b1*T + b2*T^2
b0 = [[0.0]*4 for _ in range(4)]
b1 = [[0.0]*4 for _ in range(4)]
b2 = [[0.0]*4 for _ in range(4)]
b0[2][2] = -0.1446;      b1[2][2] = 0.00074091;   b2[2][2] = -0.00000091195
b0[2][3] = -0.339693;    b1[2][3] = 0.00161176;   b2[2][3] = -0.00000204429
b0[3][3] = -0.86834;     b1[3][3] = 0.0040376;    b2[3][3] = -0.0000051657

c0 = [[[0.0]*4 for _ in range(4)] for _ in range(4)]
c1 = [[[0.0]*4 for _ in range(4)] for _ in range(4)]
c2 = [[[0.0]*4 for _ in range(4)] for _ in range(4)]
c0[2][2][2] = 0.0078498;   c1[2][2][2] = -0.000039895;   c2[2][2][2] = 0.000000061187
c0[2][2][3] = 0.00552066;  c1[2][2][3] = -0.0000168609;  c2[2][2][3] = 0.0000000157169
c0[2][3][3] = 0.00358783;  c1[2][3][3] = 0.00000806674;  c2[2][3][3] = -0.0000000325798
c0[3][3][3] = 0.0020513;   c1[3][3][3] = 0.000034888;    c2[3][3][3] = -0.000000083703

# 炭化水素 B, C の温度 × 発熱量多項式係数
bCHx = [[0.0]*3 for _ in range(3)]
cCHx = [[0.0]*3 for _ in range(3)]
bCHx[0][0] = -0.425468;    bCHx[1][0] = 0.002865;      bCHx[2][0] = -0.00000462073
bCHx[0][1] = 0.000877118;  bCHx[1][1] = -0.00000556281; bCHx[2][1] = 0.0000000088151
bCHx[0][2] = -0.000000824747; bCHx[1][2] = 0.00000000431436; bCHx[2][2] = -6.08319e-12
cCHx[0][0] = -0.302488;    cCHx[1][0] = 0.00195861;    cCHx[2][0] = -0.00000316302
cCHx[0][1] = 0.000646422;  cCHx[1][1] = -0.00000422876; cCHx[2][1] = 0.00000000688157
cCHx[0][2] = -0.000000332805; cCHx[1][2] = 0.0000000022316; cCHx[2][2] = -3.67713e-12

# dPdDsave（PressureGross → DensityGross で参照）
_dPdDsave = 0.0


# ============================================================
# MolarMassGross
# ============================================================
def MolarMassGross(x):
    """分子量計算 [g/mol]  x: 1-indexed リスト(長さ22)"""
    return sum(x[i] * MMiGross[i] for i in range(1, NcGross + 1))


# ============================================================
# GrossHv
# ============================================================
def GrossHv(x):
    """
    21成分組成から擬似3成分 xGrs = [0, xCH_equiv, xN2, xCO2] を計算
    戻り値: (xGrs, HN, HCH)
    """
    xGrs = [0.0] * 4  # 1-indexed: [_, CH_equiv, N2, CO2]
    xGrs[1] = 1.0 - x[2] - x[3]   # xCH (equivalent hydrocarbon)
    xGrs[2] = x[2]                  # xN2
    xGrs[3] = x[3]                  # xCO2

    HN = sum(x[i] * xHN[i] for i in range(1, NcGross + 1))
    HCH = HN / xGrs[1] if xGrs[1] > 0 else 0.0
    return xGrs, HN, HCH


# ============================================================
# Bmix
# ============================================================
def Bmix(T, xGrs, HCH):
    """
    混合第2・第3ビリアル係数を計算
    戻り値: (B [dm³/mol], C [dm⁶/mol²], ierr, herr)
    """
    global _dPdDsave

    bCH = [0.0] * 3
    cCH = [0.0] * 3
    BB  = [[0.0]*4 for _ in range(4)]
    CC  = [[[0.0]*4 for _ in range(4)] for _ in range(4)]

    onethrd = 1.0 / 3.0

    for i in range(3):
        bCH[i] = bCHx[0][i] + bCHx[1][i]*T + bCHx[2][i]*T**2
        cCH[i] = cCHx[0][i] + cCHx[1][i]*T + cCHx[2][i]*T**2

    for i in range(2, 4):
        for j in range(i, 4):
            BB[i][j] = b0[i][j] + b1[i][j]*T + b2[i][j]*T**2
            for k in range(j, 4):
                CC[i][j][k] = c0[i][j][k] + c1[i][j][k]*T + c2[i][j][k]*T**2

    BB[1][1] = bCH[0] + bCH[1]*HCH + bCH[2]*HCH**2
    BB[1][2] = (0.72 + 0.00001875*(320 - T)**2) * (BB[1][1] + BB[2][2]) / 2.0
    if BB[1][1] * BB[3][3] < 0:
        return 0.0, 0.0, 4, "Invalid input in Bmix routine"
    BB[1][3] = -0.865 * math.sqrt(BB[1][1] * BB[3][3])

    CC[1][1][1] = cCH[0] + cCH[1]*HCH + cCH[2]*HCH**2
    if CC[1][1][1] < 0 or CC[3][3][3] < 0:
        return 0.0, 0.0, 5, "Invalid input in Bmix routine"
    CC[1][1][2] = (0.92 + 0.0013*(T - 270)) * (CC[1][1][1]**2 * CC[2][2][2])**onethrd
    CC[1][2][2] = (0.92 + 0.0013*(T - 270)) * (CC[2][2][2]**2 * CC[1][1][1])**onethrd
    CC[1][1][3] = 0.92 * (CC[1][1][1]**2 * CC[3][3][3])**onethrd
    CC[1][3][3] = 0.92 * (CC[3][3][3]**2 * CC[1][1][1])**onethrd
    CC[1][2][3] = 1.1  * (CC[1][1][1] * CC[2][2][2] * CC[3][3][3])**onethrd

    B = 0.0
    C = 0.0
    for i in range(1, 4):
        for j in range(i, 4):
            if i == j:
                B += BB[i][i] * xGrs[i]**2
            else:
                B += 2 * BB[i][j] * xGrs[i] * xGrs[j]
            for k in range(j, 4):
                if i == j == k:
                    C += CC[i][i][i] * xGrs[i]**3
                elif i != j and j != k and i != k:
                    C += 6 * CC[i][j][k] * xGrs[i] * xGrs[j] * xGrs[k]
                else:
                    C += 3 * CC[i][j][k] * xGrs[i] * xGrs[j] * xGrs[k]

    return B, C, 0, ""


# ============================================================
# PressureGross
# ============================================================
def PressureGross(T, D, xGrs, HCH):
    """
    T [K], D [mol/L], xGrs, HCH → (P [kPa], Z, ierr, herr)
    """
    global _dPdDsave

    Z = 1.0
    P = D * RGross * T
    B, C, ierr, herr = Bmix(T, xGrs, HCH)
    if ierr > 0:
        return P, Z, ierr, herr

    Z = 1.0 + B*D + C*D**2
    P = D * RGross * T * Z
    _dPdDsave = RGross * T * (1.0 + 2*B*D + 3*C*D**2)

    if P < 0:
        return P, Z, -1, "Pressure is negative in the GROSS method."
    return P, Z, 0, ""


# ============================================================
# DensityGross
# ============================================================
def DensityGross(T, P_kPa, xGrs, HCH):
    """
    T [K], P [kPa], xGrs, HCH → (D [mol/L], ierr, herr)
    """
    global _dPdDsave

    if P_kPa < epsilon:
        return 0.0, 0, ""

    tolr = 1e-7
    D = P_kPa / RGross / T   # 理想気体初期値
    plog = math.log(P_kPa)
    vlog = -math.log(D)

    for _ in range(20):
        if vlog < -7 or vlog > 100:
            return P_kPa / RGross / T, 1, \
                "Calculation failed to converge in GROSS method, ideal gas density returned."

        D = math.exp(-vlog)
        P2, Z, ierr, herr = PressureGross(T, D, xGrs, HCH)
        if ierr > 0:
            return D, ierr, herr

        if _dPdDsave < epsilon or P2 < epsilon:
            vlog += 0.1
        else:
            dpdlv = -D * _dPdDsave
            vdiff = (math.log(P2) - plog) * P2 / dpdlv
            vlog -= vdiff
            if abs(vdiff) < tolr:
                if P2 < 0:
                    return P_kPa / RGross / T, 10, \
                        "Calculation failed to converge in GROSS method."
                return math.exp(-vlog), 0, ""

    return P_kPa / RGross / T, 10, \
        "Calculation failed to converge in GROSS method, ideal gas density returned."


# ============================================================
# 組成変換ユーティリティ
# ============================================================
def composition_to_x(composition_dict):
    """
    {"CH4": 0.88, "C2H6": 0.06, ...} → 1-indexed リスト(長さ22)
    未対応成分は無視。合計が 1.0 でない場合は正規化する。
    """
    x = [0.0] * (NcGross + 1)
    total = 0.0
    for name, frac in composition_dict.items():
        idx = COMP_INDEX.get(name)
        if idx is not None:
            x[idx] = float(frac)
            total += float(frac)
    # 正規化
    if total > 0 and abs(total - 1.0) > 1e-6:
        for i in range(1, NcGross + 1):
            x[i] /= total
    return x


# ============================================================
# 公開インターフェース
# ============================================================
def calc_aga8_detail_z(P_Pa, T_K, gas_prop):
    """
    AGA8 GROSS 方程式による圧縮係数 Z 計算

    Parameters
    ----------
    P_Pa : float  圧力 [Pa]  ← constants.py のシグネチャに合わせて Pa 受け取り
    T_K  : float  温度 [K]
    gas_prop : dict  GAS_DATABASE の 1 エントリ

    Returns
    -------
    Z : float or None
    """
    try:
        # 組成を取得
        comp = gas_prop.get("composition")
        if not comp:
            # 単独ガス: formula キーから 100% として扱う
            formula = gas_prop.get("formula") or gas_prop.get("description", "")
            if formula in COMP_INDEX:
                comp = {formula: 1.0}
            else:
                return None

        # 圧力単位変換: Pa → kPa
        P_kPa = P_Pa / 1000.0

        # 21成分配列に変換
        x = composition_to_x(comp)

        # GrossHv: 擬似3成分へ変換
        xGrs, HN, HCH = GrossHv(x)

        # DensityGross: モル密度を解く
        D, ierr, herr = DensityGross(T_K, P_kPa, xGrs, HCH)
        if ierr > 0 or D <= 0:
            return None

        # PressureGross: Z を計算
        P2, Z, ierr, herr = PressureGross(T_K, D, xGrs, HCH)
        if ierr > 0:
            return None

        # 物理的に妥当か確認
        if not (0.05 < Z < 3.0):
            return None

        return Z

    except Exception:
        return None
