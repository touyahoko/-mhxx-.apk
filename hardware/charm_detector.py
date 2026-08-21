"""お守り画像認識モジュール

カメラ映像のフレーム (Kivy Texture) から Switch の鑑定結果画面を
ML Kit OCR で読み取り、mhxx_rng のお守りデータと照合する。

処理フロー:
    1. Kivy Camera の texture を JPEG バイト列に変換
    2. OCR 対象領域 (クロップ矩形) を切り出す
    3. android_ocr.recognize_image_bytes() で日本語テキストを認識
    4. skill_matcher.scan() でスキル名・Pt・スロット数を推定
    5. 目標お守りと一致するかを判定して DetectResult を返す

注意:
    Android 実機のみ動作。PC テスト時は ocr/android_ocr.py が
    ダミーレスポンスを返す設計になっているため、ここでも同様に
    非 Android では recognize() がエラー文字列を返す。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Callable

from ocr.skill_matcher import scan as skill_scan, ScanResult
from ocr.android_ocr import recognize_from_bytes, is_available as ocr_available
from hardware.usb_video import capture_texture_to_jpeg, crop_jpeg
from mhxx_rng import KIND_TABLES, SKILL_NAMES


@dataclass
class TargetCharm:
    """Auto ループで狙うお守りの条件。"""
    kind: int              # 0=風化 1=古び 2=光る 3=なぞの
    skill1_idx: int        # 種類テーブル内のスキル1インデックス
    skill1_pts: int        # 必要スキル1 Pt (以上でも可)
    skill2_idx: int = -1   # -1 = 問わない
    skill2_pts: int = 0
    slot: int = -1         # -1 = 問わない
    pts_exact: bool = False  # True=完全一致 / False=以上OK

    def match(self, result: ScanResult) -> bool:
        """scan() の結果と目標が一致するか判定する。"""
        # スキル1 チェック
        if result.best_skill1 is None:
            return False
        tbl = KIND_TABLES[self.kind]
        s1_name = SKILL_NAMES[tbl.skill1[self.skill1_idx]].strip()
        if result.best_skill1.name.strip() != s1_name:
            return False
        pts1 = result.best_skill1.points or 0
        if self.pts_exact:
            if pts1 != self.skill1_pts:
                return False
        else:
            if pts1 < self.skill1_pts:
                return False

        # スロット チェック
        if self.slot >= 0 and result.best_slot != self.slot:
            return False

        # スキル2 チェック
        if self.skill2_idx >= 0:
            if result.best_skill2 is None:
                return False
            s2_name = SKILL_NAMES[tbl.skill2[self.skill2_idx]].strip()
            if result.best_skill2.name.strip() != s2_name:
                return False
            pts2 = result.best_skill2.points or 0
            if self.pts_exact:
                if pts2 != self.skill2_pts:
                    return False
            else:
                if pts2 < self.skill2_pts:
                    return False
        return True


@dataclass
class DetectResult:
    """1回の画像認識の結果。"""
    success: bool            # 目標と一致したか
    raw_text: str            # OCR が返した生テキスト
    scan: Optional[ScanResult]   # skill_matcher の解析結果
    error: str = ""          # エラーメッセージ (空=正常)

    @property
    def summary(self) -> str:
        if self.error:
            return f"[エラー] {self.error}"
        if self.scan is None:
            return "認識失敗"
        s = self.scan
        s1 = f"{s.best_skill1.name}+{s.best_skill1.points}" if s.best_skill1 else "?"
        s2 = f"  {s.best_skill2.name}+{s.best_skill2.points}" if s.best_skill2 else ""
        slot = f"  S{s.best_slot}" if s.best_slot is not None else ""
        ok = "✔ 一致" if self.success else "✘ 不一致"
        return f"{ok}  {s1}{s2}{slot}"


def _build_skill_pools(kind: int):
    """skill_scan() に渡す候補プールを種類テーブルから作る。"""
    tbl = KIND_TABLES[kind]
    s1_names = [SKILL_NAMES[i].strip() for i in tbl.skill1]
    s2_names = [SKILL_NAMES[i].strip() for i in tbl.skill2]
    s1_pts_ranges = [(tbl.sp1[i][0], tbl.sp1[i][-1]) for i in range(len(tbl.skill1))]
    s2_pts_ranges = [(tbl.sp2[i][0], tbl.sp2[i][-1]) for i in range(len(tbl.skill2))]
    return s1_names, s1_pts_ranges, s2_names, s2_pts_ranges


def detect_from_texture(
    texture,
    target: TargetCharm,
    crop_ratio: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0),
    on_ocr_done: Optional[Callable[[str], None]] = None,
) -> DetectResult:
    """
    Kivy Texture からお守りを認識して目標と照合する。

    Args:
        texture    : Camera.texture
        target     : 目標お守り条件
        crop_ratio : 認識対象の矩形 (left, top, right, bottom) 0.0〜1.0
        on_ocr_done: OCR 生テキストを受け取るコールバック (省略可)

    Returns:
        DetectResult
    """
    # 1. Texture → JPEG
    jpeg = capture_texture_to_jpeg(texture)
    if jpeg is None:
        return DetectResult(False, "", None, "テクスチャ変換失敗")

    # 2. クロップ
    if crop_ratio != (0.0, 0.0, 1.0, 1.0):
        jpeg = crop_jpeg(jpeg, crop_ratio)
    if jpeg is None:
        return DetectResult(False, "", None, "クロップ失敗")

    # 3. ML Kit OCR
    if not ocr_available():
        return DetectResult(False, "", None, "OCR は Android 実機のみ対応")

    try:
        raw_text = recognize_from_bytes(jpeg)
    except Exception as exc:
        return DetectResult(False, "", None, f"OCR エラー: {exc}")

    if on_ocr_done:
        on_ocr_done(raw_text)

    if not raw_text or raw_text.startswith("[エラー]"):
        return DetectResult(False, raw_text, None, raw_text)

    # 4. skill_matcher で解析
    tbl = KIND_TABLES[target.kind]
    s1_names, s1_ranges, s2_names, s2_ranges = _build_skill_pools(target.kind)
    scan_result = skill_scan(raw_text, s1_names, s1_ranges, s2_names, s2_ranges)

    # 5. 目標と照合
    matched = target.match(scan_result)
    return DetectResult(matched, raw_text, scan_result)
