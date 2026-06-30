"""
core/gas_database.py
ガスデータベース（物性・プリセット）

【構成】
  COMPONENT_DATABASE : 純物質物性（カスタム混合ガス成分・単独ガスの共通ソース）
  GAS_DATABASE       : プリセットガス（単独ガス + 混合ガス）

【物性の出典】
  CoolProp 7.2.0 (NIST REFPROP 互換)
  CO のみ NIST WebBook / White "Viscous Fluid Flow" (CoolProp 粘度モデルなし)
  液相化合物(nC5+, H2O) : 気相外挿値

【単位】
  M        [g/mol]
  Tc       [K]
  Pc       [Pa]
  T_ref    [K]
  mu_ref   [Pa·s]
  rho_ref  [kg/m³] (0℃, 101325 Pa 理想気体密度)
  mu_coeff [K]     (Sutherland 係数 S)

【is_mixture フラグ】
  True  : プリセット混合ガス（composition キーで成分定義）
  False / なし : 単独ガス (formula キーで COMPONENT_DATABASE を参照)
"""

from typing import Dict, List, Optional, Any

# ============================================================
# 純物質コンポーネントデータベース
# キー: 化学式（カスタム混合ガス成分の選択肢に使用）
# ============================================================
COMPONENT_DATABASE: Dict[str, Dict[str, Any]] = {

    "CH4": {
        "name": "メタン", "name_en": "Methane",
        "M": 16.0428, "kappa": 1.3131, "omega": 0.0114,
        "Tc": 190.56, "Pc": 4599200,
        "T_ref": 273.15, "mu_ref": 1.039e-5, "mu_coeff": 198.0,
        "rho_ref": 0.7158, "source": "CoolProp 7.2.0",
    },
    "C2H6": {
        "name": "エタン", "name_en": "Ethane",
        "M": 30.0690, "kappa": 1.2017, "omega": 0.0990,
        "Tc": 305.32, "Pc": 4872200,
        "T_ref": 273.15, "mu_ref": 8.613e-6, "mu_coeff": 252.0,
        "rho_ref": 1.3415, "source": "CoolProp 7.2.0",
    },
    "C3H8": {
        "name": "プロパン", "name_en": "Propane",
        "M": 44.0956, "kappa": 1.1381, "omega": 0.1521,
        "Tc": 369.89, "Pc": 4251200,
        "T_ref": 273.15, "mu_ref": 7.469e-6, "mu_coeff": 278.0,
        "rho_ref": 1.9673, "source": "CoolProp 7.2.0",
    },
    "nC4H10": {
        "name": "n-ブタン", "name_en": "n-Butane",
        "M": 58.1222, "kappa": 1.0990, "omega": 0.2008,
        "Tc": 425.13, "Pc": 3796000,
        "T_ref": 273.15, "mu_ref": 6.769e-6, "mu_coeff": 300.0,
        "rho_ref": 2.5931, "source": "CoolProp 7.2.0",
    },
    "iC4H10": {
        "name": "イソブタン", "name_en": "Isobutane",
        "M": 58.1222, "kappa": 1.1019, "omega": 0.1835,
        "Tc": 407.81, "Pc": 3629000,
        "T_ref": 273.15, "mu_ref": 6.876e-6, "mu_coeff": 295.0,
        "rho_ref": 2.5931, "source": "CoolProp 7.2.0",
    },
    "nC5H12": {
        "name": "n-ペンタン", "name_en": "n-Pentane",
        "M": 72.1488, "kappa": 1.0798, "omega": 0.2510,
        "Tc": 469.70, "Pc": 3368000,
        "T_ref": 273.15, "mu_ref": 4.693e-6, "mu_coeff": 324.0,
        "rho_ref": 3.2189, "source": "CoolProp 7.2.0 (液相外挿)",
    },
    "iC5H12": {
        "name": "イソペンタン", "name_en": "Isopentane",
        "M": 72.1488, "kappa": 1.0815, "omega": 0.2274,
        "Tc": 460.35, "Pc": 3378000,
        "T_ref": 273.15, "mu_ref": 5.011e-6, "mu_coeff": 320.0,
        "rho_ref": 3.2189, "source": "CoolProp 7.2.0 (液相外挿)",
    },
    "C6H14": {
        "name": "n-ヘキサン", "name_en": "n-Hexane",
        "M": 86.1754, "kappa": 1.0665, "omega": 0.3003,
        "Tc": 507.82, "Pc": 3044000,
        "T_ref": 273.15, "mu_ref": 4.005e-6, "mu_coeff": 345.0,
        "rho_ref": 3.8447, "source": "CoolProp 7.2.0 (液相外挿)",
    },
    "N2": {
        "name": "窒素", "name_en": "Nitrogen",
        "M": 28.0135, "kappa": 1.3997, "omega": 0.0372,
        "Tc": 126.19, "Pc": 3395800,
        "T_ref": 273.15, "mu_ref": 1.663e-5, "mu_coeff": 111.0,
        "rho_ref": 1.2498, "source": "CoolProp 7.2.0",
    },
    "O2": {
        "name": "酸素", "name_en": "Oxygen",
        "M": 31.9988, "kappa": 1.3968, "omega": 0.0222,
        "Tc": 154.60, "Pc": 5046400,
        "T_ref": 273.15, "mu_ref": 1.914e-5, "mu_coeff": 127.0,
        "rho_ref": 1.4276, "source": "CoolProp 7.2.0",
    },
    "CO2": {
        "name": "二酸化炭素", "name_en": "Carbon Dioxide",
        "M": 44.0098, "kappa": 1.3007, "omega": 0.2239,
        "Tc": 304.13, "Pc": 7377300,
        "T_ref": 273.15, "mu_ref": 1.371e-5, "mu_coeff": 240.0,
        "rho_ref": 1.9635, "source": "CoolProp 7.2.0",
    },
    "H2S": {
        "name": "硫化水素", "name_en": "Hydrogen Sulfide",
        "M": 34.0809, "kappa": 1.3256, "omega": 0.1005,
        "Tc": 373.10, "Pc": 8998900,
        "T_ref": 273.15, "mu_ref": 1.101e-5, "mu_coeff": 274.0,
        "rho_ref": 1.5205, "source": "CoolProp 7.2.0",
    },
    "CO": {
        "name": "一酸化炭素", "name_en": "Carbon Monoxide",
        "M": 28.0101, "kappa": 1.4000, "omega": 0.0481,
        "Tc": 132.86, "Pc": 3494000,
        "T_ref": 273.15, "mu_ref": 1.628e-5, "mu_coeff": 118.0,
        "rho_ref": 1.2497, "source": "NIST WebBook / White (CoolProp粘度モデルなし)",
    },
    "H2": {
        "name": "水素", "name_en": "Hydrogen",
        "M": 2.0159, "kappa": 1.4096, "omega": -0.2190,
        "Tc": 33.14, "Pc": 1296400,
        "T_ref": 273.15, "mu_ref": 8.377e-6, "mu_coeff": 72.0,
        "rho_ref": 0.0899, "source": "CoolProp 7.2.0",
    },
    "He": {
        "name": "ヘリウム", "name_en": "Helium",
        "M": 4.0026, "kappa": 1.6667, "omega": -0.3835,
        "Tc": 5.20, "Pc": 228300,
        "T_ref": 273.15, "mu_ref": 1.869e-5, "mu_coeff": 79.4,
        "rho_ref": 0.1786, "source": "CoolProp 7.2.0",
    },
    "Ar": {
        "name": "アルゴン", "name_en": "Argon",
        "M": 39.9480, "kappa": 1.6667, "omega": -0.0022,
        "Tc": 150.69, "Pc": 4863000,
        "T_ref": 273.15, "mu_ref": 2.102e-5, "mu_coeff": 144.0,
        "rho_ref": 1.7823, "source": "CoolProp 7.2.0",
    },
    "H2O": {
        "name": "水（蒸気）", "name_en": "Water",
        "M": 18.0153, "kappa": 1.3303, "omega": 0.3443,
        "Tc": 647.10, "Pc": 22064000,
        "T_ref": 273.15, "mu_ref": 6.618e-6, "mu_coeff": 1064.0,
        "rho_ref": 0.8038, "source": "CoolProp 7.2.0 (液相外挿)",
    },
    "DME": {
        "name": "ジメチルエーテル", "name_en": "Dimethyl Ether",
        "formula_str": "CH3-O-CH3",
        "M": 46.0684, "kappa": 1.1530, "omega": 0.1960,
        "Tc": 400.38, "Pc": 5336800,
        "T_ref": 273.15, "mu_ref": 8.595e-6, "mu_coeff": 250.0,
        "rho_ref": 2.0553, "source": "CoolProp 7.2.0",
    },
}

