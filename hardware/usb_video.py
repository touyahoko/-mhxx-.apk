"""USB キャプチャーカード映像ユーティリティ (Android向け)

Android Camera2 API 経由で接続中のカメラ一覧 (外部UVCを含む) を取得し、
Kivy の Camera ウィジェットが使うカメラインデックスへ変換する。

UVC対応のUSBキャプチャーカードを OTG ハブ経由でスマホに繋ぐと、
多くのAndroid端末では Camera2 API に「外部カメラ (LENS_FACING=2)」
として現れる。カメラのインデックスは端末や接続順序によって変わるため、
アプリ内でユーザーが手動で選択できるようにしてある。

接続構成 (写真の通り):
    スマホ (USB-C)
      └─ OTG アダプター (USB-C → USB-A)
          └─ ANYOYO キャプチャーカード / USB ハブ
              ├─ 映像入力 (Switch USB-C) → UVC カメラ ← このモジュールで映像取得
              └─ USB-A ポート → Arduino Leonardo (arduino_bridge.py が担当)
"""
from __future__ import annotations

from typing import Optional

try:
    from jnius import autoclass
    _ANDROID = True
except Exception:
    _ANDROID = False


def list_cameras() -> list[dict]:
    """
    Android Camera2 API で利用可能なカメラを列挙する。

    Returns:
        list of dict:
            id     (str)  : Camera2 カメラID
            index  (int)  : Kivy Camera ウィジェット用の連番インデックス
            facing (int)  : 0=背面 1=前面 2=外部(USB/UVC)
            label  (str)  : UI 表示用の日本語ラベル
    """
    if not _ANDROID:
        # PC テスト用フォールバック
        return [
            {"id": "0", "index": 0, "facing": 0, "label": "[0] 背面カメラ"},
            {"id": "1", "index": 1, "facing": 1, "label": "[1] 前面カメラ"},
        ]

    result: list[dict] = []
    try:
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        CameraCharacteristics = autoclass(
            "android.hardware.camera2.CameraCharacteristics"
        )
        ctx = PythonActivity.mActivity
        manager = ctx.getSystemService("camera")
        cam_ids = manager.getCameraIdList()
        LENS_FACING = CameraCharacteristics.LENS_FACING
        facing_labels = {0: "背面カメラ", 1: "前面カメラ", 2: "外部(USB)カメラ"}
        for idx, cam_id in enumerate(cam_ids):
            try:
                chars = manager.getCameraCharacteristics(cam_id)
                facing = chars.get(LENS_FACING)
                label = facing_labels.get(facing, "不明カメラ")
                result.append({
                    "id": cam_id,
                    "index": idx,
                    "facing": facing,
                    "label": f"[{idx}] {label}  (id={cam_id})",
                })
            except Exception:
                result.append({
                    "id": cam_id,
                    "index": idx,
                    "facing": -1,
                    "label": f"[{idx}] カメラ id={cam_id}",
                })
    except Exception:
        pass
    return result


def find_external_camera_index() -> Optional[int]:
    """
    UVC キャプチャーカード (外部カメラ, LENS_FACING=2) の
    Kivy Camera インデックスを返す。見つからなければ None。
    """
    for cam in list_cameras():
        if cam["facing"] == 2:
            return cam["index"]
    return None


def capture_texture_to_jpeg(texture) -> Optional[bytes]:
    """
    Kivy Texture のピクセルデータを JPEG バイト列へ変換する。

    Kivy の texture.pixels は RGBA バイト列 (左下原点) を返す。
    ML Kit の InputImage.fromByteArray は JPEG を受け取れるため
    ここで変換する。

    Args:
        texture: kivy.graphics.texture.Texture

    Returns:
        JPEG bytes, or None on failure
    """
    if texture is None:
        return None
    try:
        if _ANDROID:
            return _texture_to_jpeg_android(texture)
        else:
            return _texture_to_jpeg_pil(texture)
    except Exception:
        return None


