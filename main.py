"""MHXX お守り乱数計算機 + Switch 自動認識ループ (Android版)

mhxx_rng.py (デスクトップ版 nx_macro_tool から一切変更せずに移植した
RNGエンジン) を、タッチ操作向けのKivy UIから呼び出すアプリ。

追加機能 (v2.0):
  - 映像タブ: USB OTG ハブ経由のキャプチャーカードでSwitch画面をスマホに表示
  - オートタブ: Arduino Leonardo 連携でお守り自動認識ループ
    接続方式A: スマホ USB ホスト → Arduino (CDC Serial) → Switch (HID)
    接続方式B: スマホ Bluetooth (HC-05) → Arduino → Switch (HID)
"""
from __future__ import annotations

import os

from kivy.app import App
from kivy.core.text import LabelBase
from kivy.lang import Builder
from kivy.properties import NumericProperty, ObjectProperty
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

    def jump_to_auto_with_target(
        self,
        kind: int,
        s1_idx: int,
        s1_pts: int,
        s2_idx: int = -1,
        s2_pts: int = 0,
        slot: int = -1,
    ) -> None:
        """
        検索タブの「これを狙う」ボタンから呼び出す。
        TargetCharm を App.auto_target に設定してオートタブへ切り替える。
        """
        from hardware.charm_detector import TargetCharm
        app = App.get_running_app()
        app.auto_target = TargetCharm(
            kind=kind,
            skill1_idx=s1_idx,
            skill1_pts=s1_pts,
            skill2_idx=s2_idx,
            skill2_pts=s2_pts,
            slot=slot,
        )
        self.ids.auto_screen._refresh_target_text()
        # オートタブを検索して切り替え
        tabs = self.ids.tabs
        for item in tabs.tab_list:
            if item.text == "オート":
                tabs.switch_to(item)
                break


class MhxxRngApp(App):
    """アプリ全体で共有する状態 (お守り種類 / フレームレート表示) を持つ。"""

    kind = NumericProperty(0)  # 0=風化 1=古び 2=光る 3=なぞの
    fps = NumericProperty(30)  # 経過時間表示換算用 (30=オリジナル / 60=Switch2)

    def on_start(self):
        """起動直後に Android 権限を一括リクエストする。

        Camera ウィジェットは権限付与後に初めて生成するため、
        ここでリクエストするだけでよい（結果コールバックは不要）。
        Android 以外では何もしない。
        """
        try:
            from android.permissions import request_permissions, Permission
            request_permissions([
                Permission.CAMERA,
                Permission.READ_EXTERNAL_STORAGE,
            ])
        except ImportError:
            pass  # Android 以外の環境では無視

    def build(self):
        self.title = "MHXX RNG Tool"
        for kv_name in (
            "common.kv",
            "search_screen.kv",
            "around_screen.kv",
            "combo_screen.kv",
            "aimpoint_screen.kv",
            "ocr_screen.kv",
            "stream_screen.kv",   # v2: USB映像タブ
            "auto_screen.kv",     # v2: 自動ループタブ
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