# ============================================================
# 混合ガス計算用 CoolProp 名マッピング
# ============================================================
CP_NAME_MAP: Dict[str, str] = {
    "CH4":    "Methane",      "C2H6":   "Ethane",
    "C3H8":   "Propane",      "nC4H10": "n-Butane",
    "iC4H10": "IsoButane",    "nC5H12": "n-Pentane",
    "iC5H12": "Isopentane",   "C6H14":  "n-Hexane",
    "N2":     "Nitrogen",     "O2":     "Oxygen",
    "CO2":    "CarbonDioxide","H2S":    "HydrogenSulfide",
    "CO":     "CarbonMonoxide","H2":    "Hydrogen",
    "He":     "Helium",       "Ar":     "Argon",
    "H2O":    "Water",        "DME":    "DimethylEther",
}

# ============================================================
# プリセットガスデータベース
# ============================================================
def _single(formula: str, category: str,
            z_model: str = "HEOS") -> Dict[str, Any]:
    """COMPONENT_DATABASE から単独ガスエントリを生成"""
    d = dict(COMPONENT_DATABASE[formula])
    d.update({
        "is_mixture": False,
        "formula":    formula,
        "category":   category,
        "Z_model":    z_model,
        "description": formula,
    })
    return d


GAS_DATABASE: Dict[str, Dict[str, Any]] = {

    # ===== 単独ガス（炭化水素） =====
    "メタン":       _single("CH4",    "炭化水素"),
    "エタン":       _single("C2H6",   "炭化水素"),
    "プロパン":     _single("C3H8",   "炭化水素"),
    "n-ブタン":     _single("nC4H10", "炭化水素"),
    "イソブタン":   _single("iC4H10", "炭化水素"),
    "n-ペンタン":   _single("nC5H12", "炭化水素"),
    "イソペンタン": _single("iC5H12", "炭化水素"),
    "n-ヘキサン":   _single("C6H14",  "炭化水素"),

    # ===== 単独ガス（無機・その他） =====
    "窒素":         _single("N2",   "不活性ガス"),
    "酸素":         _single("O2",   "酸化ガス"),
    "二酸化炭素":   _single("CO2",  "酸性ガス"),
    "硫化水素":     _single("H2S",  "酸性ガス"),
    "一酸化炭素":   _single("CO",   "燃焼性ガス"),
    "水素":         _single("H2",   "燃焼性ガス"),
    "ヘリウム":     _single("He",   "不活性ガス"),
    "アルゴン":     _single("Ar",   "不活性ガス"),
    "水蒸気":       _single("H2O",  "蒸気"),
    "ジメチルエーテル": _single("DME", "エーテル"),

    # ===== 空気（プリセット混合） =====
    "空気": {
        "is_mixture": True,
        "category":   "標準ガス",
        "composition": {"N2": 0.7812, "O2": 0.2095, "Ar": 0.0093},
        "M":      28.966,
        "kappa":  1.400,
        "T_ref":  273.15,
        "mu_ref": 1.716e-5,
        "mu_coeff": 110.4,
        "rho_ref": 1.2924,
        "Z_model": "HEOS",
        "source": "ISO 2533:1975",
        "description": "標準大気",
    },

    # ===== 日本13A都市ガス (HHV≈45 MJ/Nm³) =====
    "日本13A都市ガス": {
        "is_mixture": True,
        "category":   "都市ガス",
        "composition": {
            "CH4": 0.896, "C2H6": 0.056, "C3H8": 0.034, "nC4H10": 0.01, "iC4H10": 0.004,
            "N2":  0.00, "CO2":  0.00,
        },
        "HHV_MJ_Nm3": 45.0,
        "Z_model": "HEOS",
        "source": "日本ガス協会 (JGA) 代表組成",
        "description": "都市ガス 13A (HHV≈45 MJ/Nm³)",
    },

    # ===== 日本LPG (HHV≈100 MJ/Nm³) =====
    "日本LPG": {
        "is_mixture": True,
        "category":   "LPG",
        "composition": {
            "C3H8":  0.9722,
            "nC4H10": 0.0195,
            "iC4H10": 0.0083,
        },
        "HHV_MJ_Nm3": 100.0,
        "Z_model": "HEOS",
        "source": "液化石油ガス保安規則 (代表組成)",
        "description": "LPG (HHV≈100 MJ/Nm³)",
    },

    # ===== LNG =====
        "China (Domestic Pipeline)": {
        "is_mixture": True,
        "category":   "LNG",
        "composition": {
            "CH4": 0.892, "C2H6": 0.045, "C3H8": 0.018, "nC4H10": 0.0056, "iC4H10": 0.0024,
            "nC5H12": 0.002,
            "N2":  0.015, "CO2":  0.02,
        },
        "Z_model": "HEOS",
    },

        "Thailand (Erawan/Pipeline)": {
        "is_mixture": True,
        "category":   "LNG",
        "composition": {
            "CH4": 0.813, "C2H6": 0.085, "C3H8": 0.035, "nC4H10": 0.00105, "iC4H10": 0.0045,
            "nC5H12": 0.005,
            "N2":  0.01, "CO2":  0.037,
        },
        "Z_model": "HEOS",
    },

        "Indonesia (Bontang/Tangguh)": {
        "is_mixture": True,
        "category":   "LNG",
        "composition": {
            "CH4": 0.9125, "C2H6": 0.048, "C3H8": 0.021, "nC4H10": 0.0063, "iC4H10": 0.0027,
            "nC5H12": 0.005,
            "N2":  0.01, "CO2":  0.008,
        },
        "Z_model": "HEOS",
    },

        "USA (Alaska/Kenai)": {
        "is_mixture": True,
        "category":   "LNG",
        "composition": {
            "CH4": 0.9971, "C2H6": 0.001, "C3H8": 0.0, "nC4H10": 0.0, "iC4H10": 0.0,
            "nC5H12": 0.0,
            "N2":  0.0015, "CO2":  0.0004,
        },
        "Z_model": "HEOS",
    },

        "USA (Shale/Sabine Pass)": {
        "is_mixture": True,
        "category":   "LNG",
        "composition": {
            "CH4": 0.9535, "C2H6": 0.0275, "C3H8": 0.0035, "nC4H10": 0.00035, "iC4H10": 0.00015,
            "nC5H12": 0.0,
            "N2":  0.013, "CO2":  0.002,
        },
        "Z_model": "HEOS",
    },

        "Russia (Sakhalin 2)": {
        "is_mixture": True,
        "category":   "LNG",
        "composition": {
            "CH4": 0.925, "C2H6": 0.0445, "C3H8": 0.017, "nC4H10": 0.00455, "iC4H10": 0.00195,
            "nC5H12": 0.0005,
            "N2":  0.0005, "CO2":  0.006,
        },
        "Z_model": "HEOS",
    },

        "Malaysia (MLNG)": {
        "is_mixture": True,
        "category":   "LNG",
        "composition": {
            "CH4": 0.915, "C2H6": 0.045, "C3H8": 0.025, "nC4H10": 0.00525, "iC4H10": 0.00225,
            "nC5H12": 0.0005,
            "N2":  0.0005, "CO2":  0.0065,
        },
        "Z_model": "HEOS",
    },

        "Qatar (Qatargas)": {
        "is_mixture": True,
        "category":   "LNG",
        "composition": {
            "CH4": 0.893, "C2H6": 0.059, "C3H8": 0.025, "nC4H10": 0.00805, "iC4H10": 0.00345,
            "nC5H12": 0.001,
            "N2":  0.0055, "CO2":  0.005,
        },
        "Z_model": "HEOS",
    },

        "Brunei (Lumut)": {
        "is_mixture": True,
        "category":   "LNG",
        "composition": {
            "CH4": 0.894, "C2H6": 0.059, "C3H8": 0.029, "nC4H10": 0.0091, "iC4H10": 0.0039,
            "nC5H12": 0.0005,
            "N2":  0.0002, "CO2":  0.0043,
        },
        "Z_model": "HEOS",
    },

        "Algeria (Arzew)": {
        "is_mixture": True,
        "category":   "LNG",
        "composition": {
            "CH4": 0.865, "C2H6": 0.094, "C3H8": 0.023, "nC4H10": 0.0042, "iC4H10": 0.0018,
            "nC5H12": 0.0005,
            "N2":  0.007, "CO2":  0.0045,
        },
        "Z_model": "HEOS",
    },

        "UAE (Das Island)": {
        "is_mixture": True,
        "category":   "LNG",
        "composition": {
            "CH4": 0.8175, "C2H6": 0.159, "C3H8": 0.019, "nC4H10": 0.0007, "iC4H10": 0.0003,
            "nC5H12": 0.0005,
            "N2":  0.0005, "CO2":  0.0025,
        },
        "Z_model": "HEOS",
    },
}

