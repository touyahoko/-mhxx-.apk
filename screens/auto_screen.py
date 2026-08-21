"""オートタブ ── Arduino 連携 / お守り自動認識ループ

接続構成 (写真の通り):
  スマホ (USB-C)
    └─ OTG アダプター
        └─ ANYOYO ハブ
            ├─ Arduino Leonardo → CDC シリアル (コマンド) + HID (Switch 操作)
            └─ Switch 映像 → UVC カメラ (映像タブ)

動作フロー:
  [開始] → SEQ:APPRAISE → DONE:APPRAISE → OCR → 一致? → 成功 or SEQ:BACK → 繰返し
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from kivy.app import App
from kivy.clock import Clock
from kivy.properties import BooleanProperty, ListProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout

from hardware.arduino_bridge import ArduinoBridge
from hardware.charm_detector import detect_from_texture, TargetCharm, DetectResult
from mhxx_rng import KIND_NAMES, KIND_TABLES, SKILL_NAMES

_MAX_LOG  = 120
_LOOP_MAX = 9999


class AutoScreen(BoxLayout):
    """
    オートタブ画面。

    App 共有属性:
        app.auto_target         : TargetCharm
        app.stream_camera_index : int
        app.stream_crop_ratio   : tuple
    """

    status_text   = StringProperty("未接続  —  OTG ケーブルを接続してから「接続」を押してください")
    conn_btn_text = StringProperty("接続")
    loop_btn_text = StringProperty("▶ 自動ループ開始")
    loop_running  = BooleanProperty(False)
    is_connected  = BooleanProperty(False)
    log_lines     = ListProperty([])
    target_text   = StringProperty("目標未設定 (映像タブで OCR 後に自動設定 / 以下で直接入力)")
    usb_dev_labels = ListProperty(["── USB デバイス一覧を更新してください ──"])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._bridge: Optional[ArduinoBridge] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._stop_loop   = threading.Event()
        Clock.schedule_once(self._init_ui, 0)

    # ------------------------------------------------------------------ #
    # 初期化
    # ------------------------------------------------------------------ #

    def _init_ui(self, _dt):
        app = App.get_running_app()
        for attr, default in [
            ("auto_target",         None),
            ("stream_camera_index", 2),
            ("stream_crop_ratio",   (0.1, 0.25, 0.9, 0.75)),
        ]:
            if not hasattr(app, attr):
                setattr(app, attr, default)
        self._refresh_target_text()
        self._refresh_usb_devices()

    # ------------------------------------------------------------------ #
    # 目標表示
    # ------------------------------------------------------------------ #

    def _refresh_target_text(self):
        app = App.get_running_app()
        t: Optional[TargetCharm] = getattr(app, "auto_target", None)
        if t is None:
            self.target_text = "目標未設定"
            return
        tbl  = KIND_TABLES[t.kind]
        s1   = SKILL_NAMES[tbl.skill1[t.skill1_idx]].strip()
        op   = "=" if t.pts_exact else "≥"
        s2   = ""
        if t.skill2_idx >= 0:
            sn = SKILL_NAMES[tbl.skill2[t.skill2_idx]].strip()
            s2 = f"  {sn}{op}{t.skill2_pts}"
        slot = f"  スロット{t.slot}" if t.slot >= 0 else "  スロット不問"
        self.target_text = f"[{KIND_NAMES[t.kind]}]  {s1}{op}{t.skill1_pts}{s2}{slot}"

    # ------------------------------------------------------------------ #
    # USB デバイス一覧
    # ------------------------------------------------------------------ #

    def _refresh_usb_devices(self):
        devs = ArduinoBridge.list_usb_devices()
        if devs:
            labels = []
            for d in devs:
                mark = "✔ Arduino" if d["is_arduino"] else "   "
                labels.append(f'{mark}  {d["name"]}  VID={d["vid"]:04X} PID={d["pid"]:04X}')
        else:
            labels = ["（接続された USB デバイスなし — OTG ケーブルを確認）"]
        self.usb_dev_labels = labels

    # ------------------------------------------------------------------ #
    # 接続 / 切断
    # ------------------------------------------------------------------ #

    def toggle_connect(self):
        if self.is_connected:
            self._do_disconnect()
        else:
            self._do_connect()

    def _do_connect(self):
        if self._bridge is None:
            self._bridge = ArduinoBridge()
        self.status_text = "接続中..."
        self._log("OTG ハブ経由で Arduino Leonardo を検索中...")

        def on_ok():
            Clock.schedule_once(lambda dt: self._on_connected())

        def on_err(msg: str):
            Clock.schedule_once(lambda dt, m=msg: self._on_connect_error(m))

        self._bridge.connect(on_connected=on_ok, on_error=on_err)

    def _on_connected(self):
        self.is_connected   = True
        self.conn_btn_text  = "切断"
        self.status_text    = "✔ Arduino 接続済み (OTG → ANYOYO ハブ経由)"
        self._log("✔ Arduino Leonardo 接続成功")

        def _ping():
            resp = self._bridge.send_sync("READY", timeout=4.0)
            Clock.schedule_once(
                lambda dt, r=resp: self._log(
                    f"  READY → {r}" if r else
                    "  READY → 応答なし（スケッチが書き込まれているか確認）"
                )
            )
        threading.Thread(target=_ping, daemon=True).start()

    def _on_connect_error(self, msg: str):
        self.status_text = "✘ 接続失敗"
        self._log(f"✘ 接続エラー:\n  {msg}")
        self._bridge = None

    def _do_disconnect(self):
        if self._bridge:
            self._bridge.disconnect()
            self._bridge = None
        self.is_connected  = False
        self.conn_btn_text = "接続"
        self.status_text   = "切断済み"
        self._log("切断しました")

    # ------------------------------------------------------------------ #
    # 自動ループ
    # ------------------------------------------------------------------ #

    def toggle_loop(self):
        if self.loop_running:
            self._stop_loop.set()
            self.loop_btn_text = "停止中..."
        else:
            self._start_loop()

    def _start_loop(self):
        if not self.is_connected:
            self._log("⚠ まず Arduino を接続してください")
            return
        app    = App.get_running_app()
        target = getattr(app, "auto_target", None)
        if target is None:
            self._log("⚠ 目標お守りが未設定です")
            self._log("  映像タブでテスト OCR を実行するか、以下の入力欄で直接設定してください")
            return
        if self._get_live_camera() is None:
            self._log("⚠ 映像タブのカメラを先に開始してください")
            return

        self.loop_running  = True
        self.loop_btn_text = "■ 停止"
        self._stop_loop.clear()
        self._refresh_target_text()
        self._log("━━━━ 自動ループ開始 ━━━━")
        self._log(f"目標: {self.target_text}")

        self._loop_thread = threading.Thread(
            target=self._loop_body, args=(target,), daemon=True
        )
        self._loop_thread.start()

    def _loop_body(self, target: TargetCharm):
        try:
            for attempt in range(1, _LOOP_MAX + 1):
                if self._stop_loop.is_set():
                    Clock.schedule_once(lambda dt: self._on_loop_ended("手動停止"))
                    return

                Clock.schedule_once(
                    lambda dt, n=attempt: self._log(f"[{n:4d}回目] 鑑定シーケンス送信...")
                )

                # 1. 鑑定
                resp = self._bridge.send_sync("SEQ:APPRAISE", timeout=10.0)
                if not resp.startswith("DONE"):
                    Clock.schedule_once(
                        lambda dt, r=resp: self._log(f"  ✘ Arduino 応答異常: {r!r}")
                    )
                    Clock.schedule_once(lambda dt: self._on_loop_ended("Arduino エラー"))
                    return

                if self._stop_loop.is_set():
                    Clock.schedule_once(lambda dt: self._on_loop_ended("手動停止"))
                    return

                # 2. 画面安定待ち
                time.sleep(0.3)

                # 3. OCR → 判定
                result = self._detect(target)
                if result is None:
                    Clock.schedule_once(lambda dt: self._log("  カメラ取得失敗 → スキップ"))
                    self._bridge.send_sync("SEQ:BACK", timeout=6.0)
                    continue

                Clock.schedule_once(
                    lambda dt, r=result: self._log(f"  OCR: {r.summary}")
                )

                if result.success:
                    Clock.schedule_once(
                        lambda dt, n=attempt: self._on_loop_success(n)
                    )
                    return

                # 4. 不一致 → キャンセルして次へ
                self._bridge.send_sync("SEQ:BACK", timeout=6.0)

            Clock.schedule_once(
                lambda dt: self._on_loop_ended(f"最大試行 {_LOOP_MAX} 回に達しました")
            )
        except Exception as exc:
            Clock.schedule_once(
                lambda dt, e=exc: self._on_loop_ended(f"例外: {e}")
            )

    def _detect(self, target: TargetCharm) -> Optional[DetectResult]:
        cam = self._get_live_camera()
        if cam is None or cam.texture is None:
            return None
        app  = App.get_running_app()
        crop = tuple(getattr(app, "stream_crop_ratio", (0.0, 0.0, 1.0, 1.0)))
        return detect_from_texture(cam.texture, target, crop)

    def _get_live_camera(self):
        try:
            scr = App.get_running_app().root.ids.get("stream_screen")
            if scr and hasattr(scr.ids, "live_camera"):
                return scr.ids.live_camera
        except Exception:
            pass
        return None

    def _on_loop_success(self, attempt: int):
        self.loop_running  = False
        self.loop_btn_text = "▶ 自動ループ開始"
        self.status_text   = f"✔ 成功！ {attempt} 回目で目標一致"
        self._log(f"━━━━ 成功！ {attempt} 回で目標お守りを確認 ━━━━")

    def _on_loop_ended(self, reason: str):
        self.loop_running  = False
        self.loop_btn_text = "▶ 自動ループ開始"
        self.status_text   = f"停止: {reason}"
        self._log(f"━━━━ 停止: {reason} ━━━━")

    # ------------------------------------------------------------------ #
    # 目標直接設定
    # ------------------------------------------------------------------ #

    def apply_target_from_fields(self):
        app = App.get_running_app()
        try:
            kind = app.kind
            tbl  = KIND_TABLES[kind]

            def _int(iid, default=0):
                raw = (getattr(self.ids, iid, None).text or "").strip()
                return int(raw) if raw else default

            s1_idx = max(0, min(_int("inp_s1_idx"), len(tbl.skill1) - 1))
            s1_pts = max(1, _int("inp_s1_pts", 1))
            s2_raw = (getattr(self.ids, "inp_s2_idx", None).text or "").strip()
            s2_idx = int(s2_raw) if s2_raw else -1
            if s2_idx >= 0:
                s2_idx = max(0, min(s2_idx, len(tbl.skill2) - 1))
            s2_pts = max(0, _int("inp_s2_pts"))
            slot_raw = (getattr(self.ids, "inp_slot", None).text or "").strip()
            slot = int(slot_raw) if slot_raw else -1

            app.auto_target = TargetCharm(
                kind=kind, skill1_idx=s1_idx, skill1_pts=s1_pts,
                skill2_idx=s2_idx, skill2_pts=s2_pts, slot=slot,
            )
            self._refresh_target_text()
            self._log(f"目標設定: {self.target_text}")
        except Exception as exc:
            self._log(f"⚠ 目標設定エラー: {exc}")

    # ------------------------------------------------------------------ #
    # ログ
    # ------------------------------------------------------------------ #

    def _log(self, msg: str):
        lines = list(self.log_lines) + [msg]
        self.log_lines = lines[-_MAX_LOG:]

    def clear_log(self):
        self.log_lines = []
