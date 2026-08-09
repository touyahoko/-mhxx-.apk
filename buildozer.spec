[app]

title = MHXX RNG Tool
package.name = mhxxrngtool
package.domain = org.mhxxtools

source.dir = .
source.include_exts = py,kv,otf,ttf,txt,png,jpg
source.exclude_dirs = tests, bin, .buildozer, .github, .git

version = 1.0.0

requirements = python3,kivy==2.3.1

orientation = portrait
fullscreen = 0

icon.filename = %(source.dir)s/assets/icons/icon.png

# Android固有設定
android.permissions =
android.api = 34
android.minapi = 23
android.archs = arm64-v8a,armeabi-v7a
android.allow_backup = True

# 個人利用目的のツールのため、Google Playへの公開は想定していません。
# (公開する場合は package.domain を実際に所有するドメインの逆順に、
#  version / versionCode の運用ルールを別途整備してください)

[buildozer]
log_level = 2
warn_on_root = 1
