"""
実行時出力への不確かさレポート追記機能
- コンソール出力への不確かさ情報表示
- GUI TreeView への不確かさ列追加
- 詳細レポートファイルの自動生成

Author: Shoei Manufacturing
Date: 2026-06-12
Version: 1.0
"""

import pandas as pd
from datetime import datetime
import os


# =====================================================================
# コンソール出力：不確かさレポートの生成
# =====================================================================

def generate_console_uncertainty_report(
    df_result,
    correction_info,
    include_uncertainty=True
):
    """
    コンソール用の不確かさレポートを生成して出力
    
    Args:
        df_result: 計算結果 DataFrame
        correction_info: 補正情報（温度など）
        include_uncertainty: 不確かさ情報を含めるか
    
    Returns:
        str: レポート文字列
    """
    
    report_lines = []
    
    # ============================================
    # ヘッダー
    # ============================================
    report_lines.append("=" * 90)
    report_lines.append("オリフィスメータ流量計算結果 - 不確かさレポート付")
    report_lines.append("=" * 90)
    report_lines.append("")
    
    # ============================================
    # 計算条件の要約
    # ============================================
    report_lines.append("【計算条件】")
    
    if isinstance(correction_info, dict):
        for key, value in correction_info.items():
            if isinstance(value, (int, float)):
                report_lines.append(f"  {key:20s}: {value:12.4f}")
            else:
                report_lines.append(f"  {key:20s}: {str(value)}")
    
    report_lines.append("")
    
    # ============================================
    # 計算結果サマリー（規格別）
    # ============================================
    report_lines.append("【計算結果サマリー】")
    report_lines.append("")
    
    # 見出し
    header_format = (
        "{標準:15s} | {流出係数:8s} | {膨張補正:8s} | "
        "{流量:12s} | {不確かさ:12s} | {信頼区間:20s}"
    )
    report_lines.append(header_format.format(
        標準="規格",
        流出係数="C",
        膨張補正="ε",
        流量="Q [m³/h]",
        不確かさ="U [%]",
        信頼区間="95% 信頼区間"
    ))
    report_lines.append("-" * 90)
    
    # データ行
    if df_result is not None:
        for standard_name, row in df_result.iterrows():
            
            Q = row.get("体積流量[m³/h]", None)
            C = row.get("流出係数C", None)
            epsilon = row.get("膨張補正係数ε", None)
            
            # 不確かさ情報
            if include_uncertainty and "拡張不確かさ[%]" in row:
                u_pct = row.get("拡張不確かさ[%]", 0)
                u_abs = row.get("拡張不確かさ[m3/h]", 0)
                q_lower = row.get("信頼区間下限[m3/h]", None)
                q_upper = row.get("信頼区間上限[m3/h]", None)
                
                if q_lower is not None and q_upper is not None:
                    ci_str = f"[{q_lower:.6f}, {q_upper:.6f}]"
                else:
                    ci_str = "N/A"
                
                u_str = f"±{u_pct:.2f}%"
            else:
                u_str = "評価なし"
                ci_str = "N/A"
            
            if Q is not None:
                data_format = (
                    "{:15s} | {:8.6f} | {:8.6f} | "
                    "{:12.6f} | {:12s} | {:20s}"
                )
                report_lines.append(data_format.format(
                    standard_name[:15],
                    C if C else 0,
                    epsilon if epsilon else 0,
                    Q,
                    u_str,
                    ci_str
                ))
    
    report_lines.append("")
    
    # ============================================
    # ISO5167 の詳細不確かさ情報
    # ============================================
    
    if include_uncertainty and df_result is not None:
        if "ISO5167 Corner Tap" in df_result.index:
            iso_row = df_result.loc["ISO5167 Corner Tap"]
            
            report_lines.append("【ISO5167 詳細不確かさ評価（ISO GUM準拠）】")
            report_lines.append("")
            
            # 基本情報
            Q_iso = iso_row.get("体積流量[m³/h]", None)
            
            if Q_iso is not None:
                report_lines.append(f"  計測流量:                    {Q_iso:.6f} m³/h")
            
            # 標準不確かさ
            u_std = iso_row.get("標準不確かさ[%]", None)
            if u_std is not None:
                report_lines.append(f"  標準不確かさ (k=1):          ±{u_std:.2f}%")
            
            # 拡張不確かさ
            u_exp = iso_row.get("拡張不確かさ[%]", None)
            u_abs = iso_row.get("拡張不確かさ[m3/h]", None)
            if u_exp is not None:
                report_lines.append(f"  拡張不確かさ (k=2, 95%):    ±{u_exp:.2f}% (±{u_abs:.6f} m³/h)")
            
            # 信頼区間
            q_lower = iso_row.get("信頼区間下限[m3/h]", None)
            q_upper = iso_row.get("信頼区間上限[m3/h]", None)
            if q_lower is not None and q_upper is not None:
                report_lines.append(f"  95% 信頼区間:               [{q_lower:.6f}, {q_upper:.6f}] m³/h")
            
            # 有効自由度
            nu_eff = iso_row.get("有効自由度", None)
            k_eff = iso_row.get("カバレッジ係数", None)
            if nu_eff is not None:
                report_lines.append(f"  有効自由度 (ν_eff):         {nu_eff:.1f}")
            if k_eff is not None:
                report_lines.append(f"  有効カバレッジ係数 (k):    {k_eff:.3f}")
            
            report_lines.append("")
            report_lines.append("  解釈:")
            report_lines.append(f"    同じ条件で計測を繰り返した場合、結果の95%が")
            report_lines.append(f"    [{q_lower:.6f}, {q_upper:.6f}] m³/h の範囲に収まります")
            report_lines.append("")
    
    # ============================================
    # 規格適合判定
    # ============================================
    
    #if df_result is not None:
    #    report_lines.append("【規格適合判定】")
    #    report_lines.append("")
        
    #    for standard_name, row in df_result.iterrows():
    #        comment = row.get("ISO適合判定", "")
    #        status_icon = "✓" if comment == "適合" else "⚠" if "範囲外" not in comment else "✗"
    #        report_lines.append(f"  {status_icon} {standard_name:25s}: {comment}")
        
    #    report_lines.append("")
    
    # ============================================
    # 推奨事項
    # ============================================
    
    if include_uncertainty and df_result is not None:
        report_lines.append("【推奨事項】")
        report_lines.append("")
        
        iso_row = df_result.loc["ISO5167 Corner Tap"] if "ISO5167 Corner Tap" in df_result.index else None
        
        if iso_row is not None:
            u_exp = iso_row.get("拡張不確かさ[%]", 0)
            
            if u_exp > 5.0:
                report_lines.append("  ⚠️  拡張不確かさが大きい (>5%) 場合:")
                report_lines.append("     → 計測精度の向上を検討してください")
                report_lines.append("       例) 差圧計の精度向上（現在 ±2% → ±1% へ）")
                report_lines.append("       例) 寸法測定精度の向上（現在 ±0.05% → ±0.02% へ）")
                report_lines.append("")
            
            if u_exp < 1.0:
                report_lines.append("  ✓  不確かさが小さい (<1%) 場合:")
                report_lines.append("     → 現在の計測精度は良好です")
                report_lines.append("")
        
        report_lines.append("  全規格について:")
        report_lines.append("  → 詳細な Pareto 分析は advanced_uncertainty_analysis.py を実行してください")
        report_lines.append("  → コマンド: python advanced_uncertainty_analysis.py")
        report_lines.append("")
    
    # ============================================
    # フッター
    # ============================================
    
    report_lines.append("=" * 90)
    report_lines.append(f"生成時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append("対応規格: ISO 5167-2:2022, ISO GUM (JCGM 100:2008)")
    report_lines.append("=" * 90)
    
    report_text = "\n".join(report_lines)
    return report_text


# =====================================================================
# 詳細レポートファイルの生成
# =====================================================================

def save_uncertainty_report_to_file(
    df_result,
    correction_info,
    output_dir="./uncertainty_reports",
    include_uncertainty=True
):
    """
    不確かさレポートをテキストファイルに保存
    
    Args:
        df_result: 計算結果 DataFrame
        correction_info: 補正情報
        output_dir: 出力ディレクトリ
        include_uncertainty: 不確かさ情報を含めるか
    """
    
    # ディレクトリ作成
    os.makedirs(output_dir, exist_ok=True)
    
    # レポート生成
    report_text = generate_console_uncertainty_report(
        df_result, correction_info, include_uncertainty
    )
    
    # ファイル名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(output_dir, f"uncertainty_report_{timestamp}.txt")
    
    # ファイルに保存
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(report_text)
    
    return filename, report_text


# =====================================================================
# GUI 用：不確かさ情報の Treeview への追加
# =====================================================================

def format_df_for_display(df_result, include_uncertainty=True):
    """
    GUI 表示用に DataFrame をフォーマット
    
    Args:
        df_result: 計算結果 DataFrame
        include_uncertainty: 不確かさ列を含めるか
    
    Returns:
        tuple: (表示用DataFrame, 列リスト)
    """
    
    if df_result is None:
        return None, []
    
    # コピーを作成（元の DataFrame を変更しない）
    df_display = df_result.copy()
    
    # 表示列の定義
    display_columns = [
        "差圧[kPa]",
        "レイノルズ数Re",
        "流出係数C",
        "膨張補正係数ε",
        "体積流量[m³/h]",
        "ノルマル流量[Nm³/h]"
    ]
    
    # 不確かさ列の追加
    if include_uncertainty:
        uncertainty_columns = [
            "標準不確かさ[%]",
            "拡張不確かさ[m3/h]",
            "拡張不確かさ[%]",
            "信頼区間下限[m3/h]",
            "信頼区間上限[m3/h]"
        ]
        
        # 存在する列のみを追加
        for col in uncertainty_columns:
            if col in df_display.columns:
                display_columns.append(col)
    
    # 規格適合判定
    #display_columns.append("ISO適合判定")
    
    # 存在する列のみを抽出
    available_columns = [col for col in display_columns if col in df_display.columns]
    
    return df_display[available_columns], available_columns


# =====================================================================
# TreeView 用の列フォーマット
# =====================================================================

def get_treeview_column_config(include_uncertainty=True):
    """
    TreeView の列設定を取得
    
    Returns:
        dict: 列設定（列名 → 幅と書式）
    """
    
    config = {
        "規格": {"width": 180, "anchor": "w"},
        "差圧[kPa]": {"width": 90, "anchor": "e"},
        "レイノルズ数Re": {"width": 100, "anchor": "e"},
        "流出係数C": {"width": 90, "anchor": "e"},
        "膨張補正係数ε": {"width": 100, "anchor": "e"},
        "体積流量[m³/h]": {"width": 120, "anchor": "e"},
        "ノルマル流量[Nm³/h]": {"width": 140, "anchor": "e"},
        "流量係数K": {"width": 90, "anchor": "e"},
        "流量係数Kn": {"width": 90, "anchor": "e"},
    }
    
    # 不確かさ列の追加
    if include_uncertainty:
        uncertainty_config = {
            "標準不確かさ[%]": {"width": 110, "anchor": "e"},
            "拡張不確かさ[m3/h]": {"width": 130, "anchor": "e"},
            "拡張不確かさ[%]": {"width": 110, "anchor": "e"},
            "信頼区間下限[m3/h]": {"width": 140, "anchor": "e"},
            "信頼区間上限[m3/h]": {"width": 140, "anchor": "e"},
        }
        config.update(uncertainty_config)
    
    #config["ISO適合判定"] = {"width": 250, "anchor": "w"}
    
    return config


# =====================================================================
# コンソール出力用の簡易フォーマッタ
# =====================================================================

def print_uncertainty_summary(df_result):
    """
    コンソールに不確かさサマリーを簡潔に出力
    """
    
    if df_result is None or "ISO5167 Corner Tap" not in df_result.index:
        return
    
    iso_row = df_result.loc["ISO5167 Corner Tap"]
    
    print("\n" + "=" * 70)
    print("【ISO5167 不確かさ評価結果】")
    print("=" * 70)
    
    Q = iso_row.get("体積流量[m³/h]", None)
    if Q is not None:
        print(f"  流量: {Q:.6f} m³/h")
    
    u_exp = iso_row.get("拡張不確かさ[%]", None)
    u_abs = iso_row.get("拡張不確かさ[m3/h]", None)
    if u_exp is not None:
        print(f"  95% 拡張不確かさ: ±{u_exp:.2f}% (±{u_abs:.6f} m³/h)")
    
    q_lower = iso_row.get("信頼区間下限[m3/h]", None)
    q_upper = iso_row.get("信頼区間上限[m3/h]", None)
    if q_lower is not None and q_upper is not None:
        print(f"  95% 信頼区間: [{q_lower:.6f}, {q_upper:.6f}] m³/h")
    
    nu_eff = iso_row.get("有効自由度", None)
    if nu_eff is not None:
        print(f"  有効自由度: {nu_eff:.1f}")
    
    print("=" * 70)


# =====================================================================
# 10点計算時の不確かさ推移表
# =====================================================================

def generate_uncertainty_trend_table(df_result):
    """
    10等分計算時の、差圧に対する不確かさの推移を表示
    
    Args:
        df_result: ISO5167 Corner Tap の複数行を含む DataFrame
    
    Returns:
        str: フォーマットされたテーブル
    """
    
    lines = []
    
    lines.append("")
    lines.append("【不確かさの推移（差圧依存性）】")
    lines.append("")
    lines.append(
        "差圧[kPa] | 流量[m³/h] | 標準不確かさ[%] | 拡張不確かさ[%] | 信頼区間幅[%]"
    )
    lines.append("-" * 80)
    
    if df_result is not None:
        # ISO5167 の行のみ抽出
        for idx, row in df_result.iterrows():
            if "ISO5167" in str(idx):
                dp = row.get("差圧[kPa]", None)
                Q = row.get("体積流量[m³/h]", None)
                u_std = row.get("標準不確かさ[%]", None)
                u_exp = row.get("拡張不確かさ[%]", None)
                
                if all([dp, Q, u_std, u_exp]):
                    # 信頼区間幅（相対）
                    ci_width = u_exp  # 拡張不確かさが相対幅
                    
                    lines.append(
                        f"{dp:9.1f} | {Q:10.6f} | {u_std:14.2f} | {u_exp:14.2f} | {ci_width:15.2f}"
                    )
    
    lines.append("")
    lines.append("注記:")
    lines.append("  - 差圧が大きいほど、流量の不確かさは相対的に小さくなる")
    lines.append("  - 計測精度は差圧レベルに依存するため、運用条件の確認が重要")
    lines.append("")
    
    return "\n".join(lines)


# =====================================================================
# テスト・例示コード
# =====================================================================

if __name__ == "__main__":
    
    print("コンソール出力モジュール テスト")
    
    # テスト用 DataFrame を作成
    test_data = {
        "差圧[kPa]": [10.0],
        "レイノルズ数Re": [50000],
        "流出係数C": [0.610500],
        "膨張補正係数ε": [0.976800],
        "体積流量[m³/h]": [1.500000],
        "ノルマル流量[Nm³/h]": [1.545000],
        "標準不確かさ[%]": [1.50],
        "拡張不確かさ[m3/h]": [0.046500],
        "拡張不確かさ[%]": [3.10],
        "信頼区間下限[m3/h]": [1.453500],
        "信頼区間上限[m3/h]": [1.546500],
        "有効自由度": [45.5],
        "カバレッジ係数": [1.960],
        #"ISO適合判定": ["適合"]
    }
    
    test_df = pd.DataFrame(test_data, index=["ISO5167 Corner Tap"])
    
    test_corr_info = {
        "流体": "空気",
        "配管内径D[mm]": 50.0,
        "オリフィス孔径d[mm]": 25.0,
        "管温度[℃]": 20.0,
        "上流圧力P1[kPa]": 111.3
    }
    
    # コンソールレポート生成
    report = generate_console_uncertainty_report(
        test_df, test_corr_info, include_uncertainty=True
    )
    
    print("\n" + report)
    
    # ファイル保存テスト
    filename, _ = save_uncertainty_report_to_file(
        test_df, test_corr_info, output_dir="./test_output"
    )
    print(f"\n✅ レポートを保存: {filename}")
    
    # TreeView 用フォーマット
    df_display, cols = format_df_for_display(test_df, include_uncertainty=True)
    print(f"\n✅ TreeView 用フォーマット完了")
    print(f"   表示列: {cols}")
