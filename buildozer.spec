[app]

title = MHXX RNG Tool
package.name = mhxxrngtool
package.domain = org.mhxxtools

source.dir = .
source.include_exts = py,kv,otf,ttf,txt,png,jpg
source.exclude_dirs = tests, bin, .buildozer, .github, .git

version = 1.1.0

requirements = python3,kivy==2.3.1,plyer

orientation = portrait
fullscreen = 0

icon.filename = %(source.dir)s/assets/icons/icon.png

# ---------------------------------------------------------------------------
# Android 権限
#
#   CAMERA            : USBキャプチャーボード (外部カメラ) / OCR 撮影
#   USB_HOST          : Arduino Leonardo + UVC キャプチャー USB 通信
#   READ_MEDIA_IMAGES : ギャラリーから画像選択 (Android 13+)
#   READ_EXTERNAL_STORAGE : ギャラリーから画像選択 (Android 12 以下)
#   VIBRATE           : 目標お守り発見時の通知バイブ
# ---------------------------------------------------------------------------
android.permissions = CAMERA,USB_HOST,READ_MEDIA_IMAGES,READ_EXTERNAL_STORAGE,VIBRATE
android.api = 34
android.minapi = 28
# Android 9 (API 28) 以降: Camera2 外部カメラ (UVC キャプチャーボード) サポート
android.archs = arm64-v8a,armeabi-v7a
android.allow_backup = True

# ---------------------------------------------------------------------------
# Gradle 依存関係
#
#   text-recognition-japanese : ML Kit 日本語 OCR (既存機能)
#   カメラ / USB は Android OS 標準 API のため Gradle 追加不要
# ---------------------------------------------------------------------------
android.gradle_dependencies = com.google.mlkit:text-recognition-japanese:16.0.1
android.enable_androidx = True

# USB デバイスフィルター (USB OTG 接続時にアプリを自動起動する設定)
# android.meta_data = android.hardware.usb.action.USB_DEVICE_ATTACHED:@xml/device_filter
# ※ 自動起動不要ならコメントアウトのままで OK

[buildozer]
log_level = 2
warn_on_root = 1
