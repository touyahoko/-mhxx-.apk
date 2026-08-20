"""📡 配信タブ - USB キャプチャーボード映像表示

キャプチャーボードを USB OTG で接続し、Switch の画面を
リアルタイムでスマートフォン上に表示する。

• 映像は usb_stream.uvc_capture.UVCCapture が取得する
• 最新フレームは app.uvc.latest_frame (bytes/JPEG) で参照できる
• AutoLoopScreen はこのフレームを OCR 入力として使用する
• Switch 本体との通信・自動操作は行わない
"""
from __future__ import annotations

import io
import queue

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.scrollview import ScrollView


class StreamScreen(ScrollView):
    """USB キャプチャー映像表示タブ。"""

    _FPS_TARGET = 30          # 表示フレームレート目標
    _FRAME_QUEUE_SIZE = 3     # フレームキューの最大サイズ

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._frame_queue: queue.Queue[bytes] = queue.Queue(
            maxsize=self._FRAME_QUEUE_SIZE
        )
        self._update_event = None
        self._running = False

    def on_kv_post(self, base_widget) -> None:
        app = App.get_running_app()
        if not app.uvc.is_available():
            self.ids.start_btn.disabled = True
            self.ids.start_btn.text = "USBキャプチャー (Android 専用)"
            self._set_status(
                "USB キャプチャーはAndroid端末でのみ利用できます。\n"
                "デスクトップではこの機能は使用できません。"
            )

    # ------------------------------------------------------------------ #
    # 公開プロパティ (AutoLoopScreen からも参照)
    # ------------------------------------------------------------------ #

    @property
    def running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------ #
    # ストリーミング開始 / 停止
    # ------------------------------------------------------------------ #

    def _toggle_stream(self) -> None:
        if self._running:
            self._stop_stream()
        else:
            self._start_stream()

    def _start_stream(self) -> None:
        app = App.get_running_app()
        self._set_status("接続中... キャプチャーボードを検索しています")
        self.ids.start_btn.disabled = True

        def on_frame(jpeg: bytes) -> None:
            # Camera2 バックグラウンドスレッドから呼ばれる
            try:
                self._frame_queue.put_nowait(jpeg)
            except queue.Full:
                # キューが溢れたら古いフレームを捨て新しいものを入れる
                try:
                    self._frame_queue.get_nowait()
                    self._frame_queue.put_nowait(jpeg)
                except queue.Empty:
                    pass

        def on_error(msg: str) -> None:
            Clock.schedule_once(lambda dt: self._on_stream_error(msg))

        ok = app.uvc.start(on_frame=on_frame, on_error=on_error)
        if ok:
            self._running = True
            self._update_event = Clock.schedule_interval(
                self._update_texture, 1.0 / self._FPS_TARGET
            )
            self.ids.start_btn.text = "ストリーミング停止"
            self.ids.start_btn.disabled = False
            self._set_status("ストリーミング中 (Switch の映像が表示されます)")
        else:
            self.ids.start_btn.disabled = False

    def _stop_stream(self) -> None:
        app = App.get_running_app()
        app.uvc.stop()
        if self._update_event:
            self._update_event.cancel()
            self._update_event = None
        self._running = False
        self.ids.start_btn.text = "ストリーミング開始"
        self._set_status("停止しました")

    def _on_stream_error(self, msg: str) -> None:
        self._running = False
        self.ids.start_btn.text = "ストリーミング開始"
        self.ids.start_btn.disabled = False
        self._set_status(f"エラー: {msg}")

    # ------------------------------------------------------------------ #
    # Kivy テクスチャ更新 (メインスレッド / Clock.schedule_interval)
    # ------------------------------------------------------------------ #

    def _update_texture(self, dt: float) -> None:
        try:
            jpeg = self._frame_queue.get_nowait()
        except queue.Empty:
            return
        try:
            from kivy.core.image import Image as CoreImage
            buf = io.BytesIO(jpeg)
            core_img = CoreImage(buf, ext="jpg")
            self.ids.stream_view.texture = core_img.texture
        except Exception:
            pass  # デコード失敗は無視して次フレームを待つ

    # ------------------------------------------------------------------ #
    # ヘルパー
    # ------------------------------------------------------------------ #

    def _set_status(self, text: str) -> None:
        self.ids.status_label.text = text