def _texture_to_jpeg_android(texture) -> bytes:
    """Android: pyjnius 経由で Bitmap → JPEG 変換。"""
    from jnius import autoclass
    import io as _io

    Bitmap = autoclass("android.graphics.Bitmap")
    BitmapConfig = autoclass("android.graphics.Bitmap$Config")
    BitmapCF = autoclass("android.graphics.CompressFormat")
    ByteArrayOutputStream = autoclass("java.io.ByteArrayOutputStream")

    w, h = texture.size
    # Kivy texture は左下原点なので垂直反転が必要
    raw = bytes(texture.pixels)  # RGBA, bottom-up

    # ARGB_8888 Bitmap 生成
    bmp = Bitmap.createBitmap(w, h, BitmapConfig.ARGB_8888)
    # setPixels (int[], offset, stride, x, y, width, height)
    pixel_ints = []
    for i in range(0, len(raw), 4):
        r, g, b, a = raw[i], raw[i+1], raw[i+2], raw[i+3]
        # Android Bitmap の ARGB_8888 は int32 (ARGB)
        argb = (a << 24) | (r << 16) | (g << 8) | b
        pixel_ints.append(argb)

    # 垂直反転 (Kivy は左下原点)
    rows = [pixel_ints[y * w:(y + 1) * w] for y in range(h)]
    rows.reverse()
    flipped = [px for row in rows for px in row]

    jint_array = autoclass("[I")
    jflat = jint_array(len(flipped))
    for i, v in enumerate(flipped):
        jflat[i] = v
    bmp.setPixels(jflat, 0, w, 0, 0, w, h)

    # JPEG 圧縮
    baos = ByteArrayOutputStream()
    bmp.compress(BitmapCF.JPEG, 90, baos)
    return bytes(baos.toByteArray())


def _texture_to_jpeg_pil(texture) -> bytes:
    """PC / テスト環境: Pillow を使った JPEG 変換。"""
    from PIL import Image
    import io as _io

    w, h = texture.size
    raw = bytes(texture.pixels)  # RGBA bottom-up
    img = Image.frombytes("RGBA", (w, h), raw)
    img = img.transpose(Image.FLIP_TOP_BOTTOM).convert("RGB")
    buf = _io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def crop_jpeg(jpeg_bytes: bytes, rect_ratio: tuple[float, float, float, float]) -> Optional[bytes]:
    """
    JPEG を指定の相対矩形でクロップして JPEG を返す。

    Args:
        jpeg_bytes: 元の JPEG バイト列
        rect_ratio: (left_ratio, top_ratio, right_ratio, bottom_ratio)
                    各値は 0.0〜1.0 の画面座標の割合

    Returns:
        クロップ後の JPEG bytes
    """
    if jpeg_bytes is None:
        return None
    try:
        if _ANDROID:
            return _crop_jpeg_android(jpeg_bytes, rect_ratio)
        else:
            return _crop_jpeg_pil(jpeg_bytes, rect_ratio)
    except Exception:
        return None


def _crop_jpeg_android(jpeg_bytes: bytes, rect_ratio) -> bytes:
    from jnius import autoclass
    BitmapFactory = autoclass("android.graphics.BitmapFactory")
    Bitmap = autoclass("android.graphics.Bitmap")
    BitmapCF = autoclass("android.graphics.CompressFormat")
    ByteArrayOutputStream = autoclass("java.io.ByteArrayOutputStream")

    jbytes = bytearray(jpeg_bytes)
    bmp = BitmapFactory.decodeByteArray(jbytes, 0, len(jbytes))
    w, h = bmp.getWidth(), bmp.getHeight()
    lx, ty, rx, by = rect_ratio
    x0 = int(lx * w)
    y0 = int(ty * h)
    cw = max(1, int((rx - lx) * w))
    ch = max(1, int((by - ty) * h))
    cropped = Bitmap.createBitmap(bmp, x0, y0, cw, ch)
    baos = ByteArrayOutputStream()
    cropped.compress(BitmapCF.JPEG, 90, baos)
    return bytes(baos.toByteArray())


def _crop_jpeg_pil(jpeg_bytes: bytes, rect_ratio) -> bytes:
    from PIL import Image
    import io as _io
    img = Image.open(_io.BytesIO(jpeg_bytes))
    w, h = img.size
    lx, ty, rx, by = rect_ratio
    box = (int(lx*w), int(ty*h), int(rx*w), int(by*h))
    cropped = img.crop(box)
    buf = _io.BytesIO()
    cropped.save(buf, format="JPEG", quality=90)
    return buf.getvalue()
