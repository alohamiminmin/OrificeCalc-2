import os
import sys

# ============================================================
# 標準出力/標準エラーの安全化（--windowed ビルドの起動ハング対策）
#
# PyInstaller の --windowed / --noconsole でビルドした EXE は
# コンソールを持たないため、環境によって sys.stdout / sys.stderr が
# None、あるいは書き込みがブロックするストリームになることがある。
# その状態でアプリ内のどこかで print() や traceback 出力が発生すると、
# 書き込みが永久にブロックしたままメインスレッドが進まなくなり、
# 「タスクマネージャー上はプロセスが起動しているのに、CPU使用率は
# 低いままウィンドウが一切表示されない」という症状になる。
#
# 起動の最初の行で安全なログファイルへ付け替えておくことで、
# アプリ内のどこで print() / traceback が呼ばれてもハングしないように
# する。
# ============================================================
def _setup_safe_stdio() -> None:
    needs_redirect = (
        sys.stdout is None or sys.stderr is None
        or not hasattr(sys.stdout, "write")
        or not hasattr(sys.stderr, "write")
    )
    if not needs_redirect:
        return

    try:
        if getattr(sys, "frozen", False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        log_path = os.path.join(base_dir, "orifice_calc.log")
        log_file = open(log_path, "a", encoding="utf-8", buffering=1)
    except Exception:
        log_file = open(os.devnull, "w", encoding="utf-8")

    sys.stdout = log_file
    sys.stderr = log_file


_setup_safe_stdio()

# ============================================================
# __pycache__ をシステムの一時フォルダに隔離
# アプリフォルダ内に __pycache__ / .pyc が生成されなくなる
# ============================================================
_CACHE_DIR = os.path.join(
    os.environ.get("TEMP", os.environ.get("TMPDIR", "/tmp")),
    "orifice_calc_pycache"
)
os.environ["PYTHONPYCACHEPREFIX"] = _CACHE_DIR

# ============================================================
# Cantera データディレクトリを ASCII パスに固定
#
# Windows 環境で Python が日本語フォルダ下にインストールされている場合、
# ct.Solution() の内部で CANTERA_DATA を検索する際に ShiftJIS パスを
# UTF-8 として読もうとして "utf-8 codec can't decode byte 0xaa" エラーが
# 発生する。import cantera より前に CANTERA_DATA を明示設定することで
# これを回避する。
# ============================================================
def _setup_cantera_data() -> None:
    """CANTERA_DATA 環境変数を ASCII パスに設定する（import cantera の前に実行）"""
    import importlib.util
    import shutil
    import tempfile

    spec = importlib.util.find_spec("cantera")
    if spec is None or spec.origin is None:
        return  # Cantera 未インストール → 後でエラーハンドリングに委ねる

    ct_data = os.path.join(os.path.dirname(spec.origin), "data")

    if ct_data.isascii():
        # ASCII パスならそのまま設定して完了
        os.environ.setdefault("CANTERA_DATA", ct_data)
        return

    # 非 ASCII パス → ASCII な一時ディレクトリにコピーして設定
    ascii_dir = os.path.join(
        tempfile.gettempdir(), "cantera_ascii"
    )
    os.makedirs(ascii_dir, exist_ok=True)

    # yaml ファイルが存在しない場合のみコピー（初回のみ）
    gri30_dst = os.path.join(ascii_dir, "gri30.yaml")
    if not os.path.isfile(gri30_dst):
        try:
            for fname in os.listdir(ct_data):
                if fname.endswith(".yaml") or fname.endswith(".xml"):
                    shutil.copy2(
                        os.path.join(ct_data, fname),
                        os.path.join(ascii_dir, fname),
                    )
        except Exception:
            pass  # コピー失敗しても続行（後続でエラーハンドリング）

    os.environ["CANTERA_DATA"] = ascii_dir


_setup_cantera_data()

# ============================================================
# アプリ起動
# ============================================================
import tkinter as tk
from gui.app import OrificeCalculatorApp

if __name__ == "__main__":
    root = tk.Tk()
    app = OrificeCalculatorApp(root)
    root.mainloop()
