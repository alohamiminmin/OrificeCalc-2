# core/asme_mfc14m_conformance.py
"""
ASME MFC-14M-2003 適合判定（コンプライアンスチェック）
"""

from typing import Dict, Tuple


def check_asme_conformance(
    beta: float,
    D_mm: float,
    d_mm: float,
    Re_D: float,
    p1_kPa: float,
    p2_kPa: float,
    verbose: bool = True,
) -> Tuple[bool, Dict]:
    """
    ASME MFC-14M-2003 コーナータップ式の適用条件をチェック
    
    Args:
        beta: 孔径比（d/D）
        D_mm: 管内径 [mm]
        d_mm: 孔径 [mm]
        Re_D: レイノルズ数（D基準）
        p1_kPa: 上流圧力 [kPa]
        p2_kPa: 下流圧力 [kPa]
        verbose: 詳細メッセージを出力するか
    
    Returns:
        (is_conform: bool, details: dict)
        is_conform: True = すべて適合、False = 1つ以上不適合
        details: 各条件の判定結果
    """
    
    results = {}
    all_conform = True
    
    # ================================================================
    # 1. D（管内径）の範囲チェック
    # ================================================================
    d_min_mm = 12.0
    d_max_mm = 40.0
    
    if d_min_mm <= D_mm <= d_max_mm:
        results["D_range"] = {
            "conform": True,
            "value": D_mm,
            "min": d_min_mm,
            "max": d_max_mm,
            "unit": "mm",
            "note": f"✓ D = {D_mm:.1f} mm は適用範囲内（{d_min_mm}～{d_max_mm}mm）"
        }
    else:
        results["D_range"] = {
            "conform": False,
            "value": D_mm,
            "min": d_min_mm,
            "max": d_max_mm,
            "unit": "mm",
            "note": f"✗ D = {D_mm:.1f} mm は範囲外（{d_min_mm}～{d_max_mm}mm）"
        }
        all_conform = False
    
    # ================================================================
    # 2. β（孔径比）の範囲チェック
    # ================================================================
    beta_min = 0.1
    beta_max = 0.8
    
    if beta_min <= beta <= beta_max:
        results["beta_range"] = {
            "conform": True,
            "value": beta,
            "min": beta_min,
            "max": beta_max,
            "unit": "dimensionless",
            "note": f"✓ β = {beta:.5f} は適用範囲内（{beta_min}～{beta_max}）"
        }
    else:
        results["beta_range"] = {
            "conform": False,
            "value": beta,
            "min": beta_min,
            "max": beta_max,
            "unit": "dimensionless",
            "note": f"✗ β = {beta:.5f} は範囲外（{beta_min}～{beta_max}）"
        }
        all_conform = False
    
    # ================================================================
    # 3. Re（レイノルズ数）の下限チェック
    # ================================================================
    re_min = 1000.0
    
    if Re_D >= re_min:
        results["reynolds_min"] = {
            "conform": True,
            "value": Re_D,
            "min": re_min,
            "unit": "dimensionless",
            "note": f"✓ Re = {Re_D:.0f} は下限を満たす（≥ {re_min:.0f}）"
        }
    else:
        results["reynolds_min"] = {
            "conform": False,
            "value": Re_D,
            "min": re_min,
            "unit": "dimensionless",
            "note": f"✗ Re = {Re_D:.0f} は下限以下（< {re_min:.0f}）⚠ 精度低下の可能性"
        }
        all_conform = False
    
    # ================================================================
    # 4. 圧力比（P2/P1）チェック
    # ================================================================
    if p1_kPa > 0 and p2_kPa > 0:
        pressure_ratio = p2_kPa / p1_kPa
        pressure_ratio_min = 0.85
        
        if pressure_ratio >= pressure_ratio_min:
            results["pressure_ratio"] = {
                "conform": True,
                "value": pressure_ratio,
                "min": pressure_ratio_min,
                "unit": "dimensionless",
                "note": f"✓ P2/P1 = {pressure_ratio:.4f} は下限を満たす（≥ {pressure_ratio_min}）"
            }
        else:
            results["pressure_ratio"] = {
                "conform": False,
                "value": pressure_ratio,
                "min": pressure_ratio_min,
                "unit": "dimensionless",
                "note": f"✗ P2/P1 = {pressure_ratio:.4f} は下限以下（< {pressure_ratio_min}）"
            }
            all_conform = False
    else:
        results["pressure_ratio"] = {
            "conform": None,
            "value": None,
            "min": 0.85,
            "unit": "dimensionless",
            "note": "⚠ 圧力情報が不足（判定不可）"
        }
    
    # ================================================================
    # 5. d（孔径）の下限チェック（D > d の確認）
    # ================================================================
    if D_mm > d_mm:
        results["d_consistency"] = {
            "conform": True,
            "value": d_mm,
            "max": D_mm,
            "unit": "mm",
            "note": f"✓ d = {d_mm:.1f} mm < D = {D_mm:.1f} mm（孔径が管内径より小さい）"
        }
    else:
        results["d_consistency"] = {
            "conform": False,
            "value": d_mm,
            "max": D_mm,
            "unit": "mm",
            "note": f"✗ d = {d_mm:.1f} mm ≥ D = {D_mm:.1f} mm（不正）"
        }
        all_conform = False
    
    # ================================================================
    # 出力
    # ================================================================
    if verbose:
        print("\n" + "="*70)
        print("【ASME MFC-14M-2003 適合判定結果】")
        print("="*70)
        
        for key, result in results.items():
            status = "✓" if result["conform"] is True else ("✗" if result["conform"] is False else "⚠")
            print(f"\n{status} {key}:")
            print(f"   {result['note']}")
        
        print("\n" + "="*70)
        if all_conform:
            print("【結論】✅ すべて適合 - ASME MFC-14M-2003 の適用範囲内です")
        else:
            print("【結論】❌ 不適合条件あり - 適用範囲外または精度低下の可能性があります")
        print("="*70 + "\n")
    
    return all_conform, results


