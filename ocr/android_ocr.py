"""Android の Google ML Kit (オンデバイス・日本語テキスト認識) を
pyjnius 経由で呼び出すブリッジ。

重要な注意:
  このファイルは Android 実機 (またはエミュレータ) 上でしか動作せず、
  このプロジェクトのビルド/テスト環境 (PC上のXvfb) では動作を検証
  できていません。pyjnius の呼び出し規約・ML Kit の公開APIドキュメント
  をもとに作成していますが、実機での動作確認・調整が必要な可能性が
  あります。失敗しても他の画面 (検索/周辺確認/調合スナイプ/狙い目) には
  一切影響しないよう、例外はすべてここで捕捉して呼び出し元にエラー
  メッセージとして返します。

  Switchや他のハードウェアとの通信は一切行いません。処理対象は
  「ユーザーが選んだ/撮影した1枚の画像ファイル」のみです。
"""
from __future__ import annotations

from typing import Callable

try:
    from jnius import autoclass, PythonJavaClass, java_method

    _ANDROID = True
    _IMPORT_ERROR = ""
except Exception as exc:  # noqa: BLE001  (Android以外の環境では必ずここに来る)
    _ANDROID = False
    _IMPORT_ERROR = str(exc)


def is_available() -> bool:
    """この端末でAndroidネイティブOCRが利用可能かどうか。"""
    return _ANDROID


if _ANDROID:

    class _OnSuccessListener(PythonJavaClass):
        __javainterfaces__ = ["com/google/android/gms/tasks/OnSuccessListener"]
        __javacontext__ = "app"

        def __init__(self, callback: Callable[[object], None]) -> None:
            super().__init__()
            self._callback = callback

        @java_method("(Ljava/lang/Object;)V")
        def onSuccess(self, result) -> None:
            self._callback(result)

    class _OnFailureListener(PythonJavaClass):
        __javainterfaces__ = ["com/google/android/gms/tasks/OnFailureListener"]
        __javacontext__ = "app"

        def __init__(self, callback: Callable[[Exception], None]) -> None:
            super().__init__()
            self._callback = callback

        @java_method("(Ljava/lang/Exception;)V")
        def onFailure(self, exception) -> None:
            self._callback(exception)


def recognize_text(
    image_path: str,
    on_result: Callable[[str], None],
    on_error: Callable[[str], None],
) -> None:
    """画像ファイル (image_path) から日本語テキストを認識する。

    非同期API。結果は on_result(text) または on_error(message) で通知
    される (ML KitのTask自体がバックグラウンドで動くため、呼び出し自体は
    メインスレッドから行って問題ない設計になっているはずだが、コール
    バックがどのスレッドで呼ばれるかは端末依存の可能性があるため、
    呼び出し側で Clock.schedule_once を使ってUIスレッドに戻すこと)。
    """
    if not _ANDROID:
        on_error(f"この端末ではAndroidのOCR機能を利用できません ({_IMPORT_ERROR})")
        return
    try:
        InputImage = autoclass("com.google.mlkit.vision.common.InputImage")
        TextRecognition = autoclass("com.google.mlkit.vision.text.TextRecognition")
        JapaneseOptionsBuilder = autoclass(
            "com.google.mlkit.vision.text.japanese.JapaneseTextRecognizerOptions$Builder"
        )
        JavaFile = autoclass("java.io.File")
        Uri = autoclass("android.net.Uri")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")

        activity = PythonActivity.mActivity
        uri = Uri.fromFile(JavaFile(image_path))
        image = InputImage.fromFilePath(activity, uri)

        options = JapaneseOptionsBuilder().build()
        recognizer = TextRecognition.getClient(options)

        def _handle_success(result) -> None:
            try:
                text = result.getText()
            except Exception as exc:  # noqa: BLE001
                on_error(f"認識結果の取得に失敗しました: {exc}")
                return
            on_result(text or "")

        def _handle_failure(exception) -> None:
            try:
                message = exception.getMessage()
            except Exception:  # noqa: BLE001
                message = None
            on_error(message or "OCR処理に失敗しました")

        task = recognizer.process(image)
        task.addOnSuccessListener(_OnSuccessListener(_handle_success))
        task.addOnFailureListener(_OnFailureListener(_handle_failure))
    except Exception as exc:  # noqa: BLE001
        on_error(f"OCR初期化エラー: {exc}")


def recognize_from_bytes(jpeg_bytes: bytes, timeout: float = 10.0) -> str:
    """
    JPEG バイト列から日本語テキストを認識する (同期API)。

    バックグラウンドスレッドから呼ぶ用途向け。
    内部で一時ファイルに書き出してから recognize_text() を呼ぶ。

    Args:
        jpeg_bytes: JPEG 画像データ
        timeout   : 最大待機秒数

    Returns:
        認識テキスト。失敗時は "[エラー] ..." 形式の文字列。
    """
    import threading
    import tempfile
    import os

    result: list[str] = []
    ev = threading.Event()

    def _ok(text: str) -> None:
        result.append(text)
        ev.set()

    def _err(msg: str) -> None:
        result.append(f"[エラー] {msg}")
        ev.set()

    # 一時ファイルに JPEG を書き出す
    try:
        fd, path = tempfile.mkstemp(suffix=".jpg")
        with os.fdopen(fd, "wb") as f:
            f.write(jpeg_bytes)
    except Exception as exc:
        return f"[エラー] 一時ファイル作成失敗: {exc}"

    try:
        recognize_text(path, _ok, _err)
        ev.wait(timeout)
    finally:
        try:
            os.remove(path)
        except Exception:
            pass

    return result[0] if result else "[エラー] タイムアウト"
