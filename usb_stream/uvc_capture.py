"""
usb_stream/uvc_capture.py
USB キャプチャーボード映像取得モジュール

Android Camera2 API の「外部カメラ (LENS_FACING_EXTERNAL)」として
USB OTG 経由で接続された UVC キャプチャーボードにアクセスし、
JPEG フレームを連続取得する。

対応環境: Android 9 (API 28) 以降 + USB OTG 接続の UVC キャプチャーボード
デスクトップ環境では is_available() が False を返し、全機能が無効化される。

使い方:
    cap = UVCCapture()
    cap.start(on_frame=my_cb, on_error=err_cb)
    frame_jpeg = cap.latest_frame  # 最新フレーム (bytes)
    cap.stop()
"""
from __future__ import annotations

import array as array_mod
import threading
from typing import Callable, Optional

try:
    from jnius import autoclass, PythonJavaClass, java_method, JArray

    _ANDROID = True
except Exception:
    _ANDROID = False


def is_available() -> bool:
    """Android Camera2 が使える環境かどうか。"""
    return _ANDROID


# ---------------------------------------------------------------------------
# Android Camera2 コールバック実装 (pyjnius PythonJavaClass)
# ---------------------------------------------------------------------------

if _ANDROID:

    class _CameraStateCallback(PythonJavaClass):
        """CameraDevice.StateCallback の Python 実装。"""
        __javainterfaces__ = ["android/hardware/camera2/CameraDevice$StateCallback"]
        __javacontext__ = "app"

        def __init__(self, on_opened, on_error, on_disconnected):
            super().__init__()
            self._opened = on_opened
            self._error = on_error
            self._disconnected = on_disconnected

        @java_method("(Landroid/hardware/camera2/CameraDevice;)V")
        def onOpened(self, camera):
            self._opened(camera)

        @java_method("(Landroid/hardware/camera2/CameraDevice;I)V")
        def onError(self, camera, error):
            self._error(f"CameraDevice エラーコード: {error}")

        @java_method("(Landroid/hardware/camera2/CameraDevice;)V")
        def onDisconnected(self, camera):
            self._disconnected(camera)

    class _SessionStateCallback(PythonJavaClass):
        """CameraCaptureSession.StateCallback の Python 実装。"""
        __javainterfaces__ = [
            "android/hardware/camera2/CameraCaptureSession$StateCallback"
        ]
        __javacontext__ = "app"

        def __init__(self, on_configured, on_failed):
            super().__init__()
            self._configured = on_configured
            self._failed = on_failed

        @java_method(
            "(Landroid/hardware/camera2/CameraCaptureSession;)V"
        )
        def onConfigured(self, session):
            self._configured(session)

        @java_method(
            "(Landroid/hardware/camera2/CameraCaptureSession;)V"
        )
        def onConfigureFailed(self, session):
            self._failed("セッション設定に失敗しました")

    class _ImageAvailableListener(PythonJavaClass):
        """ImageReader.OnImageAvailableListener の Python 実装。"""
        __javainterfaces__ = [
            "android/media/ImageReader$OnImageAvailableListener"
        ]
        __javacontext__ = "app"

        def __init__(self, frame_cb: Callable[[bytes], None]):
            super().__init__()
            self._cb = frame_cb

        @java_method("(Landroid/media/ImageReader;)V")
        def onImageAvailable(self, reader):
            try:
                image = reader.acquireLatestImage()
                if image is None:
                    return
                try:
                    planes = image.getPlanes()
                    buf = planes[0].getBuffer()
                    size = buf.remaining()
                    if size <= 0:
                        return
                    # Java byte[] に転写 (signed byte, -128 〜 127)
                    java_arr = JArray("b")(size)
                    buf.get(java_arr)
                    # array_mod.array('b', ...) でバッファプロトコル経由コピー、
                    # tobytes() で生バイト列を取得 (符号ビットはそのまま保持)
                    data = array_mod.array("b", java_arr).tobytes()
                    if self._cb:
                        self._cb(data)
                finally:
                    image.close()
            except Exception:
                pass  # フレーム取得失敗は無視 (次フレームで回復)


# ---------------------------------------------------------------------------
# メインクラス
# ---------------------------------------------------------------------------

