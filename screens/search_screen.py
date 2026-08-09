"""🔍 検索タブ

スキル/スロット条件を指定して、mhxx_rng.MHXXEngine.search() /
search_greater() でフレームを検索する。検索本体は別スレッドで実行し、
結果はメインスレッドへ Clock 経由で届く (common.BackgroundSearch)。
"""
from __future__ import annotations

from kivy.app import App
from kivy.uix.scrollview import ScrollView

from mhxx_rng import KIND_TABLES, ORIGIN_NAMES, SKILL_NAMES, MHXXEngine, SearchTarget

from screens.common import (
    BackgroundSearch,
    CharmResultCard,
    clamp,
    format_elapsed,
    format_mash,
    hex_to_rgba,
    safe_int,
)

_MAX_DISPLAY = 300


class SearchScreen(ScrollView):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._skill1_names: list[str] = []
        self._skill2_names: list[str] = []
        self._runner: BackgroundSearch | None = None
        self._true_count = 0
        app = App.get_running_app()
        app.bind(kind=self._on_kind_changed)
        app.bind(fps=self._on_fps_changed)

    def on_kv_post(self, base_widget) -> None:
        # kv側の id (self.ids) は __init__ 完了時点ではまだ未確定のため、
        # id に依存する初期化はここ (kvルール適用完了後) で行う。
        self._on_kind_changed(App.get_running_app(), App.get_running_app().kind)

    # ---- お守り種類が変わったときの更新 -----------------------------------

    def _on_kind_changed(self, app, kind: int) -> None:
        table = KIND_TABLES[int(kind)]
        self._skill1_names = [SKILL_NAMES[i].strip() for i in table.skill1]
        self._skill2_names = [SKILL_NAMES[i].strip() for i in table.skill2]

        sp = self.ids.skill1_spinner
        sp.values = self._skill1_names
        sp.text = self._skill1_names[0] if self._skill1_names else ""

        sp2 = self.ids.skill2_spinner
        sp2.values = self._skill2_names
        sp2.text = self._skill2_names[0] if self._skill2_names else ""

        self._update_pt_default(1)
        self._update_pt_default(2)

    def on_skill1_selected(self, _text: str) -> None:
        self._update_pt_default(1)

    def on_skill2_selected(self, _text: str) -> None:
        self._update_pt_default(2)

    def _update_pt_default(self, which: int) -> None:
        kind = int(App.get_running_app().kind)
        table = KIND_TABLES[kind]
        if which == 1:
            names, sp_table, pt_input, hint = (
                self._skill1_names, table.sp1, self.ids.skill1_pt, self.ids.skill1_hint,
            )
        else:
            names, sp_table, pt_input, hint = (
                self._skill2_names, table.sp2, self.ids.skill2_pt, self.ids.skill2_hint,
            )
        spinner = self.ids.skill1_spinner if which == 1 else self.ids.skill2_spinner
        if not names or spinner.text not in names:
            return
        idx = names.index(spinner.text)
        lo, hi = sp_table[idx]
        hint.text = f"Pt: {lo}〜{hi}"
        pt_input.text = str(hi)

    # ---- 検索 --------------------------------------------------------------

    def _on_search(self) -> None:
        if self._runner is not None and self._runner.is_running:
            return
        app = App.get_running_app()
        kind = int(app.kind)
        table = KIND_TABLES[kind]

        if not self._skill1_names or self.ids.skill1_spinner.text not in self._skill1_names:
            return
        s1_idx = self._skill1_names.index(self.ids.skill1_spinner.text)
        s1_lo, s1_hi = table.sp1[s1_idx]
        s1_pts = clamp(safe_int(self.ids.skill1_pt.text, s1_hi), s1_lo, s1_hi)
        self.ids.skill1_pt.text = str(s1_pts)

        s2_idx = None
        s2_pts = 0
        if self.ids.skill2_check.active and self._skill2_names:
            if self.ids.skill2_spinner.text in self._skill2_names:
                s2_idx = self._skill2_names.index(self.ids.skill2_spinner.text)
                s2_lo, s2_hi = table.sp2[s2_idx]
                s2_pts = clamp(safe_int(self.ids.skill2_pt.text, s2_hi), s2_lo, s2_hi)
                self.ids.skill2_pt.text = str(s2_pts)

        slot = clamp(safe_int(self.ids.slot_spinner.text, 0), 0, 3)
        origin = ORIGIN_NAMES.index(self.ids.origin_spinner.text) if self.ids.origin_spinner.text in ORIGIN_NAMES else 0
        start = max(0, safe_int(self.ids.start_input.text, 0))
        step = max(1, safe_int(self.ids.step_input.text, 10_000_000))
        exact_mode = self.ids.mode_exact.state == "down"

        target = SearchTarget(
            skill1_idx=s1_idx, skill1_pts=s1_pts,
            skill2_idx=s2_idx, skill2_pts=s2_pts,
            slot=slot, origin=origin,
        )

        def run_search(should_stop, on_progress):
            engine = MHXXEngine(kind)
            fn = engine.search if exact_mode else engine.search_greater
            return fn(start, step, target, should_stop=should_stop, on_progress=on_progress, progress_interval=50_000)

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
            fps = int(App.get_running_app().fps)
            card = CharmResultCard(
                frame=result.frame,
                elapsed_text=format_elapsed(result.frame, fps),
                skill1_text=f"{result.charm.skill1_name.strip()} +{result.charm.skill1_pts}",
                skill2_text=(f"{result.charm.skill2_name.strip()} +{result.charm.skill2_pts}"
                             if result.charm.skill2_name else ""),
                slot_text=str(result.charm.slot),
                rarity_text=f"Rare{result.charm.rarity}",
                rarity_color=hex_to_rgba(result.charm.rarity_color),
                mash_text=format_mash(result.frame),
            )
            card.bind(on_release=lambda w: App.get_running_app().root.jump_to_around(w.frame))
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

    # ---- fps表示切替 --------------------------------------------------------

    def _on_fps_changed(self, app, fps: int) -> None:
        for card in self.ids.results_box.children:
            card.elapsed_text = format_elapsed(card.frame, int(fps))
            card.mash_text = format_mash(card.frame)
