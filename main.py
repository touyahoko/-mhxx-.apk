"""MHXX お守り乱数計算機 (Android版)

mhxx_rng.py (デスクトップ版 nx_macro_tool から一切変更せずに移植した
RNGエンジン) を、タッチ操作向けのKivy UIから呼び出すだけのアプリ。
自動操作・コントローラー通信などの機能は含まない。
"""
from __future__ import annotations

import os

from kivy.app import App
from kivy.core.text import LabelBase
from kivy.lang import Builder
from kivy.properties import NumericProperty
from kivy.uix.boxlayout import BoxLayout

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(BASE_DIR, "assets", "fonts")

# ---------------------------------------------------------------------------
# 日本語フォント登録
#
# Kivy標準の "Roboto" は日本語グリフを含まないため、"Roboto" という名前を
# 同梱の Noto Sans JP で上書き登録する。こうすることで、font_name を個別に
# 指定していない標準ウィジェット (Label/Button/TextInput/Spinner等) も
# 含めてアプリ全体が自動的に日本語表示に対応する。
# ---------------------------------------------------------------------------
_REGULAR = os.path.join(FONT_DIR, "NotoSansJP-Regular.otf")
_BOLD = os.path.join(FONT_DIR, "NotoSansJP-Bold.otf")

LabelBase.register(name="Roboto", fn_regular=_REGULAR, fn_bold=_BOLD)
LabelBase.register(name="NotoSansJP", fn_regular=_REGULAR, fn_bold=_BOLD)


class RootLayout(BoxLayout):
    def jump_to_around(self, frame: int) -> None:
        """検索結果タップ時に、周辺確認タブへフレームを渡して切り替える。"""
        self.ids.around_screen.set_frame(frame)
        self.ids.around_screen._show()
        self.ids.tabs.switch_to(self.ids.around_tab_item)


class MhxxRngApp(App):
    """アプリ全体で共有する状態 (お守り種類 / フレームレート表示) を持つ。"""

    kind = NumericProperty(0)  # 0=風化 1=古び 2=光る 3=なぞの
    fps = NumericProperty(30)  # 経過時間表示換算用 (30=オリジナル / 60=Switch2)

    def build(self):
        self.title = "MHXX RNG Tool"
        for kv_name in (
            "common.kv",
            "search_screen.kv",
            "around_screen.kv",
            "combo_screen.kv",
            "aimpoint_screen.kv",
            "ocr_screen.kv",
        ):
            Builder.load_file(os.path.join(BASE_DIR, "screens", kv_name))
        Builder.load_file(os.path.join(BASE_DIR, "app.kv"))
        return RootLayout()

    def set_kind(self, kind: int) -> None:
        if self.kind != kind:
            self.kind = kind

    def set_fps(self, fps: int) -> None:
        if self.fps != fps:
            self.fps = fps


if __name__ == "__main__":
    MhxxRngApp().run()
