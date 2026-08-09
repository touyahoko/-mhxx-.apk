"""🎯 狙い目タブ

クエスト/マカフシギ/天運の狙い目 (有効フレーム window) を計算して表示する。
mhxx_rng.MHXXEngine の aimpoint_quest() / aimpoint_halcyon() / aimpoint_juju()
をそのまま呼ぶだけ (計算量が小さいためスレッド化なし、デスクトップ版と同じ)。
"""
from __future__ import annotations

from kivy.app import App
from kivy.uix.scrollview import ScrollView

from mhxx_rng import KIND_NAMES, MHXXEngine

from screens.common import clamp, safe_int


class AimPointScreen(ScrollView):
    def _calc(self) -> None:
        app = App.get_running_app()
        kind = int(app.kind)
        frame = max(0, safe_int(self.ids.frame_input.text, 0))

        engine = MHXXEngine(kind)
        engine.jump(frame)

        lines: list[str] = [f"フレーム: {frame}", f"種類: {KIND_NAMES[kind]}", ""]

        if self.ids.mode_quest.state == "down":
            n = clamp(safe_int(self.ids.charm_count_input.text, 10), 2, 40)
            self.ids.charm_count_input.text = str(n)
            row = engine.aimpoint_quest(n)
            lines.append(f"クエスト (チャーム数={n})")
            lines.append(f"  有効数: {row.count}")
            lines.append(f"  {row.pattern}")
        elif self.ids.mode_halcyon.state == "down":
            rows = engine.aimpoint_halcyon(self.ids.all_ranks_check.active)
            lines.append("マカフシギ (天運)")
            for r in rows:
                lines.append(f"  [{r.label}] 有効数={r.count}")
                lines.append(f"    {r.pattern}")
        else:
            rows = engine.aimpoint_juju(self.ids.all_ranks_check.active)
            lines.append("天運 (ジュジュ)")
            for r in rows:
                lines.append(f"  [{r.label}] 有効数={r.count}")
                lines.append(f"    {r.pattern}")

        self.ids.output_label.text = "\n".join(lines)
