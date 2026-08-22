"""映像タブ ── USB キャプチャーカードのライブ映像表示とフレームキャプチャ

機能:
  - カメラインデックス選択 (外部UVCキャプチャーカードは通常 idx=2以降)
  - Switch 画面のリアルタイム表示
  - OCR 認識領域を指でドラッグして定義
  - 「テストOCR」で現在フレームのお守りを即時認識して表示
  - 認識領域と選択インデックスは App.stream_* に保存し Auto タブと共有
"""
from __future__ import annotations

import threading

from kivy.app import App
from kivy.clock import Clock
from kivy.properties import (
    BooleanProperty, ListProperty, NumericProperty, StringProperty
)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget

from hardware.usb_video import list_cameras, find_external_camera_index
from hardware.charm_detector import detect_from_texture, TargetCharm
from mhxx_rng import KIND_TABLES, SKILL_NAMES


# ---------------------------------------------------------------------------
# OCR 領域選択ウィジェット
# ---------------------------------------------------------------------------

class OcrRegionSelector(Widget):
    """
    カメラ映像の上に重ねて表示するドラッグ操作の矩形選択ウィジェット。

    ユーザーが指でドラッグすると、選択矩形 (normalized 0.0〜1.0) を
    App.stream_crop_ratio に書き込む。
    """
    rect_x = NumericProperty(0.05)
    rect_y = NumericProperty(0.3)
    rect_w = NumericProperty(0.9)
    rect_h = NumericProperty(0.4)
    editing = BooleanProperty(False)

    _drag_start = (0.0, 0.0)

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return False
        self.editing = True
        nx = (touch.x - self.x) / self.width
        ny = (touch.y - self.y) / self.height
        self._drag_start = (nx, ny)
        self.rect_x = nx
        self.rect_y = ny
        self.rect_w = 0.0
        self.rect_h = 0.0
        touch.grab(self)
        return True

    def on_touch_move(self, touch):
        if touch.grab_current is not self:
            return False
        nx = (touch.x - self.x) / self.width
        ny = (touch.y - self.y) / self.height
        sx, sy = self._drag_start
        self.rect_x = min(sx, nx)
        self.rect_y = min(sy, ny)
        self.rect_w = abs(nx - sx)
        self.rect_h = abs(ny - sy)
        return True

    def on_touch_up(self, touch):
        if touch.grab_current is not self:
            return False
        touch.ungrab(self)
        self.editing = False
        self._save_ratio()
        return True

    def _save_ratio(self):
        app = App.get_running_app()
        lx = self.rect_x
        ty = 1.0 - (self.rect_y + self.rect_h)   # Kivy Y は下原点→反転
        rx = self.rect_x + self.rect_w
        by = 1.0 - self.rect_y
        app.stream_crop_ratio = (
            max(0.0, min(lx, 1.0)),
            max(0.0, min(ty, 1.0)),
            max(0.0, min(rx, 1.0)),
            max(0.0, min(by, 1.0)),
        )

    def load_ratio(self, ratio):
        """App.stream_crop_ratio から矩形を復元する。"""
        lx, ty, rx, by = ratio
        self.rect_x = lx
        self.rect_y = 1.0 - by
        self.rect_w = rx - lx
        self.rect_h = by - ty


# ---------------------------------------------------------------------------
# 映像タブ本体
# ---------------------------------------------------------------------------

