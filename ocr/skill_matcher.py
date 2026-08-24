"""
skill_matcher.py — 英語名・日本語名どちらのファイルがあっても動くブリッジ
"""
from __future__ import annotations
import importlib.util, os, sys

_DIR = os.path.dirname(os.path.abspath(__file__))

def _load():
    # 英語名の実装ファイルを探す（このファイル自身は除く）
    for _name, _file in [("_skill_matcher_ja", "スキルマッチャー.py")]:
        _path = os.path.join(_DIR, _file)
        if os.path.isfile(_path):
            spec = importlib.util.spec_from_file_location(_name, _path)
            mod  = importlib.util.module_from_spec(spec)
            sys.modules[_name] = mod
            spec.loader.exec_module(mod)
            return mod
    raise ImportError(
        "スキルマッチャー.py が見つかりません。"
        "ocr/ フォルダに スキルマッチャー.py を配置してください。"
    )

_impl = _load()

# 必要な名前をこのモジュールに展開する
scan       = getattr(_impl, "scan",       None)
ScanResult = getattr(_impl, "ScanResult", None)

# その他のシンボルも全て引き継ぐ
_self = sys.modules[__name__]
for _n in dir(_impl):
    if not _n.startswith("_"):
        setattr(_self, _n, getattr(_impl, _n))
