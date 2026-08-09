"""📋 周辺確認タブ

指定フレームの前後のお守りを一覧表示する。mhxx_rng.MHXXEngine.around()
をそのまま呼ぶだけで、計算量が小さいためスレッド化はしていない
(デスクトップ版と同じ設計)。
"""
from __future__ import annotations

from kivy.app import App
from kivy.uix.scrollview import ScrollView

from mhxx_rng import ORIGIN_NAMES, MHXXEngine

from screens.common import CharmResultCard, clamp, format_elapsed, format_mash, hex_to_rgba, safe_int


class AroundScreen(ScrollView):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        app = App.get_running_app()
        app.bind(kind=self._on_kind_changed)
        app.bind(fps=self._on_fps_changed)

    def _on_kind_changed(self, app, kind: int) -> None:
        pass  # kind は _show() 実行時に都度読むだけなので、ここでは何もしない

    def set_frame(self, frame: int) -> None:
        self.ids.frame_input.text = str(int(frame))

    def _show(self) -> None:
        app = App.get_running_app()
        kind = int(app.kind)
        frame = max(0, safe_int(self.ids.frame_input.text, 0))
        count = clamp(safe_int(self.ids.count_input.text, 20), 1, 100)
        self.ids.count_input.text = str(count)
        origin = ORIGIN_NAMES.index(self.ids.origin_spinner.text) if self.ids.origin_spinner.text in ORIGIN_NAMES else 0

        engine = MHXXEngine(kind)
        rows = engine.around(frame, count, origin)

        self.ids.results_box.clear_widgets()
        fps = int(app.fps)
        for offset, charm in rows:
            abs_frame = frame + offset
            card = CharmResultCard(
                frame=abs_frame,
                offset_text=("±0" if offset == 0 else f"{offset:+d}"),
                elapsed_text=format_elapsed(abs_frame, fps),
                skill1_text=f"{charm.skill1_name.strip()} +{charm.skill1_pts}",
                skill2_text=(f"{charm.skill2_name.strip()} +{charm.skill2_pts}" if charm.skill2_name else ""),
                slot_text=str(charm.slot),
                rarity_text=f"Rare{charm.rarity}",
                rarity_color=hex_to_rgba(charm.rarity_color),
                mash_text=format_mash(abs_frame),
                is_center=(offset == 0),
            )
            self.ids.results_box.add_widget(card)
        self.ids.result_label.text = f"{len(rows)} 件表示中 (中心フレーム: {frame})"

    def _on_fps_changed(self, app, fps: int) -> None:
        for card in self.ids.results_box.children:
            card.elapsed_text = format_elapsed(card.frame, int(fps))
            card.mash_text = format_mash(card.frame)
