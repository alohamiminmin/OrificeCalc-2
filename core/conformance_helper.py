# core/conformance_helper.py
"""
適合判定結果をGUIテーブルに表示するためのヘルパー関数
"""

from asme_mfc14m_conformance import check_asme_conformance


def add_conformance_info_to_dataframe(df, mode, D_mm, d_mm, P1_kPa, P2_kPa):
    """
    DataFrameに適合判定情報を追加
    
    Args:
        df: 計算結果DataFrame
        mode: 計算モード（'ASME_MFC14M', 'ISO_RHG', 'JIS_Z8762'）
        D_mm: 管内径 [mm]
        d_mm: 孔径 [mm]
        P1_kPa: 上流圧力 [kPa]
        P2_kPa: 下流圧力 [kPa]
    
    Returns:
        修正されたDataFrame
    """
    
    if df is None or len(df) == 0:
        return df
    
    # ASME のみ適合チェック対象
    if mode != "ASME_MFC14M":
        df["適合"] = "─"  # その他規格は「─」（チェック対象外）
        df["適合備考"] = ""
        return df
    
    # ASME の適合判定
    conformance_symbols = []
    conformance_notes = []
    
    for idx, row in df.iterrows():
        beta = row.get("β")
        Re_D = row.get("レイノルズ数Re")
        
        if beta is None or Re_D is None:
            conformance_symbols.append("✗")
            conformance_notes.append("計算不能")
            continue
        
        try:
            is_conform, details = check_asme_conformance(
                beta=beta,
                D_mm=D_mm,
                d_mm=d_mm,
                Re_D=Re_D,
                p1_kPa=P1_kPa,
                p2_kPa=P2_kPa,
                verbose=False
            )
            
            symbol = "○" if is_conform else "×"
            conformance_symbols.append(symbol)
            
            # 不適合理由を集約
            non_conform_items = []
            for key, result in details.items():
                if result["conform"] is False:
                    # 簡潔な理由を抽出
                    if key == "D_range":
                        non_conform_items.append(f"D={D_mm}mm(範囲外)")
                    elif key == "beta_range":
                        non_conform_items.append(f"β={beta:.3f}(範囲外)")
                    elif key == "reynolds_min":
                        non_conform_items.append(f"Re={int(Re_D)}<1000")
                    elif key == "pressure_ratio":
                        p_ratio = P2_kPa / P1_kPa if P1_kPa > 0 else 0
                        non_conform_items.append(f"P2/P1={p_ratio:.2f}<0.85")
                    elif key == "d_consistency":
                        non_conform_items.append("d≥D(不正)")
            
            note = " / ".join(non_conform_items) if non_conform_items else ""
            conformance_notes.append(note)
        
        except Exception as e:
            conformance_symbols.append("⚠")
            conformance_notes.append(f"判定エラー: {str(e)[:20]}")
    
    df["適合"] = conformance_symbols
    df["適合備考"] = conformance_notes
    
    return df


if __name__ == "__main__":
    # テスト
    import pandas as pd
    
    test_df = pd.DataFrame({
        "β": [0.246, 0.246, 0.246],
        "レイノルズ数Re": [5000, 800, 5000],
        "流出係数C": [0.5991, 0.5991, 0.5991]
    })
    
    print("【テスト1】正常な条件")
    result1 = add_conformance_info_to_dataframe(
        test_df.copy(),
        mode="ASME_MFC14M",
        D_mm=25.0,
        d_mm=6.15,
        P1_kPa=111.3,
        P2_kPa=101.3
    )
    print(result1[["β", "レイノルズ数Re", "適合", "適合備考"]])
    
    print("\n【テスト2】Re が下限以下")
    result2 = add_conformance_info_to_dataframe(
        test_df.copy(),
        mode="ASME_MFC14M",
        D_mm=25.0,
        d_mm=6.15,
        P1_kPa=111.3,
        P2_kPa=101.3
    )
    print(result2[["β", "レイノルズ数Re", "適合", "適合備考"]])
