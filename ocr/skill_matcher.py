"""OCRで読み取った (ノイズを含む可能性のある) テキストから、
mhxx_rng の該当お守り種類のスキル/スロット候補を推定するロジック。

Android依存もSwitch接続も一切なく、純粋な文字列処理だけで完結する
(このファイル単体でPC上でも完全にテスト可能)。

設計方針:
  1. まずテキスト中から「スキルらしき箇所」を出現位置の左から順に
     最大2つ特定する (スキル1候補プールとスキル2候補プールの
     "どちらか" にでも該当しうる名前の集合を使って探す)。
  2. 見つかった1つ目の箇所をスキル1プールに、2つ目の箇所をスキル2
     プールに、それぞれ個別に照合する。
  これにより、同じスキル名がスキル1・スキル2どちらの候補プールにも
  存在するお守り種類 (例: 光るお守り) で、スキル1側の検索がスキル2の
  出現箇所を横取りしてしまう、といった取り違えを防ぐ。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional

_ZEN2HAN_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")

# OCRがよく誤認識する記号類を数字扱いしないためのクリーニング対象
_NOISE_CHARS = re.compile(r"[|｜。、・:：;；]")


def normalize_text(text: str) -> str:
    """全角数字→半角、余分な空白/記号の簡易クリーニング。"""
    text = text.translate(_ZEN2HAN_DIGITS)
    text = _NOISE_CHARS.sub(" ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


@dataclass
class SkillCandidate:
    local_idx: int
    name: str
    score: float  # 0.0〜1.0 (1.0 = 完全一致)
    position: int
    points: Optional[int] = None
    points_in_range: Optional[bool] = None


@dataclass
class ScanResult:
    raw_text: str
    normalized_text: str
    skill1_candidates: list = field(default_factory=list)
    skill2_candidates: list = field(default_factory=list)
    slot_candidates: list = field(default_factory=list)

    @property
    def best_skill1(self) -> Optional[SkillCandidate]:
        return self.skill1_candidates[0] if self.skill1_candidates else None

    @property
    def best_skill2(self) -> Optional[SkillCandidate]:
        return self.skill2_candidates[0] if self.skill2_candidates else None

    @property
    def best_slot(self) -> Optional[int]:
        return self.slot_candidates[0] if self.slot_candidates else None


def _best_window_score(name: str, text: str) -> tuple[float, int]:
    """name と text 中の各ウィンドウ (name長 -1/±1) との最良類似度・位置を返す。"""
    best_score, best_pos = 0.0, -1
    n = len(name)
    for wlen in (n, n - 1, n + 1):
        if wlen <= 0:
            continue
        for i in range(0, max(1, len(text) - wlen + 1)):
            window = text[i : i + wlen]
            if not window:
                continue
            score = SequenceMatcher(None, name, window).ratio()
            if score > best_score:
                best_score, best_pos = score, i
    return best_score, best_pos


def _find_single_best_span(
    text: str, all_names: list[str], fuzzy_threshold: float = 0.6
) -> Optional[tuple[float, int, int, str]]:
    """text 全体から、all_names の中で最もよく一致する1箇所を探す
    (score, start, end, matched_name)。"""
    best: Optional[tuple[float, int, int, str]] = None
    for name in all_names:
        name = name.strip()
        if not name:
            continue
        pos = text.find(name)
        if pos >= 0:
            score = 1.0
        else:
            score, pos = _best_window_score(name, text)
            if pos < 0:
                continue
        if score < fuzzy_threshold:
            continue
        if best is None or score > best[0] or (score == best[0] and len(name) > len(best[3])):
            best = (score, pos, pos + len(name), name)
    return best


def _locate_candidate_spans(
    text: str, all_names: list[str], max_spans: int = 2, fuzzy_threshold: float = 0.6
) -> list[tuple[int, int, str, float]]:
    """テキスト中から「スキル名らしき箇所」を最大 max_spans 個、出現位置の
    左から順に返す (start, end, matched_text, score)。all_names はスキル1・
    スキル2の両プールを合わせた「位置特定専用」の候補集合で、ここではまだ
    どちらのスキルかは判定しない。

    1箇所見つけるたびにその範囲をテキストからマスクしてから次を探すため、
    同じスキル名がスキル1・スキル2の両方に (異なる位置で) 出現する場合でも
    正しく2箇所を別々に発見できる。"""
    spans: list[tuple[int, int, str, float]] = []
    remaining = text
    for _ in range(max_spans):
        best = _find_single_best_span(remaining, all_names, fuzzy_threshold)
        if best is None:
            break
        score, start, end, name = best
        spans.append((start, end, name, score))
        remaining = remaining[:start] + (" " * (end - start)) + remaining[end:]
    spans.sort(key=lambda s: s[0])  # 出現位置順 (左→右)
    return spans


def _classify_span(span_text: str, names: list[str], fuzzy_threshold: float = 0.5) -> list[tuple[int, float]]:
    """特定済みのテキスト片 span_text が、指定プール names の中でどれに
    最も近いかをスコア付けして返す (local_idx, score) のスコア降順リスト。"""
    scored: list[tuple[int, float]] = []
    for idx, name in enumerate(names):
        name = name.strip()
        if not name:
            continue
        score = 1.0 if name == span_text else SequenceMatcher(None, name, span_text).ratio()
        if score >= fuzzy_threshold:
            scored.append((idx, score))
    scored.sort(key=lambda x: -x[1])
    return scored


def extract_number_near(text: str, start: int, window: int = 8) -> Optional[int]:
    """指定位置から window 文字以内にある最初の数字列を整数として返す。"""
    snippet = text[start : start + window]
    m = re.search(r"\d{1,2}", snippet)
    if m:
        return int(m.group())
    return None


def extract_slot_candidates(text: str) -> list[int]:
    """「スロット2」のような表記、または単独の 0〜3 の並びからスロット数候補を推定する。"""
    candidates: list[int] = []
    for m in re.finditer(r"スロ(?:ット)?\s*(\d)", text):
        v = int(m.group(1))
        if 0 <= v <= 3 and v not in candidates:
            candidates.append(v)
    for m in re.finditer(r"[●○◯]{1,3}", text):
        v = m.group().count("●")
        if 0 <= v <= 3 and v not in candidates:
            candidates.append(v)
    return candidates


def _candidates_for_span(
    span_start: int, span_end: int, full_text: str, names: list[str], sp_table: list[tuple[int, int]], top_n: int = 3
) -> list[SkillCandidate]:
    span_text = full_text[span_start:span_end]
    pts = extract_number_near(full_text, span_end)
    results = []
    for idx, score in _classify_span(span_text, names)[:top_n]:
        lo, hi = sp_table[idx]
        lo, hi = min(lo, hi), max(lo, hi)  # 一部スキルは元データが (lo>hi) の順で格納されているため
        results.append(
            SkillCandidate(
                local_idx=idx,
                name=names[idx].strip(),
                score=score,
                position=span_start,
                points=pts,
                points_in_range=(lo <= pts <= hi) if pts is not None else None,
            )
        )
    return results


def scan(
    raw_text: str,
    skill1_names: list[str],
    skill1_sp: list[tuple[int, int]],
    skill2_names: list[str],
    skill2_sp: list[tuple[int, int]],
) -> ScanResult:
    """OCR生テキスト1件から、スキル1/スキル2/スロットの候補一覧を作る。"""
    normalized = normalize_text(raw_text)

    # 位置特定専用: スキル1・スキル2どちらのプールにも属しうる名前の集合から、
    # テキスト中の「スキルらしき箇所」を左から順に2つ探す。
    all_names = list(dict.fromkeys([n.strip() for n in (*skill1_names, *skill2_names) if n.strip()]))
    spans = _locate_candidate_spans(normalized, all_names, max_spans=2)

    s1_candidates: list[SkillCandidate] = []
    s2_candidates: list[SkillCandidate] = []
    if len(spans) >= 1:
        start, end, _name, _score = spans[0]
        s1_candidates = _candidates_for_span(start, end, normalized, skill1_names, skill1_sp)
    if len(spans) >= 2:
        start, end, _name, _score = spans[1]
        s2_candidates = _candidates_for_span(start, end, normalized, skill2_names, skill2_sp)

    slots = extract_slot_candidates(normalized)
    return ScanResult(
        raw_text=raw_text,
        normalized_text=normalized,
        skill1_candidates=s1_candidates,
        skill2_candidates=s2_candidates,
        slot_candidates=slots,
    )