def get_asme_conformance_summary(
    conform_result: Tuple[bool, Dict]
) -> str:
    """
    適合判定結果をテキスト形式で取得
    
    Args:
        conform_result: check_asme_conformance() の戻り値
    
    Returns:
        テキスト形式の適合判定結果
    """
    is_conform, details = conform_result
    
    lines = []
    lines.append("【ASME MFC-14M-2003 適合判定】")
    lines.append("-" * 70)
    
    for key, result in details.items():
        symbol = "○" if result["conform"] is True else ("×" if result["conform"] is False else "△")
        lines.append(f"{symbol} {result['note']}")
    
    lines.append("-" * 70)
    if is_conform:
        lines.append("結論: ✅ 規格適合")
    else:
        lines.append("結論: ❌ 規格外 / 精度低下の可能性")
    
    return "\n".join(lines)


# ================================================================
# テスト実行
# ================================================================
if __name__ == "__main__":
    print("\n【テスト1】正常な条件")
    result1 = check_asme_conformance(
        beta=0.246,      # d=13mm, D=52.9mm
        D_mm=52.9,
        d_mm=13.0,
        Re_D=14820,
        p1_kPa=111.3,
        p2_kPa=101.3,    # P2/P1 = 0.91
        verbose=True
    )
    
    print("\n【テスト2】D が範囲外（小さすぎる）")
    result2 = check_asme_conformance(
        beta=0.246,
        D_mm=10.0,       # ❌ 12mm未満
        d_mm=2.5,
        Re_D=5000,
        p1_kPa=111.3,
        p2_kPa=101.3,
        verbose=True
    )
    
    print("\n【テスト3】Re が下限以下")
    result3 = check_asme_conformance(
        beta=0.246,
        D_mm=25.0,
        d_mm=6.0,
        Re_D=800,        # ❌ 1000以下
        p1_kPa=111.3,
        p2_kPa=101.3,
        verbose=True
    )
    
    print("\n【テスト4】圧力比が不足")
    result4 = check_asme_conformance(
        beta=0.246,
        D_mm=25.0,
        d_mm=6.0,
        Re_D=5000,
        p1_kPa=100.0,
        p2_kPa=70.0,     # ❌ P2/P1 = 0.70 < 0.85
        verbose=True
    )
