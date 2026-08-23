"""MHXX お守り乱数計算機 + Switch 自動認識ループ (Android版)"""
from __future__ import annotations

import os
import sys
import traceback

# ── Kivy 最低限のインポート（ここで失敗するとアプリ自体が起動しない）──
from kivy.app import App
from kivy.core.text import LabelBase
from kivy.lang import Builder
from kivy.properties import NumericProperty
from kivy.uix.boxlayout import BoxLayout

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
FONT_DIR  = os.path.join(BASE_DIR, "assets", "fonts")
_REGULAR  = os.path.join(FONT_DIR, "NotoSansJP-Regular.otf")
_BOLD     = os.path.join(FONT_DIR, "NotoSansJP-Bold.otf")


# =============================================================================
# エラー表示用ウィジェット
# （起動クラッシュが発生したときに、原因をそのまま画面に表示する）
# =============================================================================
def _make_error_screen(error_text: str):
    """エラー内容を画面に表示するウィジェットを返す。"""
    from kivy.uix.scrollview import ScrollView
    from kivy.uix.label import Label
    from kivy.uix.boxlayout import BoxLayout as BL
    from kivy.core.window import Window

    # /sdcard にもテキスト保存（ファイルマネージャーで読める）
    try:
        with open("/sdcard/mhxx_crash.txt", "w", encoding="utf-8") as f:
            f.write(error_text)
    except Exception:
        pass

    root = BL(orientation="vertical", padding=10, spacing=6)

    header = Label(
        text="[b][color=ff4444]起動エラー[/color][/b]\n"
             "/sdcard/mhxx_crash.txt にも保存しました",
        markup=True,
        size_hint_y=None,
        height=60,
        halign="left",
        valign="middle",
    )
    header.bind(size=lambda w, s: setattr(w, "text_size", (s[0], None)))

    body = Label(
        text=error_text,
        size_hint_y=None,
        halign="left",
        valign="top",
        font_size="11sp",
    )
    body.bind(
        width=lambda w, v: setattr(w, "text_size", (v, None)),
        texture_size=lambda w, v: setattr(w, "height", v[1]),
    )

    scroll = ScrollView(size_hint=(1, 1))
    scroll.add_widget(body)

    root.add_widget(header)
    root.add_widget(scroll)
    return root


# =============================================================================
# RootLayout（通常起動時のルートウィジェット）
# =============================================================================
class RootLayout(BoxLayout):
    def jump_to_around(self, frame: int) -> None:
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
        tabs = self.ids.tabs
        for item in tabs.tab_list:
            if item.text == "オート":
                tabs.switch_to(item)
                break


# =============================================================================
# App クラス
# =============================================================================
class MhxxRngApp(App):
    kind = NumericProperty(0)
    fps  = NumericProperty(30)

    def on_start(self):
        """Android 権限を一括リクエスト（Camera は使用直前にも確認する）。"""
        try:
            from android.permissions import request_permissions, Permission
            request_permissions([
                Permission.CAMERA,
                Permission.READ_EXTERNAL_STORAGE,
            ])
        except ImportError:
            pass

    # -------------------------------------------------------------------------
    # build() ── ここで例外が起きてもクラッシュせず画面に表示する
    # -------------------------------------------------------------------------
    def build(self):
        try:
            return self._build_normal()
        except Exception:  # noqa: BLE001
            error = traceback.format_exc()
            return _make_error_screen(error)

    def _build_normal(self):
        self.title = "MHXX RNG Tool"

        # ── フォント登録（ファイルが見つからない場合もここでキャッチされる）──
        if os.path.isfile(_REGULAR):
            LabelBase.register(name="Roboto",     fn_regular=_REGULAR, fn_bold=_BOLD)
            LabelBase.register(name="NotoSansJP", fn_regular=_REGULAR, fn_bold=_BOLD)
        else:
            # フォントが見つからない場合は警告だけ出して続行
            import warnings
            warnings.warn(f"フォントファイルが見つかりません: {_REGULAR}", stacklevel=2)

        # ── KV ファイル読み込み ──
        kv_files = (
            "common.kv",
            "search_screen.kv",
            "around_screen.kv",
            "combo_screen.kv",
            "aimpoint_screen.kv",
            "ocr_screen.kv",
            "stream_screen.kv",
            "auto_screen.kv",
        )
        for kv_name in kv_files:
            path = os.path.join(BASE_DIR, "screens", kv_name)
            if not os.path.isfile(path):
                raise FileNotFoundError(
                    f"KV ファイルが見つかりません: {path}\n"
                    f"screens/ フォルダの内容を確認してください。"
                )
            Builder.load_file(path)

        app_kv = os.path.join(BASE_DIR, "app.kv")
        if not os.path.isfile(app_kv):
            raise FileNotFoundError(f"app.kv が見つかりません: {app_kv}")
        Builder.load_file(app_kv)

        return RootLayout()

    def set_kind(self, kind: int) -> None:
        if self.kind != kind:
            self.kind = kind

    def set_fps(self, fps: int) -> None:
        if self.fps != fps:
            self.fps = fps


if __name__ == "__main__":
    MhxxRngApp().run()