class UVCCapture:
    """
    USB キャプチャーボード (UVC, 外部カメラ) から JPEG フレームを取得。

    Camera2 の外部カメラ機能を使うため Android 9+ が必要。
    キャプチャーボードは USB OTG 経由で接続し、OS に UVC デバイスとして
    認識させる必要がある (認識には通常数秒かかる)。
    """

    # JPEG キャプチャー解像度
    CAPTURE_WIDTH = 1280
    CAPTURE_HEIGHT = 720

    def is_available(self) -> bool:
        """Android Camera2 が使える環境かどうか (screen から呼べるインスタンスメソッド版)。"""
        return _ANDROID

    def __init__(self):
        self._running = False
        self._latest_frame: Optional[bytes] = None
        self._camera_device = None
        self._capture_session = None
        self._image_reader = None
        self._handler_thread = None
        self._handler = None
        self._surface = None
        # コールバック参照 (GC 防止)
        self._cb_state: Optional["_CameraStateCallback"] = None
        self._cb_session: Optional["_SessionStateCallback"] = None
        self._cb_image: Optional["_ImageAvailableListener"] = None
        self._on_error: Optional[Callable[[str], None]] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # 公開 API
    # ------------------------------------------------------------------ #

    @property
    def latest_frame(self) -> Optional[bytes]:
        """最新の JPEG フレーム (bytes)。まだ届いていなければ None。"""
        return self._latest_frame

    @property
    def running(self) -> bool:
        return self._running

    def find_external_camera_id(self) -> Optional[str]:
        """
        外部カメラ (キャプチャーボード) の camera ID を返す。
        見つからなければ None。
        """
        if not is_available():
            return None
        try:
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Context = autoclass("android.content.Context")
            CameraCharacteristics = autoclass(
                "android.hardware.camera2.CameraCharacteristics"
            )
            CameraMetadata = autoclass(
                "android.hardware.camera2.CameraMetadata"
            )
            activity = PythonActivity.mActivity
            cam_mgr = activity.getSystemService(Context.CAMERA_SERVICE)
            for cid in cam_mgr.getCameraIdList():
                chars = cam_mgr.getCameraCharacteristics(cid)
                facing = chars.get(CameraCharacteristics.LENS_FACING)
                if facing == CameraMetadata.LENS_FACING_EXTERNAL:
                    return cid
        except Exception:
            pass
        return None

    def start(
        self,
        on_frame: Callable[[bytes], None],
        on_error: Callable[[str], None],
    ) -> bool:
        """
        キャプチャー開始。成功すれば True、失敗すれば on_error を呼んで False。
        """
        if not is_available():
            on_error(
                "USB キャプチャーは Android 端末でのみ利用できます"
            )
            return False
        if self._running:
            return True

        self._on_error = on_error

        camera_id = self.find_external_camera_id()
        if camera_id is None:
            on_error(
                "外部カメラ（キャプチャーボード）が見つかりません。\n"
                "• USB OTG でキャプチャーボードを接続してください\n"
                "• Android 9 以降が必要です\n"
                "• 接続直後は認識に数秒かかります"
            )
            return False

        try:
            self._open_camera(camera_id, on_frame, on_error)
            return True
        except Exception as exc:
            on_error(f"カメラ起動エラー: {exc}")
            return False

    def stop(self):
        """キャプチャー停止・リソース解放。"""
        self._running = False
        self._latest_frame = None
        for attr, method in [
            ("_capture_session", "close"),
            ("_camera_device", "close"),
            ("_image_reader", "close"),
            ("_handler_thread", "quitSafely"),
        ]:
            obj = getattr(self, attr)
            if obj is not None:
                try:
                    getattr(obj, method)()
                except Exception:
                    pass
                setattr(self, attr, None)
        self._handler = None
        self._surface = None
        self._cb_state = None
        self._cb_session = None
        self._cb_image = None

    # ------------------------------------------------------------------ #
    # 内部実装
    # ------------------------------------------------------------------ #

    def _open_camera(self, camera_id, on_frame, on_error):
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Context = autoclass("android.content.Context")
        HandlerThread = autoclass("android.os.HandlerThread")
        Handler = autoclass("android.os.Handler")
        ImageReader = autoclass("android.media.ImageReader")
        ImageFormat = autoclass("android.graphics.ImageFormat")

        activity = PythonActivity.mActivity
        cam_mgr = activity.getSystemService(Context.CAMERA_SERVICE)

        # バックグラウンドスレッドの Handler (Camera2 コールバック受け取り用)
        ht = HandlerThread("UVCCaptureThread")
        ht.start()
        handler = Handler(ht.getLooper())
        self._handler_thread = ht
        self._handler = handler

        # ImageReader (JPEG, 2 バッファ)
        reader = ImageReader.newInstance(
            self.CAPTURE_WIDTH, self.CAPTURE_HEIGHT, ImageFormat.JPEG, 2
        )
        self._image_reader = reader
        self._surface = reader.getSurface()

        capture = self  # クロージャで self を参照

        def _on_frame(data: bytes):
            with capture._lock:
                capture._latest_frame = data
            on_frame(data)

        self._cb_image = _ImageAvailableListener(_on_frame)
        reader.setOnImageAvailableListener(self._cb_image, handler)

        def _on_opened(camera):
            capture._camera_device = camera
            capture._create_session(camera, on_error)

        def _on_cam_error(msg: str):
            on_error(msg)
            capture.stop()

        def _on_disconnected(camera):
            capture.stop()

        self._cb_state = _CameraStateCallback(
            _on_opened, _on_cam_error, _on_disconnected
        )
        cam_mgr.openCamera(camera_id, self._cb_state, handler)

    def _create_session(self, camera_device, on_error):
        CaptureRequest = autoclass("android.hardware.camera2.CaptureRequest")
        ArrayList = autoclass("java.util.ArrayList")

        surfaces = ArrayList()
        surfaces.add(self._surface)

        capture = self

        def _on_configured(session):
            capture._capture_session = session
            try:
                builder = camera_device.createCaptureRequest(
                    CaptureRequest.TEMPLATE_PREVIEW
                )
                builder.addTarget(capture._surface)
                request = builder.build()
                session.setRepeatingRequest(request, None, capture._handler)
                capture._running = True
            except Exception as exc:
                on_error(f"リピートリクエスト設定エラー: {exc}")

        def _on_failed(msg: str):
            on_error(msg)

        self._cb_session = _SessionStateCallback(_on_configured, _on_failed)
        camera_device.createCaptureSession(
            surfaces, self._cb_session, self._handler
        )
