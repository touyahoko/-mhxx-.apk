"""🔁 自動ループタブ

Arduino Leonardo + USB キャプチャーの映像認識を組み合わせて、
目標のお守りが出るまでゲームを自動ループさせる。

動作フロー:
    1. 「配信」タブで USB ストリーミングを開始
    2. Arduino Leonardo を USB OTG で接続し「接続」を押す
    3. 「検索」タブで目標お守りを設定し「検索タブから読み込む」
    4. ループ待機時間を設定 (Arduino READY 信号がなければ時間ベース)
    5. 「ループ開始」を押す
       ↓
       [NEXT 送信] → Arduino がボタンシーケンス実行 → Switch でお守り生成
       ↓ 待機時間後 (または Arduino から READY 受信後)
       [スクリーンショット取得] ← app.uvc.latest_frame
       ↓
       [MLKit OCR] → [skill_matcher.scan()] → 目標と比較
       ↓
       一致: ✅ 通知・停止     不一致: ループカウント +1 → [NEXT 送信] へ

Arduino プロトコル:
    送信: "NEXT\\n" / "STOP\\n"
    受信: "READY\\n" (画面表示完了) / "OK\\n" (コマンド受理)

Switch 本体との直接通信はしない。操作は Arduino Leonardo 経由のみ。
"""
from __future__ import annotations

import os
import time as _time_mod

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.scrollview import ScrollView

from mhxx_rng import KIND_TABLES, SKILL_NAMES
from ocr import android_ocr
from ocr.skill_matcher import scan as skill_scan


# ---------------------------------------------------------------------------
# ループ状態定数
# ---------------------------------------------------------------------------

class _State:
    IDLE        = "idle"       # 停止中
    WAITING     = "waiting"    # Arduino から READY 待ち / タイマー待ち
    CAPTURING   = "capturing"  # スクリーンショット取得中
    OCR         = "ocr"        # OCR 処理中
    MATCHED     = "matched"    # 目標一致 → 停止済み


