"""MHXX お守り乱数計算機 + Switch 自動認識ループ (Android版)"""
from __future__ import annotations
import os, sys, traceback

from kivy.app import App
from kivy.core.text import LabelBase
from kivy.lang import Builder
from kivy.properties import NumericProperty
from kivy.uix.boxlayout import BoxLayout

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── フォントディレクトリ（英語名・日本語名どちらでも動く）──
for _fd in [os.path.join(BASE_DIR, "assets", "fonts"),
            os.path.join(BASE_DIR, "assets", "フォント"),
            os.path.join(BASE_DIR, "assets")]:
    if os.path.isdir(_fd):
        FONT_DIR = _fd
        break
else:
    FONT_DIR = os.path.join(BASE_DIR, "assets", "fonts")

_REGULAR = os.path.join(FONT_DIR, "NotoSansJP-Regular.otf")
_BOLD    = os.path.join(FONT_DIR, "NotoSansJP-Bold.otf")

# ── KV ファイル名マッピング（英語名 → 日本語名フォールバック）──
_KV_MAP = {
    "common.kv":          ["共通.kv"],
    "search_screen.kv":   ["検索画面.kv", "検索画面kv"],
    "around_screen.kv":   [],
    "combo_screen.kv":    [],
    "aimpoint_screen.kv": ["目標地点スクリーン.kv"],
    "ocr_screen.kv":      [],
    "stream_screen.kv":   ["ストリームスクリーン.kv"],
    "auto_screen.kv":     [],
}

def _find_kv(name_en):
    """英語名 → 日本語名の順でKVファイルを探す。"""
    base = os.path.join(BASE_DIR, "screens")
    for name in [name_en] + _KV_MAP.get(name_en, []):
        path = os.path.join(base, name)
        if os.path.isfile(path):
            return path
    tried = [name_en] + _KV_MAP.get(name_en, [])
    raise FileNotFoundError(
        f"KVファイルが見つかりません。以下を確認してください: {tried}"
    )


# ── エラー表示ウィジェット ──
def _make_error_screen(error_text: str):
    from kivy.uix.scrollview import ScrollView
    from kivy.uix.label import Label
    from kivy.core.window import Window
    try:
        with open("/sdcard/mhxx_crash.txt", "w", encoding="utf-8") as f:
            f.write(error_text)
    except Exception:
        pass
    root = BoxLayout(orientation="vertical", padding=10, spacing=6)
    header = Label(
        text="[b][color=ff4444]起動エラー[/color][/b]\n/sdcard/mhxx_crash.txt にも保存しました",
        markup=True, size_hint_y=None, height=60,
        halign="left", valign="middle",
    )
    header.bind(size=lambda w, s: setattr(w, "text_size", (s[0], None)))
    body = Label(text=error_text, size_hint_y=None, halign="left",
                 valign="top", font_size="11sp")
    body.bind(
        width=lambda w, v: setattr(w, "text_size", (v, None)),
        texture_size=lambda w, v: setattr(w, "height", v[1]),
    )
    scroll = ScrollView(size_hint=(1, 1))
    scroll.add_widget(body)
    root.add_widget(header)
    root.add_widget(scroll)
    return root


# ── RootLayout ──
class RootLayout(BoxLayout):
    def jump_to_around(self, frame: int) -> None:
        self.ids.around_screen.set_frame(frame)
        self.ids.around_screen._show()
        self.ids.tabs.switch_to(self.ids.around_tab_item)

    def jump_to_auto_with_target(self, kind, s1_idx, s1_pts,
                                  s2_idx=-1, s2_pts=0, slot=-1):
        from hardware.charm_detector import TargetCharm
        app = App.get_running_app()
        app.auto_target = TargetCharm(kind=kind, skill1_idx=s1_idx,
                                       skill1_pts=s1_pts, skill2_idx=s2_idx,
                                       skill2_pts=s2_pts, slot=slot)
        self.ids.auto_screen._refresh_target_text()
        for item in self.ids.tabs.tab_list:
            if item.text == "オート":
                self.ids.tabs.switch_to(item)
                break


# ── App ──
class MhxxRngApp(App):
    kind = NumericProperty(0)
    fps  = NumericProperty(30)

    def on_start(self):
        try:
            from android.permissions import request_permissions, Permission
            request_permissions([Permission.CAMERA, Permission.READ_EXTERNAL_STORAGE])
        except ImportError:
            pass

    def build(self):
        try:
            return self._build_normal()
        except Exception:
            return _make_error_screen(traceback.format_exc())

    def _build_normal(self):
        self.title = "MHXX RNG Tool"
        if os.path.isfile(_REGULAR):
            LabelBase.register(name="Roboto",     fn_regular=_REGULAR, fn_bold=_BOLD)
            LabelBase.register(name="NotoSansJP", fn_regular=_REGULAR, fn_bold=_BOLD)
        for name_en in list(_KV_MAP.keys()):
            Builder.load_file(_find_kv(name_en))
        Builder.load_file(os.path.join(BASE_DIR, "app.kv"))
        return RootLayout()

    def set_kind(self, kind): self.kind = kind
    def set_fps(self, fps):   self.fps  = fps


if __name__ == "__main__":
    MhxxRngApp().run()