# ============================================================
# 混合物性計算（Kay's rule）
# ============================================================
def calc_mixture_properties(
    composition: Dict[str, float],
    T_K: float = 273.15,
    P_Pa: float = 101325.0,
) -> Dict[str, Any]:
    """
    組成辞書から混合ガス物性を Kay's rule で計算。
    CoolProp が利用可能な場合は Z を HEOS で計算。

    Parameters
    ----------
    composition : {"CH4": 0.88, "C2H6": 0.06, ...}
    T_K, P_Pa  : 計算条件（デフォルト 0℃, 1 atm）

    Returns
    -------
    dict: M, kappa, Tc, Pc, omega, mu_ref, rho_ref, Z_model
    """
    total = sum(composition.values())
    if total <= 0:
        return {}

    M     = sum(y / total * COMPONENT_DATABASE[c]["M"]
                for c, y in composition.items() if c in COMPONENT_DATABASE)
    Tc    = sum(y / total * COMPONENT_DATABASE[c]["Tc"]
                for c, y in composition.items() if c in COMPONENT_DATABASE)
    Pc    = sum(y / total * COMPONENT_DATABASE[c]["Pc"]
                for c, y in composition.items() if c in COMPONENT_DATABASE)
    omega = sum(y / total * COMPONENT_DATABASE[c]["omega"]
                for c, y in composition.items() if c in COMPONENT_DATABASE)
    kappa = sum(y / total * COMPONENT_DATABASE[c]["kappa"]
                for c, y in composition.items() if c in COMPONENT_DATABASE)
    mu    = sum(y / total * COMPONENT_DATABASE[c]["mu_ref"]
                for c, y in composition.items() if c in COMPONENT_DATABASE)

    # 理想気体参照密度
    R_u   = 8.31446
    rho_ref = P_Pa * (M / 1000) / (R_u * T_K)

    return {
        "M":        round(M, 4),
        "kappa":    round(kappa, 4),
        "Tc":       round(Tc, 2),
        "Pc":       round(Pc, 0),
        "omega":    round(omega, 4),
        "mu_ref":   round(mu, 9),
        "rho_ref":  round(rho_ref, 5),
        "T_ref":    T_K,
        "Z_model":  "HEOS",
        "composition": composition,
    }