class AutoLoopScreen(ScrollView):
    """Arduino + 画像認識 お守り自動ループ タブ。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._state = _State.IDLE
        self._loop_count = 0
        self._target: dict | None = None
        self._wait_timer = None

    def on_kv_post(self, base_widget) -> None:
        app = App.get_running_app()
        if not app.arduino.is_available():
            self.ids.arduino_btn.disabled = True
            self.ids.arduino_status.text = "Android 端末でのみ利用できます"

    # ================================================================== #
    # Arduino 接続管理
    # ================================================================== #

    def _toggle_arduino(self) -> None:
        app = App.get_running_app()
        if app.arduino.connected:
            self._disconnect_arduino()
        else:
            self._connect_arduino()

    def _connect_arduino(self) -> None:
        app = App.get_running_app()
        self.ids.arduino_status.text = "接続中..."
        self.ids.arduino_btn.disabled = True

        def on_msg(msg: str) -> None:
            Clock.schedule_once(lambda dt: self._on_arduino_msg(msg))

        def on_err(msg: str) -> None:
            Clock.schedule_once(lambda dt: self._on_arduino_error(msg))

        ok = app.arduino.connect(on_message=on_msg, on_error=on_err)
        self.ids.arduino_btn.disabled = False
        if ok:
            self.ids.arduino_status.text = "✅ Arduino Leonardo に接続しました"
            self.ids.arduino_btn.text = "Arduino を切断"
        else:
            self.ids.arduino_status.text = "接続失敗"

    def _disconnect_arduino(self) -> None:
        app = App.get_running_app()
        app.arduino.disconnect()
        self.ids.arduino_status.text = "未接続"
        self.ids.arduino_btn.text = "Arduino に接続"

    def _on_arduino_msg(self, msg: str) -> None:
        """Arduino からのメッセージ処理。"""
        if msg == "READY" and self._state == _State.WAITING:
            # Arduino から「画面表示完了」の通知
            if self._wait_timer:
                self._wait_timer.cancel()
                self._wait_timer = None
            self._do_capture()
        # "OK" は無視

    def _on_arduino_error(self, msg: str) -> None:
        self._set_status(f"⚠️ Arduino エラー: {msg}")
        if self._state != _State.IDLE:
            self._stop_loop(reason=f"Arduino エラーのためループ中断: {msg}")

    # ================================================================== #
    # 目標お守り
    # ================================================================== #

    def _load_target(self) -> None:
        """「検索」タブの現在の設定を目標として読み込む。"""
        app = App.get_running_app()
        search = app.root.ids.search_screen

        if not search._skill1_names:
            self._set_target_label("検索タブでお守り種類と条件を先に設定してください")
            return

        s1_name = search.ids.skill1_spinner.text.strip()
        s1_pts_text = search.ids.skill1_pt.text
        s1_pts = int(s1_pts_text) if s1_pts_text.isdigit() else None

        s2_name = None
        s2_pts = 0
        if search.ids.skill2_check.active and search._skill2_names:
            s2_name = search.ids.skill2_spinner.text.strip()
            s2_pts_text = search.ids.skill2_pt.text
            s2_pts = int(s2_pts_text) if s2_pts_text.isdigit() else 0

        slot_text = search.ids.slot_spinner.text
        slot = int(slot_text) if slot_text.isdigit() else None

        self._target = {
            "skill1_name": s1_name or None,
            "skill1_pts": s1_pts,
            "skill2_name": s2_name,
            "skill2_pts": s2_pts,
            "slot": slot,
        }

        lines = []
        if s1_name and s1_pts is not None:
            lines.append(f"スキル1: {s1_name} +{s1_pts}")
        elif s1_name:
            lines.append(f"スキル1: {s1_name} (Pt 未指定)")
        if s2_name:
            lines.append(f"スキル2: {s2_name} +{s2_pts}")
        if slot is not None:
            lines.append(f"スロット: {slot}")

        if lines:
            self._set_target_label("\n".join(lines))
        else:
            self._set_target_label("目標が空です。検索タブで条件を設定してください。")
            self._target = None

    def _set_target_label(self, text: str) -> None:
        self.ids.target_label.text = text

    # ================================================================== #
    # ループ制御
    # ================================================================== #

    def _toggle_loop(self) -> None:
        if self._state == _State.IDLE or self._state == _State.MATCHED:
            self._start_loop()
        else:
            self._stop_loop(reason="ユーザーが停止")

    def _start_loop(self) -> None:
        # 事前チェック
        if self._target is None:
            self._load_target()
        if self._target is None:
            self._set_status("❌ 目標お守りを設定してください（検索タブから読み込む）")
            return

        app = App.get_running_app()
        stream = app.root.ids.stream_screen
        if not stream.running:
            self._set_status("❌ 先に「配信」タブでストリーミングを開始してください")
            return

        if not android_ocr.is_available():
            self._set_status(
                "❌ OCR はAndroid端末でのみ利用できます。\n"
                "「読取」タブで確認してください。"
            )
            return

        self._state = _State.WAITING
        self._loop_count = 0
        self.ids.start_btn.text = "ループ停止"
        self.ids.loop_count_label.text = "試行回数: 0"
        self.ids.current_charm_label.text = "---"
        self._set_status("ループ開始 … Arduino へ最初の NEXT を送信します")

        # 最初のステップへ
        self._do_next()

    def _stop_loop(self, reason: str = "停止") -> None:
        if self._wait_timer:
            self._wait_timer.cancel()
            self._wait_timer = None

        app = App.get_running_app()
        if app.arduino.connected:
            app.arduino.send("STOP")

        self._state = _State.IDLE
        self.ids.start_btn.text = "ループ開始"
        self._set_status(f"停止 — {reason}")

    # ================================================================== #
    # ループ内部ステップ
    # ================================================================== #

    def _do_next(self) -> None:
        """次フレームへ進む: Arduino に NEXT を送り、待機タイマーをセット。"""
        if self._state == _State.IDLE:
            return

        app = App.get_running_app()
        wait_sec = self._get_wait_sec()
        self._state = _State.WAITING

        if app.arduino.connected:
            sent = app.arduino.send("NEXT")
            if not sent:
                self._set_status("⚠️ Arduino への送信に失敗しました。再試行中...")
        else:
            # Arduino なし: 時間ベースのみで動作
            pass

        self._set_status(
            f"待機中 ({wait_sec:.0f} 秒) … Arduino が画面を進めます\n"
            f"試行回数: {self._loop_count}"
        )

        # タイムアウト = 待機時間後にスクリーンショット
        # (Arduino から READY が来れば早めに実行される)
        self._wait_timer = Clock.schedule_once(
            lambda dt: self._on_wait_timeout(), wait_sec
        )

    def _on_wait_timeout(self) -> None:
        """待機タイマー満了 → スクリーンショット取得へ。"""
        self._wait_timer = None
        if self._state != _State.WAITING:
            return
        self._do_capture()

    def _do_capture(self) -> None:
        """最新フレームを一時ファイルに書き出して OCR へ渡す。"""
        if self._state == _State.IDLE:
            return

        self._state = _State.CAPTURING
        self._set_status("📷 スクリーンショット取得中...")

        app = App.get_running_app()
        frame = app.uvc.latest_frame
        if frame is None:
            self._set_status("⚠️ フレームを取得できません。ストリーミング中か確認してください。")
            self._schedule_next()
            return

        # 一時 JPEG ファイルに保存 (ML Kit は file URI を必要とする)
        tmp_dir = getattr(app, "user_data_dir", "/tmp")
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_path = os.path.join(
            tmp_dir, f"loop_snap_{int(_time_mod.time())}.jpg"
        )
        try:
            with open(tmp_path, "wb") as f:
                f.write(frame)
        except Exception as exc:
            self._set_status(f"⚠️ 一時ファイル書き込みエラー: {exc}")
            self._schedule_next()
            return

        self._state = _State.OCR
        self._set_status("🔍 画像認識中 (ML Kit OCR)...")

        def on_text(text: str) -> None:
            Clock.schedule_once(lambda dt: self._process_ocr(text, tmp_path))

        def on_err(msg: str) -> None:
            Clock.schedule_once(lambda dt: self._on_ocr_error(msg, tmp_path))

        android_ocr.recognize_text(tmp_path, on_text, on_err)

    def _process_ocr(self, text: str, tmp_path: str) -> None:
        """OCR テキストを解析して目標と比較する。"""
        self._cleanup_tmp(tmp_path)
        if self._state == _State.IDLE:
            return

        app = App.get_running_app()
        kind = int(app.kind)
        table = KIND_TABLES[kind]
        s1_names = [SKILL_NAMES[i].strip() for i in table.skill1]
        s2_names = [SKILL_NAMES[i].strip() for i in table.skill2]

        result = skill_scan(text, s1_names, table.sp1, s2_names, table.sp2)

        b1 = result.best_skill1
        b2 = result.best_skill2

        # 認識結果を表示
        charm_lines = []
        if b1:
            charm_lines.append(
                f"スキル1: {b1.name} +{b1.points}  "
                f"(信頼度 {b1.score * 100:.0f}%)"
            )
        else:
            charm_lines.append("スキル1: 認識失敗")
        if b2:
            charm_lines.append(
                f"スキル2: {b2.name} +{b2.points}  "
                f"(信頼度 {b2.score * 100:.0f}%)"
            )
        if result.best_slot is not None:
            charm_lines.append(f"スロット: {result.best_slot}")

        self.ids.current_charm_label.text = "\n".join(charm_lines)

        if self._check_match(result):
            self._on_matched()
        else:
            self._schedule_next()

    def _on_ocr_error(self, msg: str, tmp_path: str) -> None:
        self._cleanup_tmp(tmp_path)
        if self._state == _State.IDLE:
            return
        self._set_status(f"⚠️ OCR エラー: {msg}。次フレームへ進みます...")
        self._schedule_next()

    def _schedule_next(self) -> None:
        """次のループへ (少し間を空けてから)。"""
        if self._state == _State.IDLE:
            return
        self._loop_count += 1
        self.ids.loop_count_label.text = f"試行回数: {self._loop_count}"
        self._state = _State.WAITING
        Clock.schedule_once(lambda dt: self._do_next(), 0.3)

    def _on_matched(self) -> None:
        """目標のお守りが見つかった！"""
        app = App.get_running_app()
        if app.arduino.connected:
            app.arduino.send("STOP")

        self._state = _State.MATCHED
        self.ids.start_btn.text = "ループ開始"
        self._set_status(
            f"🎉 目標のお守りが見つかりました！ (試行回数: {self._loop_count + 1})\n"
            "今すぐゲームを保存してください。"
        )
        self.ids.loop_count_label.text = (
            f"試行回数: {self._loop_count + 1} 回目で発見！"
        )

        # バイブレーション通知
        try:
            from plyer import vibrator
            vibrator.vibrate(1)
        except Exception:
            pass

    # ================================================================== #
    # 目標との比較
    # ================================================================== #

    def _check_match(self, ocr_result) -> bool:
        """OCR 結果が目標のお守りと一致するか判定する。"""
        if not self._target:
            return False

        b1 = ocr_result.best_skill1
        b2 = ocr_result.best_skill2

        # スキル1 チェック
        t_s1_name = self._target.get("skill1_name")
        t_s1_pts = self._target.get("skill1_pts")
        if t_s1_name is not None:
            if not b1:
                return False
            if b1.name.strip() != t_s1_name:
                return False
            if t_s1_pts is not None and b1.points != t_s1_pts:
                return False

        # スキル2 チェック
        t_s2_name = self._target.get("skill2_name")
        t_s2_pts = self._target.get("skill2_pts", 0)
        if t_s2_name is not None:
            if not b2:
                return False
            if b2.name.strip() != t_s2_name:
                return False
            if b2.points != t_s2_pts:
                return False

        # スロット チェック
        t_slot = self._target.get("slot")
        if t_slot is not None and ocr_result.best_slot != t_slot:
            return False

        return True

    # ================================================================== #
    # ヘルパー
    # ================================================================== #

    def _get_wait_sec(self) -> float:
        """待機スピナーから秒数を取得。"""
        text = self.ids.wait_spinner.text  # 例: "5秒"
        try:
            return float(text.replace("秒", "").strip())
        except ValueError:
            return 5.0

    def _set_status(self, text: str) -> None:
        self.ids.loop_status.text = text

    @staticmethod
    def _cleanup_tmp(path: str) -> None:
        """一時ファイルを削除する。"""
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
