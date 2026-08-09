"""共通ウィジェット / ヘルパー。

ここにあるのは表示の整形とスレッド制御だけで、乱数計算のロジックは
一切含まない (すべて mhxx_rng.py 側の未改変のロジックをそのまま呼ぶ)。
"""
from __future__ import annotations

import threading
from typing import Callable, Iterator, Optional

from kivy.clock import Clock
from kivy.properties import BooleanProperty, ListProperty, NumericProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.textinput import TextInput

from mhxx_rng import MHXXEngine, continue_mash_info

# ---------------------------------------------------------------------------
# 表示整形ヘルパー (mhxx_rng の値をそのまま文字列にするだけ)
# ---------------------------------------------------------------------------


def format_elapsed(frame: int, fps: int) -> str:
    d, h, m, s, fr = MHXXEngine.watch(frame, fps=fps)
    return f"{d}日 {h}時間 {m}分 {s}秒 {fr}f"


def format_mash(frame: int) -> str:
    mashes, _reached, remainder = continue_mash_info(frame)
    return f"{mashes}回 (残{remainder}f)"


def hex_to_rgba(hex_color: str) -> list:
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16) / 255
    g = int(hex_color[2:4], 16) / 255
    b = int(hex_color[4:6], 16) / 255
    return [r, g, b, 1]


def clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def safe_int(text: Optional[str], default: int = 0) -> int:
    text = (text or "").strip()
    if not text:
        return default
    try:
        return int(text)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# 入力/結果表示ウィジェット
# ---------------------------------------------------------------------------


class IntInput(TextInput):
    """半角数字専用の1行入力欄 (フレーム数・Pt・ステップ数などに使用)。"""

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("input_filter", "int")
        kwargs.setdefault("multiline", False)
        kwargs.setdefault("write_tab", False)
        super().__init__(**kwargs)


class CharmResultCard(ButtonBehavior, BoxLayout):
    """検索/周辺確認タブの1件分の結果 (フレーム+お守り情報)。タップで
    周辺確認タブへフレームを転送できる (デスクトップ版のダブルクリック
    相当の操作をタップ1回に置き換えたもの)。"""

    frame = NumericProperty(0)
    offset_text = StringProperty("")
    elapsed_text = StringProperty("")
    skill1_text = StringProperty("")
    skill2_text = StringProperty("")
    slot_text = StringProperty("")
    rarity_text = StringProperty("")
    rarity_color = ListProperty([1, 1, 1, 1])
    mash_text = StringProperty("")
    is_center = BooleanProperty(False)


class FrameResultCard(BoxLayout):
    """調合スナイプタブの1件分の結果 (フレーム+経過時間のみ)。"""

    frame_text = StringProperty("")
    elapsed_text = StringProperty("")


# ---------------------------------------------------------------------------
# バックグラウンド検索ランナー
# ---------------------------------------------------------------------------


class BackgroundSearch:
    """mhxx_rng.MHXXEngine.search() / search_greater() / search_combo() の
    ような (should_stop=, on_progress=) を受け取るジェネレータ関数を
    バックグラウンドスレッドで実行し、結果/進捗/終了をKivyのメイン
    スレッドへ Clock.schedule_once 経由で安全に届けるヘルパー。

    Qt版の _SearchWorker / _ComboSearchWorker (QThread) に相当するが、
    乱数列を生成するアルゴリズム自体 (mhxx_rng.py) には一切手を加えて
    いない。ここは「別スレッドで回して結果をUIに届ける」配線のみ。
    """

    def __init__(
        self,
        run_search: Callable[[Callable[[], bool], Callable[[int, int], None]], Iterator[object]],
        on_result: Callable[[object], None],
        on_progress: Callable[[int, int], None],
        on_finished: Callable[[int], None],
    ) -> None:
        self._run_search = run_search
        self._on_result = on_result
        self._on_progress = on_progress
        self._on_finished = on_finished
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def request_stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        count = 0

        def progress(done: int, total: int) -> None:
            Clock.schedule_once(lambda dt: self._on_progress(done, total))

        try:
            for result in self._run_search(self._stop.is_set, progress):
                count += 1
                Clock.schedule_once(lambda dt, r=result: self._on_result(r))
        finally:
            Clock.schedule_once(lambda dt: self._on_finished(count))
