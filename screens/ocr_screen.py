"""📷 鑑定読取タブ

ユーザーが撮影/選択した「1枚の画像」、または手動入力したテキストから、
お守りのスキル/スロットを推定し、検索タブへ反映する。

重要: Switch本体との通信・自動操作は一切行わない。処理対象は
ユーザーが指定したその場限りの1枚の画像 or 1件のテキストのみで、
連続実行・自動化の要素はない。カメラ/OCR自体はAndroid実機でのみ
動作する (ocr/android_ocr.py 参照。デスクトップでは「利用不可」と
表示され、テキスト直接入力のみが使える)。
"""
from __future__ import annotations

import os
import time

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.scrollview import ScrollView

from mhxx_rng import KIND_TABLES, SKILL_NAMES

from ocr import android_ocr
from ocr.skill_matcher import scan


class OcrScreen(ScrollView):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._last_result = None

    def on_kv_post(self, base_widget) -> None:
        if not android_ocr.is_available():
            self.ids.camera_btn.disabled = True
            self.ids.camera_btn.text = "写真を撮る (この端末では未対応)"
            self._set_status(
                "この端末ではカメラOCRは利用できません。ギャラリー選択、"
                "またはテキスト直接入力をお使いください。"
            )

    # ---- 画像入手 (撮影 / ギャラリー) --------------------------------------

    def _take_photo(self) -> None:
        try:
            from plyer import camera
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"カメラ機能を利用できません: {exc}")
            return
        app = App.get_running_app()
        out_dir = getattr(app, "user_data_dir", "/tmp")
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"mhxx_scan_{int(time.time())}.jpg")
        self._set_status("カメラを起動しています...")
        try:
            camera.take_picture(
                filename=path,
                on_complete=lambda p=path: Clock.schedule_once(lambda dt: self._on_image_ready(p)),
            )
        except NotImplementedError:
            self._set_status("この端末ではカメラ機能を利用できません。")
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"カメラの起動に失敗しました: {exc}")

    def _pick_gallery(self) -> None:
        try:
            from plyer import filechooser
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"ファイル選択機能を利用できません: {exc}")
            return
        self._set_status("画像を選択してください...")
        try:
            filechooser.open_file(
                on_selection=lambda sel: Clock.schedule_once(lambda dt: self._on_gallery_selection(sel)),
                filters=[["Images", "*.jpg", "*.jpeg", "*.png"]],
            )
        except NotImplementedError:
            self._set_status("この端末ではギャラリー選択を利用できません。")
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"ファイル選択に失敗しました: {exc}")

    def _on_gallery_selection(self, selection) -> None:
        if not selection:
            self._set_status("画像が選択されませんでした。")
            return
        self._on_image_ready(selection[0])

    def _on_image_ready(self, path: str) -> None:
        if not path or not os.path.exists(path):
            self._set_status("画像ファイルが見つかりませんでした。")
            return
        self._set_status("OCR処理中... (端末により数秒かかります)")

        def on_result(text: str) -> None:
            Clock.schedule_once(lambda dt: self._on_ocr_text(text))

        def on_error(message: str) -> None:
            Clock.schedule_once(lambda dt: self._set_status(f"OCRエラー: {message}"))

        android_ocr.recognize_text(path, on_result, on_error)

    def _on_ocr_text(self, text: str) -> None:
        self.ids.text_input.text = text
        if text.strip():
            self._set_status("読み取りました。内容を確認して「この内容を解析」を押してください。")
        else:
            self._set_status("テキストを検出できませんでした。別の写真を試すか、直接入力してください。")

    # ---- 解析 ---------------------------------------------------------------

    def _analyze(self) -> None:
        text = self.ids.text_input.text
        if not text.strip():
            self._set_status("テキストが空です。写真を撮るか、直接入力してください。")
            return
        app = App.get_running_app()
        kind = int(app.kind)
        table = KIND_TABLES[kind]
        s1_names = [SKILL_NAMES[i].strip() for i in table.skill1]
        s2_names = [SKILL_NAMES[i].strip() for i in table.skill2]
        result = scan(text, s1_names, table.sp1, s2_names, table.sp2)
        self._last_result = result
        self._render_result(result)
        self._set_status("解析しました。内容を確認して「検索タブへ反映」を押してください。")

    def _render_result(self, result) -> None:
        lines: list[str] = []
        b1 = result.best_skill1
        if b1 is not None:
            pts = b1.points if b1.points is not None else "?"
            lines.append(f"スキル1: {b1.name} +{pts}  (信頼度 {b1.score * 100:.0f}%)")
            others = result.skill1_candidates[1:3]
            if others:
                lines.append("  他の候補: " + " / ".join(f"{c.name}+{c.points}" for c in others))
        else:
            lines.append("スキル1: 認識できませんでした → 検索タブで手動選択してください")

        b2 = result.best_skill2
        if b2 is not None:
            pts = b2.points if b2.points is not None else "?"
            lines.append(f"スキル2: {b2.name} +{pts}  (信頼度 {b2.score * 100:.0f}%)")
            others = result.skill2_candidates[1:3]
            if others:
                lines.append("  他の候補: " + " / ".join(f"{c.name}+{c.points}" for c in others))
        else:
            lines.append("スキル2: 認識できませんでした → 検索タブで手動選択してください")

        if result.slot_candidates:
            lines.append(f"スロット: {result.best_slot}  (候補: {result.slot_candidates})")
        else:
            lines.append("スロット: 認識できませんでした → 検索タブで手動選択してください")

        self.ids.result_label.text = "\n".join(lines)
        self.ids.apply_btn.disabled = not (b1 or b2)

    def _apply_to_search(self) -> None:
        if self._last_result is None:
            return
        b1 = self._last_result.best_skill1
        b2 = self._last_result.best_skill2
        app = App.get_running_app()
        search = app.root.ids.search_screen
        search.apply_external_result(
            skill1_name=b1.name if b1 else None,
            skill1_pts=b1.points if b1 else None,
            skill2_name=b2.name if b2 else None,
            skill2_pts=b2.points if b2 else None,
            slot=self._last_result.best_slot,
        )
        app.root.ids.tabs.switch_to(app.root.ids.search_tab_item)

    def _clear(self) -> None:
        self.ids.text_input.text = ""
        self.ids.result_label.text = ""
        self.ids.apply_btn.disabled = True
        self._last_result = None
        self._set_status("")

    def _set_status(self, text: str) -> None:
        self.ids.status_label.text = text
