"""
core/gerg2008.py  ── 後方互換ラッパー
GERG-2008 は HEOS バックエンド (coolprop_models.py) と同一。
constants.py / 外部コードが import するエントリポイントとして保持。
"""
from core.coolprop_models import calc_Z_GERG2008  # noqa: F401
