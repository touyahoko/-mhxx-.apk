"""
arduino/serial_ctrl.py
Arduino Leonardo USB シリアル通信モジュール

Android USB Host API (pyjnius 経由) を使い、USB OTG で接続した
Arduino Leonardo とシリアル通信する。

接続プロトコル (115200 bps / 8N1):
  スマホ → Arduino:  "NEXT\\n"  … 次のお守りへ進む
  スマホ → Arduino:  "STOP\\n"  … ループ停止
  Arduino → スマホ:  "READY\\n" … お守り確認画面が表示された
  Arduino → スマホ:  "OK\\n"    … コマンド受理

Arduino の VID/PID:
  Arduino LLC (0x2341)  PID: Leonardo=0x0036 / Leonardo CDC=0x8036
  Arduino SA  (0x2A03)  PID: Leonardo=0x0036
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

# Arduino Leonardo の VID / PID
_ARDUINO_VIDS: set[int] = {0x2341, 0x2A03}
_LEONARDO_PIDS: set[int] = {0x0036, 0x8036}

try:
    from jnius import autoclass as _autoclass
    _ANDROID = True
except Exception:
    _ANDROID = False


def is_available() -> bool:
    """Android USB Host API が利用可能かどうか。"""
    return _ANDROID


class ArduinoCtrl:
    """
    Arduino Leonardo (USB シリアル / CDC-ACM) 通信クラス。

    connect() で接続、send() でコマンド送信、disconnect() で切断。
    受信データは on_message コールバックで 1 行単位に通知される。
    """

    def is_available(self) -> bool:
        """Android USB Host API が利用可能かどうか (screen から呼べるインスタンスメソッド版)。"""
        return _ANDROID

    def __init__(self):
        self._conn = None          # UsbDeviceConnection
        self._ep_in = None         # bulk-in endpoint
        self._ep_out = None        # bulk-out endpoint
        self._data_intf = None     # UsbInterface (CDC Data class)
        self._running = False
        self._read_thread: Optional[threading.Thread] = None
        self._on_message: Optional[Callable[[str], None]] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # 公開 API
    # ------------------------------------------------------------------ #

    @property
    def connected(self) -> bool:
        return self._conn is not None and self._running

    def connect(
        self,
        on_message: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> bool:
        """
        Arduino に接続する。成功すれば True。失敗すれば on_error を呼んで False。
        """
        if not is_available():
            on_error("USB シリアルは Android 端末でのみ利用できます")
            return False
        if self._running:
            return True
        try:
            return self._connect_android(on_message, on_error)
        except Exception as exc:
            on_error(f"接続エラー: {exc}")
            return False

    def disconnect(self):
        """接続を閉じる。"""
        self._running = False
        with self._lock:
            if self._conn is not None:
                if self._data_intf is not None:
                    try:
                        self._conn.releaseInterface(self._data_intf)
                    except Exception:
                        pass
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
        self._ep_in = None
        self._ep_out = None
        self._data_intf = None

    def send(self, command: str) -> bool:
        """
        コマンドを送信する (末尾に \\n を付けて一括送信)。
        接続していなければ False を返す。
        """
        with self._lock:
            if self._conn is None or self._ep_out is None:
                return False
            try:
                data = (command.strip() + "\n").encode("utf-8")
                n = self._conn.bulkTransfer(self._ep_out, data, len(data), 500)
                return n == len(data)
            except Exception:
                return False

    # ------------------------------------------------------------------ #
    # 内部実装
    # ------------------------------------------------------------------ #

    def _connect_android(self, on_message, on_error) -> bool:
        PythonActivity = _autoclass("org.kivy.android.PythonActivity")
        Context = _autoclass("android.content.Context")
        UsbConstants = _autoclass("android.hardware.usb.UsbConstants")

        activity = PythonActivity.mActivity
        usb_mgr = activity.getSystemService(Context.USB_SERVICE)
        device_list = usb_mgr.getDeviceList()

        # Arduino Leonardo を VID/PID で探す
        arduino = None
        for name in device_list.keySet():
            dev = device_list.get(name)
            if (
                dev.getVendorId() in _ARDUINO_VIDS
                and dev.getProductId() in _LEONARDO_PIDS
            ):
                arduino = dev
                break

        if arduino is None:
            on_error(
                "Arduino Leonardo が見つかりません。\n"
                "• USB OTG で接続してください\n"
                "• 接続時に表示された「USB デバイスを許可」ダイアログで\n"
                "  「OK」を選んでいることを確認してください"
            )
            return False

        # USB 権限を確認
        if not usb_mgr.hasPermission(arduino):
            on_error(
                "Arduino への USB アクセス権限がありません。\n"
                "「切断→接続」を繰り返し、ダイアログで「OK」を選んでください。"
            )
            return False

        # CDC Data インターフェース (class=0x0A) とエンドポイントを取得
        data_intf = None
        ep_in = None
        ep_out = None

        for i in range(arduino.getInterfaceCount()):
            intf = arduino.getInterface(i)
            if intf.getInterfaceClass() == 0x0A:  # CDC Data
                data_intf = intf
                for j in range(intf.getEndpointCount()):
                    ep = intf.getEndpoint(j)
                    if ep.getType() == UsbConstants.USB_ENDPOINT_XFER_BULK:
                        if ep.getDirection() == UsbConstants.USB_DIR_IN:
                            ep_in = ep
                        else:
                            ep_out = ep
                break

        if data_intf is None or ep_in is None or ep_out is None:
            on_error(
                "CDC-ACM エンドポイントが見つかりません。\n"
                "Arduino Leonardo 用のスケッチが書き込まれているか確認してください。"
            )
            return False

        conn = usb_mgr.openDevice(arduino)
        if conn is None:
            on_error("USB デバイスを開けませんでした。")
            return False

        conn.claimInterface(data_intf, True)

        # ボーレート 115200 / 8N1 を設定 (CDC SetLineCoding)
        line_coding = bytes([
            0x00, 0xC2, 0x01, 0x00,  # 115200 (little-endian 32bit)
            0x00,                     # 1 ストップビット
            0x00,                     # パリティなし
            0x08,                     # データビット 8
        ])
        conn.controlTransfer(0x21, 0x20, 0, 0, line_coding, len(line_coding), 200)

        # DTR + RTS 有効化 (CDC SetControlLineState)
        conn.controlTransfer(0x21, 0x22, 0x03, 0, None, 0, 200)

        self._conn = conn
        self._ep_in = ep_in
        self._ep_out = ep_out
        self._data_intf = data_intf
        self._on_message = on_message
        self._running = True

        # バックグラウンド受信スレッド
        self._read_thread = threading.Thread(
            target=self._read_loop, daemon=True
        )
        self._read_thread.start()
        return True

    def _read_loop(self):
        """Arduino からの 1 行受信ループ (バックグラウンドスレッド)。"""
        buf = bytearray(128)
        line_buf = ""

        while self._running:
            try:
                with self._lock:
                    if self._conn is None:
                        break
                    n = self._conn.bulkTransfer(
                        self._ep_in, buf, len(buf), 200
                    )
                if n > 0:
                    line_buf += buf[:n].decode("utf-8", errors="ignore")
                    while "\n" in line_buf:
                        line, line_buf = line_buf.split("\n", 1)
                        line = line.strip()
                        if line and self._on_message:
                            self._on_message(line)
            except Exception:
                break

        self._running = False