# ============================================================
# アクセス関数
# ============================================================

def get_gas_names() -> List[str]:
    """GAS_DATABASE の全ガス名リスト（挿入順）"""
    return list(GAS_DATABASE.keys())

def get_preset_names() -> List[str]:
    """プリセット単独ガス名リスト（is_mixture = False）"""
    return [n for n, v in GAS_DATABASE.items() if not v.get("is_mixture")]

def get_mixture_names() -> List[str]:
    """プリセット混合ガス名リスト（is_mixture = True）"""
    return [n for n, v in GAS_DATABASE.items() if v.get("is_mixture")]

def get_custom_component_names() -> List[str]:
    """カスタム混合ガス成分として選択可能な formula のリスト"""
    return list(COMPONENT_DATABASE.keys())

def get_gas_properties(gas_name: str) -> Optional[Dict[str, Any]]:
    """ガス名 → GAS_DATABASE エントリ。なければ None。"""
    return GAS_DATABASE.get(gas_name)

def get_component_properties(formula: str) -> Optional[Dict[str, Any]]:
    """化学式 → COMPONENT_DATABASE エントリ。なければ None。"""
    return COMPONENT_DATABASE.get(formula)

def create_custom_mixture(
    composition: Dict[str, float],
    name: str = "カスタム混合ガス",
) -> Optional[Dict[str, Any]]:
    """
    カスタム混合ガスオブジェクトを生成。
    1成分 100% → 単独ガスとして扱う。
    """
    if not composition:
        return None

    # 正規化
    total = sum(composition.values())
    comp  = {k: v / total for k, v in composition.items() if v > 0}

    # 未対応成分チェック
    unknown = [c for c in comp if c not in COMPONENT_DATABASE]
    if unknown:
        raise ValueError(f"未対応成分: {unknown}")

    props = calc_mixture_properties(comp)
    props.update({
        "is_mixture": len(comp) > 1,
        "category":   "カスタム混合ガス",
        "description": name,
        "Z_model":     "HEOS",
    })
    return props


