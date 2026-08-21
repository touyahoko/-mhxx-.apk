"""Arduino Leonardo 通信ブリッジ  (USB シリアル専用)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
接続構成 (写真のとおり)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  スマホ (USB-C)
    └─ OTG アダプター (USB-C → USB-A)
        └─ ANYOYO キャプチャーカード / USB ハブ
            ├─ USB-A ポート → Arduino Leonardo
            │                  ├─ CDC シリアル … スマホ側が制御コマンドを送受信
            │                  └─ HID ゲームパッド … Switch が「Proコントローラー」と認識
            └─ 映像入力 (Switch USB-C) → UVC カメラとしてスマホへ

  ANYOYO はハブとして機能し、スマホ (USB ホスト) から見ると:
    ・UVC カメラ   → stream_screen.py が映像として表示
    ・CDC シリアル → このブリッジが Arduino と通信

  Arduino Leonardo の USB ポートは「コンポジット USB デバイス」として動作:
    ・Switch 側: USB HID Gamepad (Pro Controller として認識)
    ・スマホ側 : CDC/ACM シリアル (コマンド受信)
  これにより 1 本の USB ケーブルで両方を同時に実現する。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
コマンド仕様 (改行区切り)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  送信 (スマホ → Arduino):
    READY              接続確認       → "OK"
    PRESS:A / B / X / Y / L / R / ZL / ZR
    PRESS:PLUS / MINUS / HOME / UP / DOWN / LEFT / RIGHT
    HOLD:A:<n>         n フレーム保持 → "OK"
    MASH:A:<n>         n 回マッシュ   → "OK"
    WAIT:<n>           n フレーム待機 → "OK"
    SEQ:APPRAISE       鑑定シーケンス → "DONE:APPRAISE"
    SEQ:BACK           戻りシーケンス → "DONE:BACK"
    STOP               中断           → "OK"
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Callable, Optional

try:
    from jnius import autoclass
    _ANDROID = True
except Exception:
    _ANDROID = False

# Arduino Leonardo の USB VID / PID
_ARDUINO_VID = 0x2341
_ARDUINO_PIDS = {0x8036, 0x0036}   # CDC モード / bootloader
_CDC_BAUD    = 115200
_TIMEOUT_MS  = 500
_READ_MS     = 100


class ArduinoBridge:
    """
    スマホ → OTG → ANYOYO ハブ → Arduino Leonardo (CDC シリアル) の
    USB シリアル通信を管理する。

    使い方:
        bridge = ArduinoBridge()
        bridge.connect(on_connected=..., on_error=...)
        resp = bridge.send_sync("READY")   # → "OK"
        bridge.send("SEQ:APPRAISE", on_done=lambda r: ...)
        bridge.disconnect()
    """

    def __init__(self) -> None:
        self._connected  = False
        self._running    = False
        self._send_q: queue.Queue[tuple[str, Optional[Callable]]] = queue.Queue()
        self._response_q: queue.Queue[str] = queue.Queue()
        self._async_cbs: list[tuple[str, Callable]] = []
        self._cb_lock    = threading.Lock()
        self._reader: Optional[threading.Thread] = None
        self._writer: Optional[threading.Thread] = None
        # Android USB
        self._usb_conn  = None
        self._ep_in     = None
        self._ep_out    = None
        self._usb_iface = None

    # ------------------------------------------------------------------ #
    # 接続 / 切断
    # ------------------------------------------------------------------ #

    def connect(
        self,
        on_connected: Callable[[], None],
        on_error: Callable[[str], None],
    ) -> None:
        """OTG ハブ経由の Arduino を探して非同期で接続する。"""
        threading.Thread(
            target=self._connect_task,
            args=(on_connected, on_error),
            daemon=True,
        ).start()

    def _connect_task(
        self,
        on_connected: Callable[[], None],
        on_error: Callable[[str], None],
    ) -> None:
        if not _ANDROID:
            on_error("USB シリアルは Android 実機のみ対応です")
            return
        try:
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            UsbConstants   = autoclass("android.hardware.usb.UsbConstants")
            ctx        = PythonActivity.mActivity
            usb_mgr    = ctx.getSystemService("usb")

            # ── Arduino Leonardo を VID/PID で探す ──
            device = None
            dev_list = usb_mgr.getDeviceList()
            it = dev_list.values().iterator()
            while it.hasNext():
                d = it.next()
                if d.getVendorId() == _ARDUINO_VID and d.getProductId() in _ARDUINO_PIDS:
                    device = d
                    break

            if device is None:
                on_error(
                    "Arduino Leonardo が見つかりません。\n"
                    "・ANYOYO ハブの USB-A ポートに Leonardo が刺さっているか確認\n"
                    "・OTG アダプターがスマホに刺さっているか確認\n"
                    "・Leonardo の電源 LED が点灯しているか確認"
                )
                return

            if not usb_mgr.hasPermission(device):
                on_error(
                    "Arduino へのアクセス権限がありません。\n"
                    "USB 機器接続時に表示される権限ダイアログで「許可」を選択してください。\n"
                    "（再接続すると再度ダイアログが表示されます）"
                )
                return

            conn = usb_mgr.openDevice(device)
            if conn is None:
                on_error("Arduino を開けませんでした（接続を確認してください）")
                return

            # ── CDC Data インターフェース (class=0x0A) を探す ──
            data_iface = ep_in = ep_out = None
            for i in range(device.getInterfaceCount()):
                iface = device.getInterface(i)
                if iface.getInterfaceClass() == 0x0A:          # CDC Data
                    data_iface = iface
                    for e in range(iface.getEndpointCount()):
                        ep = iface.getEndpoint(e)
                        if ep.getDirection() == UsbConstants.USB_DIR_IN:
                            ep_in  = ep
                        else:
                            ep_out = ep
                    break

            if data_iface is None or ep_in is None or ep_out is None:
                conn.close()
                on_error(
                    "CDC Data エンドポイントが見つかりません。\n"
                    "Arduino に mhxx_controller スケッチが書き込まれているか確認してください。"
                )
                return

            if not conn.claimInterface(data_iface, True):
                conn.close()
                on_error("インターフェースの排他取得に失敗しました")
                return

            # ── CDC SET_LINE_CODING: 115200bps / 8N1 ──
            lc = bytearray([0x00, 0xC2, 0x01, 0x00, 0x00, 0x00, 0x08])
            conn.controlTransfer(0x21, 0x20, 0, 0, lc, 7, _TIMEOUT_MS)
            # SET_CONTROL_LINE_STATE: DTR=1 (Arduino リセット解除)
            conn.controlTransfer(0x21, 0x22, 0x01, 0, None, 0, _TIMEOUT_MS)

            self._usb_conn  = conn
            self._ep_in     = ep_in
            self._ep_out    = ep_out
            self._usb_iface = data_iface
            self._connected = True
            self._running   = True

            self._reader = threading.Thread(target=self._read_loop, daemon=True)
            self._writer = threading.Thread(target=self._write_loop, daemon=True)
            self._reader.start()
            self._writer.start()

            time.sleep(1.2)   # Arduino リセット + 起動完了待ち
            on_connected()

        except Exception as exc:
            on_error(f"接続エラー: {exc}")

    def disconnect(self) -> None:
        self._running   = False
        self._connected = False
        self._send_q.put(("__STOP__", None))
        if self._usb_conn:
            try:
                if self._usb_iface:
                    self._usb_conn.releaseInterface(self._usb_iface)
                self._usb_conn.close()
            except Exception:
                pass
            self._usb_conn = None

    @property
    def connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------ #
    # コマンド送信
    # ------------------------------------------------------------------ #

    def send(
        self,
        command: str,
        on_done: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """コマンドをキューに積む（ノンブロッキング）。"""
        if not self._connected:
            return False
        self._send_q.put((command, on_done))
        return True

    def send_sync(self, command: str, timeout: float = 8.0) -> str:
        """コマンドを送って応答を同期待ちする（ブロッキング）。"""
        result: list[str] = []
        ev = threading.Event()

        def _cb(r: str) -> None:
            result.append(r)
            ev.set()

        if not self.send(command, _cb):
            return ""
        ev.wait(timeout)
        return result[0] if result else ""

    # ------------------------------------------------------------------ #
    # 送受信スレッド
    # ------------------------------------------------------------------ #

    def _write_loop(self) -> None:
        while self._running:
            try:
                cmd, cb = self._send_q.get(timeout=0.5)
                if cmd == "__STOP__":
                    break
                data = (cmd.strip() + "\n").encode("ascii")
                buf  = bytearray(data)
                ok   = False
                if self._usb_conn and self._ep_out:
                    n  = self._usb_conn.bulkTransfer(
                        self._ep_out, buf, len(buf), _TIMEOUT_MS
                    )
                    ok = n >= 0
                if ok and cb is not None:
                    with self._cb_lock:
                        self._async_cbs.append((cmd, cb))
            except queue.Empty:
                continue

    def _read_loop(self) -> None:
        if not _ANDROID:
            return
        pending = ""
        buf = bytearray(64)
        while self._running:
            if self._usb_conn is None or self._ep_in is None:
                time.sleep(0.05)
                continue
            n = self._usb_conn.bulkTransfer(
                self._ep_in, buf, 64, _READ_MS
            )
            if n <= 0:
                continue
            pending += bytes(buf[:n]).decode("ascii", errors="ignore")
            while "\n" in pending:
                line, pending = pending.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                self._response_q.put(line)
                with self._cb_lock:
                    if self._async_cbs:
                        _cmd, cb = self._async_cbs.pop(0)
                        threading.Thread(target=cb, args=(line,), daemon=True).start()

    # ------------------------------------------------------------------ #
    # 診断ユーティリティ
    # ------------------------------------------------------------------ #

    @staticmethod
    def list_usb_devices() -> list[dict]:
        """
        接続中の USB デバイス一覧を返す（デバッグ・確認用）。
        Returns: [{"name": str, "vid": int, "pid": int, "is_arduino": bool}]
        """
        if not _ANDROID:
            return [{"name": "Arduino Leonardo (テスト用)", "vid": 0x2341, "pid": 0x8036, "is_arduino": True}]
        try:
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            ctx     = PythonActivity.mActivity
            usb_mgr = ctx.getSystemService("usb")
            result  = []
            dev_list = usb_mgr.getDeviceList()
            it = dev_list.values().iterator()
            while it.hasNext():
                d = it.next()
                vid = d.getVendorId()
                pid = d.getProductId()
                result.append({
                    "name"       : d.getProductName() or d.getDeviceName() or "?",
                    "vid"        : vid,
                    "pid"        : pid,
                    "is_arduino" : (vid == _ARDUINO_VID and pid in _ARDUINO_PIDS),
                })
            return result
        except Exception:
            return []
