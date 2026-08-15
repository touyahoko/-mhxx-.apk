[app]

title = MHXX RNG Tool
package.name = mhxxrngtool
package.domain = org.mhxxtools

source.dir = .
source.include_exts = py,kv,otf,ttf,txt,png,jpg
source.exclude_dirs = tests, bin, .buildozer, .github, .git

version = 1.0.0

requirements = python3,kivy==2.3.1,plyer

orientation = portrait
fullscreen = 0

icon.filename = %(source.dir)s/assets/icons/icon.png

# Android固有設定
# CAMERA: 鑑定結果の撮影用。READ_MEDIA_IMAGES/READ_EXTERNAL_STORAGE:
# ギャラリーからの画像選択用 (Android 13+ / 12以下の両方をカバー)。
android.permissions = CAMERA,READ_MEDIA_IMAGES,READ_EXTERNAL_STORAGE
android.api = 34
android.minapi = 23
android.archs = arm64-v8a,armeabi-v7a
android.allow_backup = True

# Google ML Kit (オンデバイス日本語テキスト認識、無料・APIキー不要)。
# ocr/android_ocr.py から pyjnius 経由で呼び出す。ML KitはAndroidXが
# 前提のため enable_androidx も有効化する。
#
# ⚠️ ビルドエラーが出た場合、まずこの2行が原因かどうかを切り分ける
# ためにコメントアウトしてみてください。コメントアウトしても
# アプリ自体は問題なくビルド・動作します。「鑑定読取」タブのうち、
# カメラ撮影からの自動OCRだけが使えなくなり、テキスト直接入力による
# 判定機能はそのまま使えます。
# (前回の "grpmodule.c" ビルドエラーはこの2行が原因ではなく、Gradle
#  依存関係の解決よりずっと前段階の、CPython本体のコンパイル中に
#  起きていたものでした。そちらは patches/android-config.site 側で
#  対処したため、この2行は有効化した状態に戻しています)
android.gradle_dependencies = com.google.mlkit:text-recognition-japanese:16.0.1
android.enable_androidx = True

# 個人利用目的のツールのため、Google Playへの公開は想定していません。
# (公開する場合は package.domain を実際に所有するドメインの逆順に、
#  version / versionCode の運用ルールを別途整備してください)

[buildozer]
log_level = 2
warn_on_root = 1