# ============================================================
# 後方互換エイリアス（旧 gas_database.py との互換性維持）
# ============================================================

def calculate_mixture_properties(
    composition: Dict[str, float],
    T_K: float = 273.15,
    P_Pa: float = 101325.0,
) -> Dict[str, Any]:
    """後方互換: calc_mixture_properties の旧名"""
    return calc_mixture_properties(composition, T_K, P_Pa)


def get_available_gases() -> List[str]:
    """後方互換: GAS_DATABASE の全ガス名リスト"""
    return get_gas_names()


def get_component_list() -> List[str]:
    """後方互換: カスタム混合成分の formula リスト"""
    return get_custom_component_names()


def get_preset_mixtures() -> Dict[str, Dict]:
    """後方互換: プリセット混合ガス辞書 {name: props}"""
    return {n: v for n, v in GAS_DATABASE.items() if v.get("is_mixture")}


def validate_composition(composition: Dict[str, float]) -> tuple:
    """
    後方互換: 組成辞書の妥当性を検証。
    Returns (is_valid: bool, message: str)
    """
    if not composition:
        return False, "組成が空です"

    unknown = [c for c in composition if c not in COMPONENT_DATABASE]
    if unknown:
        return False, f"未対応成分: {unknown}"

    total = sum(v for v in composition.values() if v >= 0)
    if total <= 0:
        return False, "モル分率の合計が 0 以下です"

    if abs(total - 1.0) > 0.01:
        return True, f"警告: モル分率の合計 = {total:.4f} (自動正規化されます)"

    return True, "OK"


def get_mixture_composition(gas_name: str) -> Optional[Dict[str, float]]:
    """後方互換: プリセット混合ガスの composition 辞書を返す"""
    props = GAS_DATABASE.get(gas_name)
    if props and props.get("is_mixture"):
        return props.get("composition")
    return None


# ============================================================
# プリセット混合ガスの物性値を composition から自動補完
# （M, kappa, Tc, Pc, omega, mu_ref, rho_ref が未定義の場合に計算）
# ============================================================
def _fill_mixture_props() -> None:
    """GAS_DATABASE のプリセット混合ガスに物性値を補完する（初期化時に1回実行）"""
    for _name, _props in GAS_DATABASE.items():
        if not _props.get("is_mixture"):
            continue
        _comp = _props.get("composition")
        if not _comp:
            continue
        # Kay's rule で計算
        _mixed = calc_mixture_properties(_comp)
        for _key in ("M", "kappa", "Tc", "Pc", "omega", "mu_ref", "rho_ref", "T_ref", "mu_coeff"):
            if _key not in _props and _key in _mixed:
                _props[_key] = _mixed[_key]

_fill_mixture_props()
