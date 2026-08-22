"""🧪 調合スナイプタブ

調合(アイテム合成)を繰り返した際の「累計作成数」の列から、
mhxx_rng.MHXXEngine.search_combo() で現在のフレームを特定する。
入力検証には mhxx_rng.parse_combo_sequence() をそのまま使う。
"""
from __future__ import annotations

from kivy.app import App
from kivy.uix.scrollview import ScrollView

from mhxx_rng import MHXXEngine, parse_combo_sequence

from screens.common import BackgroundSearch, FrameResultCard, safe_int

_MAX_DISPLAY = 300


class ComboScreen(ScrollView):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._runner: BackgroundSearch | None = None
        self._true_count = 0

    # ---- 入力検証 (画面遷移時にも初期状態を出しておく) -----------------------

    def on_kv_post(self, base_widget) -> None:
        self._validate(self.ids.sequence_input.text)

    def _parse_values(self) -> list[int] | None:
        text = self.ids.sequence_input.text.strip()
        if not text:
            return None
        try:
            return [int(v) for v in text.split()]
        except ValueError:
            return None

    def _validate(self, _text: str) -> tuple[list[int], list[int]] | None:
        values = self._parse_values()
        label = self.ids.validation_label
        if values is None:
            label.text = "半角スペース区切りの数字を入力してください"
            label.color = (0.6, 0.6, 0.66, 1)
            return None
        dif, invalid = parse_combo_sequence(values)
        if not dif:
            label.text = "⚠ 数値列が短すぎます (先頭3件を除いた後に2件以上必要です)"
            label.color = (0.9, 0.35, 0.35, 1)
            return None
        if invalid:
            marked = " ".join(f"[{d}]" if i in invalid else str(d) for i, d in enumerate(dif))
            label.text = f"⚠ 2/3/4以外の増分があります ([]内が該当箇所):\n{marked}"
            label.color = (0.9, 0.35, 0.35, 1)
            return None
        label.text = f"✓ 増分列 ({len(dif)}件): {' '.join(map(str, dif))}"
        label.color = (0.35, 0.85, 0.55, 1)
        return dif, invalid

    # ---- 検索 --------------------------------------------------------------

    def _on_search(self) -> None:
        if self._runner is not None and self._runner.is_running:
            return
        values = self._parse_values()
        check = self._validate(self.ids.sequence_input.text)
        if values is None or check is None:
            return

        start = max(0, safe_int(self.ids.start_input.text, 0))
        step = max(1, safe_int(self.ids.step_input.text, 10_000_000))

        def run_search(should_stop, on_progress):
            engine = MHXXEngine(0)  # kindは調合検索の乱数には影響しない
            return engine.search_combo(start, step, values, should_stop=should_stop, on_progress=on_progress)

        self._on_clear()
        self._runner = BackgroundSearch(run_search, self._on_result, self._on_progress, self._on_finished)
        self.ids.search_btn.disabled = True
        self.ids.stop_btn.disabled = False
        self.ids.stop_btn.text = "停止"
        self.ids.progress.value = 0
        self.ids.progress.opacity = 1
        self._runner.start()

    def _on_stop(self) -> None:
        if self._runner is not None and self._runner.is_running:
            self._runner.request_stop()
            self.ids.stop_btn.disabled = True
            self.ids.stop_btn.text = "停止中..."

    def _on_clear(self) -> None:
        self.ids.results_box.clear_widgets()
        self._true_count = 0
        self._update_label()

    def _on_result(self, result) -> None:
        self._true_count += 1
        if len(self.ids.results_box.children) < _MAX_DISPLAY:
            card = FrameResultCard(frame_text=f"F{result.frame}", elapsed_text=result.elapsed_text())
            self.ids.results_box.add_widget(card)
        self._update_label()

    def _on_progress(self, done: int, total: int) -> None:
        self.ids.progress.value = int(done * 100 / total) if total else 0

    def _on_finished(self, _count: int) -> None:
        self.ids.search_btn.disabled = False
        self.ids.stop_btn.disabled = True
        self.ids.stop_btn.text = "停止"
        self.ids.progress.opacity = 0
        self._update_label()

    def _update_label(self) -> None:
        text = f"検索結果: {self._true_count} 件"
        if self._true_count > _MAX_DISPLAY:
            text += f" (表示は先頭{_MAX_DISPLAY}件まで)"
        self.ids.result_label.text = text
