"""MHXX お守り乱数計算機 (Android版)

mhxx_rng.py (デスクトップ版 nx_macro_tool から一切変更せずに移植した
RNGエンジン) を、タッチ操作向けのKivy UIから呼び出すだけのアプリ。

追加機能:
  - USBキャプチャーボード経由の Switch 画面ストリーミング
  - Arduino Leonardo + 画像認識 によるお守り自動ループ
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
# ---------------------------------------------------------------------------
_REGULAR = os.path.join(FONT_DIR, "NotoSansJP-Regular.otf")
_BOLD    = os.path.join(FONT_DIR, "NotoSansJP-Bold.otf")

LabelBase.register(name="Roboto",    fn_regular=_REGULAR, fn_bold=_BOLD)
LabelBase.register(name="NotoSansJP", fn_regular=_REGULAR, fn_bold=_BOLD)


class RootLayout(BoxLayout):
    def jump_to_around(self, frame: int) -> None:
        """検索結果タップ時に、周辺確認タブへフレームを渡して切り替える。"""
        self.ids.around_screen.set_frame(frame)
        self.ids.around_screen._show()
        self.ids.tabs.switch_to(self.ids.around_tab_item)


class MhxxRngApp(App):
    """
    アプリ全体で共有する状態とデバイスインスタンスを持つ。

    app.uvc     : UVCCapture     — USB キャプチャーボード映像取得
    app.arduino : ArduinoCtrl   — Arduino Leonardo シリアル通信
    """

    kind = NumericProperty(0)   # 0=風化 1=古び 2=光る 3=なぞの
    fps  = NumericProperty(30)  # 経過時間表示換算用 (30=オリジナル / 60=Switch2)

    def build(self):
        self.title = "MHXX RNG Tool"

        # ---- デバイスドライバー (Android 実機のみ動作。それ以外は is_available()=False)
        from usb_stream.uvc_capture import UVCCapture
        from arduino.serial_ctrl import ArduinoCtrl
        self.uvc     = UVCCapture()
        self.arduino = ArduinoCtrl()

        # ---- KV ファイル読み込み
        for kv_name in (
            "common.kv",
            "search_screen.kv",
            "around_screen.kv",
            "combo_screen.kv",
            "aimpoint_screen.kv",
            "ocr_screen.kv",
            "stream_screen.kv",     # 追加: USBキャプチャー配信タブ
            "autoloop_screen.kv",   # 追加: お守り自動ループタブ
        ):
            Builder.load_file(os.path.join(BASE_DIR, "screens", kv_name))
        Builder.load_file(os.path.join(BASE_DIR, "app.kv"))
        return RootLayout()

    def on_stop(self):
        """アプリ終了時にデバイス接続を安全に閉じる。"""
        if hasattr(self, "uvc"):
            self.uvc.stop()
        if hasattr(self, "arduino"):
            self.arduino.disconnect()

    def set_kind(self, kind: int) -> None:
        if self.kind != kind:
            self.kind = kind

    def set_fps(self, fps: int) -> None:
        if self.fps != fps:
            self.fps = fps


if __name__ == "__main__":
    MhxxRngApp().run()