class StreamScreen(BoxLayout):
    """
    映像タブ画面。

    app.stream_camera_index : int   (選択カメラインデックス)
    app.stream_crop_ratio   : tuple (OCR 認識領域 left,top,right,bottom 0〜1)
    """

    status_text = StringProperty("カメラを選択して「開始」を押してください")
    ocr_result_text = StringProperty("")
    camera_labels = ListProperty([])
    camera_playing = BooleanProperty(False)
    show_region = BooleanProperty(True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._camera_list: list[dict] = []
        Clock.schedule_once(self._init_ui, 0)

    def _init_ui(self, _dt):
        app = App.get_running_app()
        if not hasattr(app, "stream_camera_index"):
            app.stream_camera_index = 2        # 外部カメラ既定値
        if not hasattr(app, "stream_crop_ratio"):
            app.stream_crop_ratio = (0.1, 0.25, 0.9, 0.75)
        if not hasattr(app, "auto_target"):
            app.auto_target = None
        self._refresh_camera_list()

    def _refresh_camera_list(self):
        cams = list_cameras()
        self._camera_list = cams
        # 外部カメラが見つかればデフォルトに設定
        ext_idx = find_external_camera_index()
        if ext_idx is not None:
            App.get_running_app().stream_camera_index = ext_idx
        labels = [c["label"] for c in cams] if cams else [
            "[2] 外部(USB)カメラ (推定)",
            "[0] 背面カメラ",
            "[1] 前面カメラ",
        ]
        self.camera_labels = labels
        if cams:
            self.status_text = f"{len(cams)} 台のカメラを検出しました"
        else:
            self.status_text = "カメラ一覧取得中... (Android 実機のみ)"

    def on_camera_selected(self, spinner_text: str):
        """カメラ選択スピナーが変更されたとき。"""
        for cam in self._camera_list:
            if cam["label"] == spinner_text:
                App.get_running_app().stream_camera_index = cam["index"]
                return
        # フォールバック: ラベル先頭 "[N]" からインデックスを抽出
        try:
            idx = int(spinner_text.split("]")[0].lstrip("["))
            App.get_running_app().stream_camera_index = idx
        except Exception:
            pass

    def start_camera(self):
        """カメラ映像を開始する。"""
        self.camera_playing = True
        self.status_text = "映像を配信中..."
        # OCR 領域の復元
        crop = App.get_running_app().stream_crop_ratio
        if hasattr(self.ids, "region_selector"):
            self.ids.region_selector.load_ratio(crop)

    def stop_camera(self):
        self.camera_playing = False
        self.status_text = "映像停止中"

    def toggle_camera(self):
        if self.camera_playing:
            self.stop_camera()
        else:
            self.start_camera()

    def run_test_ocr(self):
        """現在のフレームに対してテスト OCR を実行する。"""
        if not self.camera_playing:
            self.ocr_result_text = "先にカメラを開始してください"
            return
        cam = getattr(self.ids, "live_camera", None)
        if cam is None or cam.texture is None:
            self.ocr_result_text = "カメラテクスチャが取得できません"
            return
        app = App.get_running_app()
        target = getattr(app, "auto_target", None)
        if target is None:
            # テスト用ダミーターゲット (風化したお守り スキル1 任意)
            target = TargetCharm(kind=app.kind, skill1_idx=0,
                                 skill1_pts=1, slot=-1)

        crop = tuple(app.stream_crop_ratio)
        texture = cam.texture
        self.ocr_result_text = "OCR 実行中..."

        def _ocr():
            result = detect_from_texture(texture, target, crop)
            Clock.schedule_once(lambda dt: self._show_ocr(result))

        threading.Thread(target=_ocr, daemon=True).start()

    def _show_ocr(self, result):
        self.ocr_result_text = result.summary
        # 生テキストをステータスに短く表示
        raw = (result.raw_text or "")[:80]
        self.status_text = f"OCR: {raw}"

    def set_target_from_search(self, kind, s1_idx, s1_pts,
                                s2_idx=-1, s2_pts=0, slot=-1):
        """
        検索タブから「これを狙う」で呼び出されるメソッド。
        App.auto_target に TargetCharm を設定する。
        """
        app = App.get_running_app()
        app.auto_target = TargetCharm(
            kind=kind,
            skill1_idx=s1_idx,
            skill1_pts=s1_pts,
            skill2_idx=s2_idx,
            skill2_pts=s2_pts,
            slot=slot,
        )
        self.status_text = (
            f"目標設定: {SKILL_NAMES[KIND_TABLES[kind].skill1[s1_idx]].strip()}"
            f" +{s1_pts}  S{slot if slot >= 0 else '?'}"
        )
