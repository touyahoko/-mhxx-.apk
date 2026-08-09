"""
MHXX (モンスターハンタークロス/ダブルクロス) お守り乱数生成エンジン

やかさんのJupyter Notebook (mhxx-rng.ipynb) に実装されていたロジックを、
GUIから安全に使えるクラスベースのエンジンに移植したものです。

移植方針:
    - ノートブック側はモジュールグローバル変数 (x,y,z,w,t,f / r0..r6) で
      状態を持つ作りでしたが、GUIではバックグラウンドスレッドでの検索と
      メインスレッドでの単発計算 (around/aim point 確認) が同時に走り得るため、
      MHXXEngine のインスタンス属性として状態を持つように変更しています。
    - 乱数アルゴリズム・テーブル・各種しきい値やビット演算は、ノートブックの
      値をそのまま使用しています (変更・「修正」は一切行っていません)。
      特に slot() 内の `slotvalue[fill - 1]` のように fill=0 のとき
      Pythonの負インデックスで最後の要素を参照する挙動も、元のロジック通りに
      残しています。
    - print()していた箇所は、GUI表示用のデータ (dataclass) を返す/yieldする
      形に変更しています。

現時点では日本語テーブル (set_ja 相当) のみ移植しています。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Iterator

# ---------------------------------------------------------------------------
# 言語非依存の共有テーブル (cell "3rd" の set_ja() 相当)
# ---------------------------------------------------------------------------

SKILL_NAMES: list[str] = [
    "毒　", "麻痺", "睡眠", "気絶", "聴覚", "風圧", "耐震", "だる", "耐暑", "耐寒",
    "寒冷", "炎熱", "盗み", "対防", "狂撃", "細菌", "裂傷", "攻撃", "防御", "体力",
    "火耐", "水耐", "雷耐", "氷耐", "龍耐", "属耐", "火攻", "水攻", "雷攻", "氷攻",
    "龍攻", "属攻", "特攻", "研師", "匠　", "斬味", "剣術", "研磨", "鈍器", "抜会",
    "抜減", "納刀", "納研", "刃鱗", "装速", "反動", "精密", "通強", "貫強", "散強",
    "重強", "通追", "貫追", "散追", "榴追", "拡追", "毒追", "麻追", "睡追", "強追",
    "属追", "接追", "減追", "爆追", "速射", "射法", "装数", "変則", "弾節", "達人",
    "痛撃", "連撃", "特会", "属会", "会心", "裏会", "溜短", "スタ", "体術", "気力",
    "走行", "回性", "回距", "泡沫", "ガ性", "ガ強", "ＫＯ", "減攻", "笛　", "砲術",
    "重撃", "爆弾", "本気", "闘魂", "無傷", "チャ", "龍気", "底力", "逆境", "逆上",
    "窮地", "根性", "気配", "采配", "号令", "乗り", "跳躍", "無心", "我慢", "ＳＰ",
    "千里", "観察", "狩人", "運搬", "加護", "英雄", "回量", "回速", "効果", "広域",
    "腹減", "食い", "食事", "節食", "肉食", "茸食", "野草", "調成", "調数", "高速",
    "採取", "ハチ", "護石", "気ま", "運気", "剥取", "捕獲", "ベル", "ココ", "ポッ",
    "ユク", "龍識", "飛行", "紅兜", "大雪", "矛砕", "岩穿", "紫毒", "宝纏", "白疾",
    "隻眼", "黒炎", "金雷", "荒鉤", "燼滅", "朧隠", "鎧裂", "天眼", "青電", "銀嶺",
    "鏖魔", "真紅", "真大", "真矛", "真岩", "真紫", "真宝", "真白", "真隻", "真黒",
    "真金", "真荒", "真燼", "真朧", "真鎧", "真天", "真青", "真銀", "真鏖", "北辰",
    "斬術", "食欲", "職工", "剛腕", "祈願", "裏稼", "刀匠", "射手", "状態", "怒　",
    "回術", "居合", "頑強", "剛撃", "盾持", "潔癖", "増幅", "護収", "強欲", "対鋼",
    "対霞", "対炎", "胴倍", "秘術", "護強",
]

ORIGIN_NAMES: list[str] = ["マカ", "炭鉱"]
KIND_NAMES: list[str] = ["風化したお守り", "古びたお守り", "光るお守り", "なぞのお守り"]
MELDING_NAMES: list[str] = ["マカフシギ", "天運"]

RARITY_COLORS: dict[int, str] = {
    1: "#808080", 2: "#8080ff", 3: "#c0c000", 4: "#c080c0",
    5: "#80c080", 6: "#4040c0", 7: "#c04040", 8: "#80c0c0",
    9: "#ffc080", 10: "#c040c0",
}

_SEED = (0x0194FD72, 0x79E6C985, 0x08DD9701, 0x41CFCE91)
_JUMP_MODULUS = 0x100000201A8362F671442057EEA368001
_MASK32 = 0xFFFFFFFF


@dataclass(frozen=True)
class KindTable:
    """set_blue/set_red/set_yellow/set_white 相当のテーブル一式。"""

    index: int
    label: str
    skill1: tuple[int, ...]
    sp1: tuple[tuple[int, int], ...]
    skill2: tuple[int, ...]
    sp2: tuple[tuple[int, int], ...]
    slotvalue: tuple[tuple[int, int, int], ...]
    th: int


KIND_TABLES: dict[int, KindTable] = {
    0: KindTable(
        index=0, label="風化したお守り",
        skill1=(
            4, 5, 10, 11, 14, 15, 25, 31, 32, 35,
            36, 37, 38, 39, 40, 41, 42, 44, 45, 47,
            48, 49, 50, 64, 65, 66, 68, 70, 71, 72,
            73, 76, 77, 78, 79, 80, 81, 82, 83, 84,
            85, 86, 87, 90, 92, 93, 94, 95, 97, 99,
            100, 101, 106, 107, 108, 109, 114, 115, 116, 122,
            123, 132,
        ),
        sp1=(
            (3, 7), (5, 10), (3, 7), (3, 7), (3, 7), (5, 10), (3, 7), (3, 7), (3, 7), (3, 7),
            (3, 7), (1, 5), (2, 6), (1, 5), (1, 5), (5, 10), (5, 10), (3, 7), (2, 6), (2, 6),
            (2, 6), (2, 6), (2, 6), (1, 5), (1, 5), (1, 5), (3, 7), (2, 6), (1, 5), (2, 6),
            (2, 6), (2, 6), (2, 6), (3, 7), (3, 7), (2, 6), (2, 6), (2, 6), (1, 5), (3, 7),
            (3, 7), (5, 10), (5, 10), (2, 6), (2, 6), (1, 5), (1, 5), (1, 5), (2, 6), (2, 6),
            (2, 6), (1, 5), (2, 6), (1, 5), (3, 7), (3, 7), (3, 7), (1, 5), (3, 7), (2, 6),
            (3, 7), (3, 7),
        ),
        skill2=(
            4, 5, 17, 18, 25, 26, 27, 28, 29, 30,
            32, 33, 34, 35, 36, 37, 39, 40, 41, 43,
            44, 45, 47, 48, 49, 50, 64, 65, 66, 68,
            69, 70, 71, 74, 75, 76, 77, 78, 79, 80,
            81, 82, 83, 84, 85, 86, 87, 88, 89, 90,
            91, 92, 93, 94, 95, 96, 97, 99, 100, 101,
            105, 106, 107, 108, 109, 114, 115, 116, 119, 122,
            123, 125, 132, 134, 135, 136, 161, 162, 163, 164,
            165, 166, 167, 168, 169, 170, 171, 172, 173, 174,
            175, 176, 177, 178,
        ),
        sp2=(
            (3, 5), (5, 7), (7, 10), (5, 13), (5, 7), (5, 13), (5, 13), (5, 13), (5, 13), (5, 13),
            (5, 7), (7, 10), (3, 5), (5, 7), (5, 7), (3, 5), (5, 5), (2, 8), (5, 7), (3, 3),
            (5, 7), (5, 7), (3, 5), (3, 5), (3, 5), (3, 5), (3, 5), (3, 5), (3, 5), (5, 7),
            (7, 10), (3, 5), (1, 3), (3, 5), (3, 3), (3, 5), (3, 5), (3, 5), (3, 5), (3, 5),
            (3, 5), (3, 5), (1, 3), (3, 5), (3, 5), (7, 10), (7, 10), (5, 10), (5, 10), (3, 5),
            (5, 10), (3, 5), (1, 3), (1, 3), (1, 3), (3, 3), (3, 5), (3, 5), (3, 5), (1, 3),
            (7, 10), (3, 5), (1, 3), (5, 7), (5, 7), (7, 10), (1, 3), (3, 5), (5, 12), (3, 5),
            (5, 7), (3, 5), (7, 10), (5, 7), (3, 5), (5, 7), (3, 3), (3, 3), (3, 3), (3, 3),
            (3, 3), (3, 3), (3, 3), (3, 3), (3, 3), (3, 3), (3, 3), (3, 3), (3, 3), (3, 3),
            (3, 3), (3, 3), (3, 3), (3, 3),
        ),
        slotvalue=(
            (100, 100, 100), (3, 53, 88), (5, 55, 89), (7, 57, 89), (13, 58, 89),
            (16, 60, 90), (22, 62, 90), (30, 66, 90), (38, 68, 91), (50, 72, 91),
            (55, 75, 92), (59, 77, 92), (64, 81, 94), (67, 83, 94), (71, 86, 96),
            (74, 88, 96), (79, 91, 98), (82, 92, 98), (86, 94, 99), (90, 96, 99),
        ),
        th=15,
    ),
    1: KindTable(
        index=1, label="古びたお守り",
        skill1=(
            4, 5, 10, 11, 14, 15, 25, 26, 27, 28,
            29, 30, 31, 32, 35, 36, 38, 41, 42, 44,
            45, 47, 48, 49, 50, 65, 68, 70, 72, 73,
            76, 77, 78, 79, 81, 82, 84, 85, 86, 87,
            90, 92, 97, 99, 100, 103, 104, 106, 108, 109,
            114, 116, 122, 123, 124, 132,
        ),
        sp1=(
            (1, 5), (1, 5), (1, 5), (1, 5), (1, 5), (1, 8), (1, 5), (1, 7), (1, 7), (1, 7),
            (1, 7), (1, 7), (1, 5), (1, 6), (1, 5), (1, 5), (1, 6), (1, 6), (1, 6), (1, 6),
            (1, 5), (1, 5), (1, 5), (1, 5), (1, 5), (1, 3), (1, 5), (1, 5), (1, 5), (1, 5),
            (1, 5), (1, 5), (1, 6), (1, 6), (1, 6), (1, 6), (1, 6), (1, 6), (1, 6), (1, 6),
            (1, 5), (1, 6), (1, 6), (1, 5), (1, 5), (1, 7), (1, 7), (1, 5), (1, 5), (1, 6),
            (1, 7), (1, 6), (1, 5), (1, 5), (1, 5), (1, 7),
        ),
        skill2=(
            3, 4, 5, 17, 18, 19, 20, 21, 22, 23,
            24, 25, 26, 27, 28, 29, 30, 32, 33, 34,
            35, 36, 37, 39, 40, 41, 42, 44, 45, 47,
            48, 49, 50, 64, 65, 66, 68, 69, 70, 71,
            74, 76, 77, 78, 79, 80, 81, 82, 83, 84,
            85, 86, 87, 88, 89, 90, 91, 92, 93, 94,
            95, 97, 99, 100, 101, 103, 104, 105, 106, 107,
            108, 109, 110, 114, 115, 116, 117, 119, 120, 122,
            123, 124, 125, 132, 134, 135, 136, 143, 144, 145,
            146, 147, 148, 149, 150, 151, 152, 153, 154, 155,
            156, 157, 158, 159, 160,
        ),
        sp2=(
            (10, 13), (3, 3), (10, 3), (10, 10), (10, 10), (10, 13), (10, 13), (10, 13), (10, 13), (10, 13),
            (10, 13), (3, 3), (10, 13), (10, 13), (10, 13), (10, 13), (10, 13), (10, 4), (10, 8), (5, 5),
            (3, 3), (3, 3), (3, 3), (3, 3), (5, 8), (10, 4), (3, 3), (3, 4), (3, 3), (3, 3),
            (3, 3), (3, 3), (3, 3), (3, 3), (5, 5), (3, 3), (5, 5), (10, 10), (3, 3), (3, 3),
            (3, 3), (3, 3), (3, 3), (3, 4), (3, 4), (5, 5), (3, 4), (3, 4), (3, 3), (3, 4),
            (3, 4), (3, 4), (3, 4), (10, 10), (10, 10), (3, 3), (10, 10), (3, 4), (3, 3), (3, 3),
            (3, 3), (3, 4), (5, 5), (5, 5), (3, 3), (10, 10), (10, 10), (5, 5), (5, 5), (3, 3),
            (5, 5), (3, 3), (10, 12), (10, 9), (3, 3), (3, 4), (10, 12), (10, 12), (10, 10), (3, 3),
            (5, 5), (5, 5), (3, 3), (8, 10), (3, 3), (3, 3), (3, 3), (3, 3), (3, 3), (3, 3),
            (3, 3), (3, 3), (3, 3), (3, 3), (3, 3), (3, 3), (3, 3), (3, 3), (3, 3), (3, 3),
            (3, 3), (3, 3), (3, 3), (3, 3), (3, 3),
        ),
        slotvalue=(
            (8, 58, 88), (9, 59, 88), (16, 61, 89), (17, 62, 89), (23, 63, 89),
            (25, 65, 90), (31, 66, 90), (38, 68, 90), (45, 71, 91), (58, 76, 91),
            (63, 79, 92), (66, 80, 92), (71, 83, 94), (74, 84, 94), (78, 87, 96),
            (82, 90, 96), (86, 93, 98), (88, 94, 98), (91, 96, 99), (94, 97, 99),
        ),
        th=25,
    ),
    2: KindTable(
        index=2, label="光るお守り",
        skill1=(
            0, 1, 2, 3, 5, 6, 7, 13, 17, 18,
            19, 20, 21, 22, 23, 24, 26, 27, 28, 29,
            30, 32, 33, 38, 41, 44, 46, 51, 52, 53,
            54, 55, 62, 63, 68, 69, 72, 73, 78, 79,
            81, 84, 85, 86, 87, 88, 89, 91, 97, 98,
            99, 100, 103, 104, 106, 108, 109, 110, 113, 114,
            116, 117, 119, 120, 122, 123, 124, 126, 129, 131,
            132,
        ),
        sp1=(
            (1, 5), (1, 5), (1, 5), (1, 8), (1, 4), (1, 7), (1, 7), (1, 7), (1, 4), (1, 4),
            (1, 8), (1, 6), (1, 6), (1, 6), (1, 6), (1, 6), (1, 7), (1, 7), (1, 7), (1, 7),
            (1, 7), (1, 4), (1, 4), (1, 4), (1, 6), (1, 4), (1, 6), (1, 6), (1, 10), (1, 10),
            (1, 10), (1, 10), (1, 10), (1, 10), (1, 3), (1, 4), (1, 3), (1, 3), (1, 6), (1, 6),
            (1, 6), (1, 6), (1, 4), (1, 6), (1, 6), (1, 6), (1, 6), (1, 6), (1, 6), (1, 5),
            (1, 3), (1, 3), (1, 5), (1, 5), (1, 3), (1, 3), (1, 6), (1, 8), (1, 8), (1, 7),
            (1, 6), (1, 7), (1, 8), (1, 8), (1, 4), (1, 3), (1, 3), (1, 8), (1, 8), (1, 8),
            (1, 3),
        ),
        skill2=(
            0, 1, 2, 3, 6, 7, 8, 9, 12, 13,
            14, 15, 16, 17, 18, 19, 20, 21, 22, 23,
            24, 32, 40, 46, 51, 52, 53, 54, 55, 56,
            57, 58, 59, 60, 61, 62, 63, 65, 67, 68,
            69, 72, 73, 88, 89, 91, 98, 99, 100, 102,
            103, 104, 105, 106, 108, 110, 111, 112, 113, 117,
            118, 119, 120, 121, 123, 124, 126, 127, 128, 129,
            130, 131, 132, 133,
        ),
        sp2=(
            (10, 7), (10, 7), (10, 7), (10, 10), (10, 8), (10, 8), (10, 10), (10, 10), (10, 10), (10, 8),
            (5, 5), (5, 5), (10, 10), (7, 7), (7, 7), (10, 10), (10, 10), (10, 10), (10, 10), (10, 10),
            (10, 10), (4, 4), (5, 5), (10, 10), (8, 8), (10, 10), (10, 10), (10, 10), (10, 10), (10, 10),
            (10, 10), (10, 10), (10, 12), (10, 12), (10, 10), (10, 10), (10, 10), (3, 3), (10, 10), (5, 5),
            (7, 7), (5, 5), (5, 5), (8, 8), (8, 8), (8, 8), (5, 5), (5, 5), (5, 5), (10, 10),
            (7, 7), (7, 7), (8, 8), (5, 5), (5, 5), (10, 10), (10, 10), (10, 10), (10, 10), (4, 4),
            (10, 10), (10, 10), (10, 10), (10, 13), (5, 5), (5, 5), (10, 10), (10, 13), (10, 10), (10, 10),
            (10, 13), (10, 10), (5, 5), (10, 13),
        ),
        slotvalue=(
            (2, 72, 100), (9, 74, 100), (16, 76, 100), (23, 78, 100), (30, 80, 100),
            (37, 82, 100), (44, 84, 100), (51, 86, 100), (58, 88, 100), (75, 90, 100),
            (83, 92, 100), (87, 95, 100), (90, 97, 100), (92, 98, 100), (94, 99, 100),
            (95, 99, 100), (97, 100, 100), (98, 100, 100), (99, 100, 100), (99, 100, 100),
        ),
        th=35,
    ),
    3: KindTable(
        index=3, label="なぞのお守り",
        skill1=(
            0, 1, 2, 3, 6, 7, 8, 9, 12, 13,
            14, 16, 17, 18, 19, 20, 21, 22, 23, 24,
            46, 51, 52, 53, 54, 55, 56, 57, 58, 59,
            60, 61, 62, 63, 67, 69, 88, 89, 91, 98,
            102, 103, 104, 105, 110, 111, 112, 113, 118, 119,
            120, 121, 126, 127, 128, 129, 130, 131, 133,
        ),
        sp1=(
            (1, 5), (1, 5), (1, 5), (1, 8), (1, 7), (1, 7), (1, 10), (1, 10), (1, 10), (1, 7),
            (1, 3), (1, 5), (1, 4), (1, 4), (1, 8), (1, 6), (1, 6), (1, 6), (1, 6), (1, 6),
            (1, 6), (1, 8), (1, 8), (1, 8), (1, 8), (1, 8), (1, 8), (1, 8), (1, 8), (1, 8),
            (1, 8), (1, 8), (1, 8), (1, 8), (1, 5), (1, 4), (1, 6), (1, 6), (1, 6), (1, 4),
            (1, 8), (1, 3), (1, 3), (1, 10), (1, 8), (1, 8), (1, 8), (1, 8), (1, 8), (1, 8),
            (1, 8), (1, 10), (1, 8), (1, 10), (1, 8), (1, 8), (1, 10), (1, 8), (1, 10),
        ),
        skill2=(0,),
        sp2=((10, 7),),
        slotvalue=(
            (55, 100, 100), (60, 100, 100), (65, 100, 100), (70, 100, 100), (75, 100, 100),
            (80, 100, 100), (85, 100, 100), (90, 100, 100), (95, 100, 100), (99, 100, 100),
            (100, 100, 100), (100, 100, 100), (100, 100, 100), (100, 100, 100), (100, 100, 100),
            (100, 100, 100), (100, 100, 100), (100, 100, 100), (100, 100, 100), (100, 100, 100),
        ),
        th=100,
    ),
}


# ---------------------------------------------------------------------------
# 結果表現用データクラス
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RawCharm:
    """getcharm() の生の戻り値 (元コードの c[0..7] にそのまま対応)。"""

    skill1_idx: int
    skill1_pts: int
    skill2_idx: int
    skill2_pts: int
    slot: int
    fill: int
    slot_roll: int
    rarity: int


@dataclass(frozen=True)
class Charm:
    """表示用に名前解決済みのお守り情報。"""

    skill1_name: str
    skill1_pts: int
    skill2_name: str | None
    skill2_pts: int
    slot: int
    rarity: int
    rarity_color: str

    @classmethod
    def from_raw(cls, raw: RawCharm) -> "Charm":
        # getcharm() 内では skill1 と skill2 が同一スキルに衝突した場合、
        # tmp2 (スロット計算用のローカル変数) は 0 に補正される一方で、
        # 戻り値の c[2]/c[3] (=skill2_idx/skill2_pts) は補正前の値のまま
        # 返る (ノートブック側の search()/search_greater() が
        # 「c[2]==-1 or c[2]==c[0]」を毎回自前でチェックしているのは
        # まさにこの生値のクセを呼び出し側で吸収するため)。
        # 実際のゲームでは同一スキルが2つ付くお守りは存在しないため、
        # 表示用に変換するこの唯一の場所で「衝突 = スキル2なし」として
        # 統一的に扱う。エンジンの乱数計算・フレーム消費自体には一切
        # 手を加えていない。
        is_collision = raw.skill2_idx != -1 and raw.skill2_idx == raw.skill1_idx
        if raw.skill2_idx == -1 or is_collision:
            skill2_name = None
            skill2_pts = 0
        else:
            skill2_name = SKILL_NAMES[raw.skill2_idx]
            skill2_pts = raw.skill2_pts
        return cls(
            skill1_name=SKILL_NAMES[raw.skill1_idx],
            skill1_pts=raw.skill1_pts,
            skill2_name=skill2_name,
            skill2_pts=skill2_pts,
            slot=raw.slot,
            rarity=raw.rarity,
            rarity_color=RARITY_COLORS.get(raw.rarity, "#e8e8ea"),
        )

    def skill_text(self) -> str:
        s1 = f"{self.skill1_name.strip()} +{self.skill1_pts}"
        if self.skill2_name is None:
            return s1
        return f"{s1} / {self.skill2_name.strip()} +{self.skill2_pts}"


@dataclass(frozen=True)
class CharmResult:
    frame: int
    elapsed: tuple[int, int, int, int, int]
    charm: Charm

    def elapsed_text(self) -> str:
        d, h, m, s, fr = self.elapsed
        return f"{d}日 {h}時間 {m}分 {s}秒 {fr}f"


@dataclass(frozen=True)
class FrameResult:
    """報酬列・調合列検索の結果フレーム (お守り情報なし)。"""

    frame: int
    elapsed: tuple[int, int, int, int, int]

    def elapsed_text(self) -> str:
        d, h, m, s, fr = self.elapsed
        return f"{d}日 {h}時間 {m}分 {s}秒 {fr}f"


@dataclass(frozen=True)
class SearchTarget:
    """GUIから渡す検索条件。"""

    skill1_idx: int | None
    skill1_pts: int
    skill2_idx: int | None
    skill2_pts: int
    slot: int
    origin: int

    def as_raw(self) -> tuple[int, int, int, int, int, int]:
        id1 = -1 if self.skill1_idx is None else self.skill1_idx
        id2 = -1 if self.skill2_idx is None else self.skill2_idx
        return id1, self.skill1_pts, id2, self.skill2_pts, self.slot, self.origin


@dataclass(frozen=True)
class AimPointRow:
    label: str
    count: int
    pattern: str


# ---------------------------------------------------------------------------
# KMP + ストライド検索 (報酬列・調合列フレーム特定用)
# ---------------------------------------------------------------------------

def kmp_prefix(pattern: list[int]) -> list[int]:
    """KMPの失敗関数(prefix table)を計算する。"""
    n = len(pattern)
    pi = [0] * n
    j = 0
    for i in range(1, n):
        while j > 0 and pattern[i] != pattern[j]:
            j = pi[j - 1]
        if pattern[i] == pattern[j]:
            j += 1
        pi[i] = j
    return pi


def search_stride(
    engine: "MHXXEngine",
    step: int,
    pattern: list[int],
    stride: int,
    lut: list[int],
    *,
    should_stop: Callable[[], bool] | None = None,
) -> Iterator[int]:
    """KMP法を用いてストライド付き乱数列からパターンを検索する。

    engine.w & 0xFFFF を % 100 した値を lut でシンボルに変換し、
    stride フレームおきに生成されるシンボル列の中から pattern を探す。

    Yields:
        パターン先頭位置 (0 始まりのステップインデックス)
    """
    n = len(pattern)
    if n == 0:
        return
    pi = kmp_prefix(pattern)
    state = [0] * stride
    r = 0
    for i in range(step):
        if should_stop is not None and i % 4096 == 0 and should_stop():
            return
        symbol = lut[(engine.w & 0xFFFF) % 100]
        engine.ascend()
        k = state[r]
        while k > 0 and pattern[k] != symbol:
            k = pi[k - 1]
        if pattern[k] == symbol:
            k += 1
        if k == n:
            yield i - stride * (n - 1)
            k = pi[n - 1]
        state[r] = k
        r += 1
        if r == stride:
            r = 0


def reward_lookup_table(reward_table: dict[str, int]) -> list[int]:
    """報酬テーブルから lut[0..99] → シンボルインデックス の配列を生成する。"""
    thresholds = list(reward_table.values())
    lut = [0] * 100
    prev = 0
    for i, th in enumerate(thresholds):
        for v in range(prev, th):
            lut[v] = i
        prev = th
    return lut


def combo_lookup_table() -> list[int]:
    """調合の乱数 0~99 → 調合品数 (2/3/4) の lut を生成する。"""
    lut = [2] * 25 + [3] * 50 + [4] * 25
    return lut


def check_reward_bonus(observed_len: int, four_nums: list[int], bonus_threshold: int) -> bool:
    """報酬ボーナス判定。ノートブックの check_bonus() と同一ロジック。"""
    flags = [(n & 0x1F) < bonus_threshold for n in four_nums]
    if observed_len == 8:
        return all(flags)
    k = observed_len - 4
    return (not flags[3]) and all(flags[3 - k:3])


def find_invalid_combo_differences(differences: list[int]) -> list[int]:
    """調合差分列の中で 2/3/4 以外の値があるインデックスを返す。"""
    return [i for i, d in enumerate(differences) if d not in (2, 3, 4)]


def parse_combo_sequence(combo_positions: list[int]) -> tuple[list[int], list[int]]:
    """調合数値列 → (差分列, 不正な差分のインデックス一覧)。

    MHXXEngine.search_combo() が内部で行う前処理 (先頭3つを捨てる/末尾の
    99を捨てる/差分を取る) を、検索を実行する前にUI側で入力検証するために
    切り出したもの。search_combo() 自体のロジックは変更していない。
    差分列が短すぎる場合 (長さ1以下) は ([], []) を返す。
    """
    raw = list(combo_positions)
    pos = raw[3:]
    if pos and pos[-1] == 99:
        pos = pos[:-1]
    if len(pos) <= 1:
        return [], []
    dif = [pos[i + 1] - pos[i] for i in range(len(pos) - 1)]
    return dif, find_invalid_combo_differences(dif)


# ---------------------------------------------------------------------------
# コンテニュー連打法
# ---------------------------------------------------------------------------
# 力尽きた(気絶上限等)後の「コンテニューするか」選択画面で、コンテニューを
# 1回選択する度にRNGが一定数消費される(消費フレーム数は選択にかかる時間や
# その後の演出等に依存し、フレーム単位の細かい調整は効かないが、遠いフレーム
# まで大まかに・機械を使わず・何度でも再現よく飛ばせる手段として使われる)。
# ここでは実測値として1回あたり700フレーム消費するものとして計算する。
# なお、この「フレーム数」はRNGの内部ティック数そのものであり、fps
# (表示・実時間換算のレート) には依存しない。

CONTINUE_MASH_FRAME_COST = 700


def continue_mash_info(frame: int) -> tuple[int, int, int]:
    """コンテニュー連打法で指定フレームに到達するための情報を返す。

    連打では歩進しかできない(後戻りできない)ため、目的フレームぴったりに
    止められるとは限らない。そのため「目的フレームを超えない最大到達点」を
    連打の目標とする。

    戻り値: (必要連打回数, 連打だけで到達できる最大フレーム, 目的フレームまでの
             残りフレーム数(0〜699。連打後に別手段で詰める分))
    """
    if frame <= 0:
        return 0, 0, 0
    mashes = frame // CONTINUE_MASH_FRAME_COST
    reached = mashes * CONTINUE_MASH_FRAME_COST
    remainder = frame - reached
    return mashes, reached, remainder


# ---------------------------------------------------------------------------
# GF(2)多項式演算 (jump()の高速フレーム送り用)
# ---------------------------------------------------------------------------

def _poly_mul(p1: int, p2: int) -> int:
    res = 0
    while p2 > 0:
        if p2 & 1:
            res ^= p1
        p1 <<= 1
        p2 >>= 1
    return res


def _poly_mod(p: int, m: int) -> int:
    m_len = m.bit_length()
    while (delta_deg := p.bit_length() - m_len) >= 0:
        p ^= m << delta_deg
    return p


def _poly_pow_mod(base: int, exp: int, mod: int) -> int:
    res = 1
    base = _poly_mod(base, mod)
    while exp > 0:
        if exp & 1:
            res = _poly_mod(_poly_mul(res, base), mod)
        base = _poly_mod(_poly_mul(base, base), mod)
        exp >>= 1
    return res


def _rand(num1: int, num2: int) -> int:
    """aim point計算 (マカフシギ/天運の色抽選) 専用の別系統の簡易乱数。"""
    num1 &= 0xFFFF
    for _ in range(num2):
        num1 = max(num1, 1)
        num1 = num1 * 176 % 65363
    return num1


def _halcyon_colors(seed: int, rank: int) -> list[int]:
    values = {1: (3, 1), 2: (4, 1), 3: (4, 2), 4: (5, 2)}
    width, minimum = values[rank]
    a = 1
    num = _rand(seed, a) % width + minimum
    a += 1
    b = [0] * num
    for i in range(num):
        while _rand(seed, a) % 100 >= 85:
            a += 1
        c = _rand(seed, a) % 100
        a += 1
        b[i] = 3 if c < 10 else 2 if c < 55 else 1
    return b


def _juju_colors(seed: int, rank: int) -> list[int]:
    values = {1: (2, 0, 1, 1), 2: (2, 0, 2, 1), 3: (2, 1, 2, 1), 4: (1, 2, 2, 1)}
    width1, min1, width2, min2 = values[rank]
    num1 = _rand(seed, 1) % width1 + min1
    num2 = _rand(seed, 2) % width2 + min2
    return [0] * num1 + [1] * num2


def _format_aimpoint(array: list[bool], predicate: Callable[[bool], bool]) -> AimPointRow:
    """show_aimpoint() 相当 (printの代わりに文字列を組み立てて返す)。"""
    count = sum(1 for v in array if predicate(v))
    chars: list[str] = []
    for i in reversed(range(len(array))):
        if i % 10 == 0:
            chars.append(" ")
        if i == 0:
            chars.append("[")
        chars.append("◯" if predicate(array[i]) else "Ｘ")
    chars.append("]")
    return AimPointRow(label="", count=count, pattern="".join(chars))


# ---------------------------------------------------------------------------
# エンジン本体
# ---------------------------------------------------------------------------

class MHXXEngine:
    """お守り乱数エンジン本体。1インスタンス=1つの独立した乱数状態を持つ。"""

    def __init__(self, kind: int = 0) -> None:
        self.table: KindTable = KIND_TABLES[kind]
        self.x = self.y = self.z = self.w = 0
        self.t = 0
        self.f = 0
        self.r0 = self.r1 = self.r2 = self.r3 = self.r4 = self.r5 = self.r6 = 0

    def set_kind(self, kind: int) -> None:
        self.table = KIND_TABLES[kind]

    @property
    def kind(self) -> int:
        return self.table.index

    @property
    def th(self) -> int:
        return self.table.th

    # -- RNGコア -----------------------------------------------------------
    def _init_state(self) -> None:
        self.x, self.y, self.z, self.w = _SEED
        self.t = 0
        self.f = 0

    def ascend(self) -> None:
        t = (self.x ^ (self.x << 15)) & _MASK32
        self.x = self.y
        self.y = self.z
        self.z = self.w
        self.w = self.w ^ (self.w >> 21) ^ t ^ (t >> 4)
        self.t = t
        self.f += 1

    def descend(self) -> None:
        t = self.w ^ self.z ^ (self.z >> 21)
        t ^= t >> 4
        t ^= t >> 8
        t ^= t >> 16
        self.w = self.z
        self.z = self.y
        self.y = self.x
        self.x = (t ^ (t << 15) ^ (t << 30)) & _MASK32
        self.t = t
        self.f -= 1

    def roll(self) -> None:
        self.r0, self.r1, self.r2, self.r3, self.r4, self.r5, self.r6 = (
            self.r1, self.r2, self.r3, self.r4, self.r5, self.r6, self.w,
        )
        self.ascend()

    def jump(self, frame: int) -> None:
        """任意フレームへ多項式演算で高速に移動し、r0..r6履歴も7回分再構築する。"""
        self._init_state()
        r_poly = _poly_pow_mod(0b10, frame % (2**128 - 1), _JUMP_MODULUS)
        s_x = s_y = s_z = s_w = 0
        while r_poly > 0:
            if r_poly & 1:
                s_x ^= self.x
                s_y ^= self.y
                s_z ^= self.z
                s_w ^= self.w
            r_poly >>= 1
            self.ascend()
        self.x, self.y, self.z, self.w = s_x, s_y, s_z, s_w
        self.f = frame
        for _ in range(7):
            self.roll()

    # -- お守り生成 ----------------------------------------------------------
    def slot(self, fill: int, num1: int) -> int:
        sv = self.table.slotvalue[fill - 1]
        if num1 >= sv[2]:
            return 3
        if num1 >= sv[1]:
            return 2
        if num1 >= sv[0]:
            return 1
        return 0

    def rare(self, slot_count: int, fill: int) -> int:
        num1 = slot_count * 2 + fill
        kind = self.table.index
        if kind == 0:
            return 10 if num1 >= 13 else 9 if num1 >= 8 else 8
        if kind == 1:
            return 7 if num1 >= 13 else 6 if num1 >= 8 else 5
        if kind == 2:
            return 4 if num1 >= 8 else 3
        return 2 if num1 >= 8 else 1

    def getcharm(self, origin: int) -> RawCharm:
        t = self.table
        id1 = self.r0 % len(t.skill1)
        id2 = self.r3 % len(t.skill2)
        s1 = t.sp1[id1][1]
        s2 = t.sp2[id2][1]
        c0 = t.skill1[id1]
        tmp1 = self.r1 % (t.sp1[id1][1] - t.sp1[id1][0] + 1) + t.sp1[id1][0]
        c1 = tmp1
        if self.r2 % 100 >= t.th:
            c2 = t.skill2[id2]
            if origin == 1 and self.r4 % 2 == 0:
                q4, q5 = self.r5, self.r6
                tmp2 = q4 % (t.sp2[id2][0] + 1) - t.sp2[id2][0]
            else:
                if origin == 1:
                    q4, q5 = self.r5, self.r6
                else:
                    q4, q5 = self.r4, self.r5
                tmp2 = q4 % t.sp2[id2][1] + 1
            c3 = tmp2
            if t.skill1[id1] == t.skill2[id2] or tmp2 < 0:
                tmp2 = 0
        else:
            c2 = -1
            tmp2 = 0
            c3 = 0
            q5 = self.r3
        tmp0 = (tmp1 * s2 + tmp2 * s1) * 10 // (s1 * s2)
        c6 = q5 % 100
        c4 = self.slot(tmp0, c6)
        c5 = tmp0
        c7 = self.rare(c4, c5)
        return RawCharm(c0, c1, c2, c3, c4, c5, c6, c7)

    @staticmethod
    def watch(frame: int, fps: int = 30) -> tuple[int, int, int, int, int]:
        """フレーム数を日/時/分/秒/フレーム(端数)の経過時間に変換する。

        fps: 経過時間の換算に使うフレームレート。
             既定値30は本来のハード (3DS/Switch) 想定。
             Switch2で60fps動作する場合は fps=60 を渡すと、同じフレーム数
             でも実時間換算が半分になる (フレーム数=RNG内部ティック数
             そのものは fps に依存せず変化しない)。
        """
        frames_per_day  = fps * 86400
        frames_per_hour = fps * 3600
        frames_per_min  = fps * 60
        d  = frame // frames_per_day
        h  = (frame % frames_per_day) // frames_per_hour
        m  = (frame % frames_per_hour) // frames_per_min
        s  = (frame % frames_per_min) // fps
        fr = frame % fps
        return d, h, m, s, fr

    def _make_result(self, raw: RawCharm, frame: int) -> CharmResult:
        return CharmResult(frame=frame, elapsed=self.watch(frame), charm=Charm.from_raw(raw))

    # -- 検索 (スキル指定) ---------------------------------------------------
    def search(
        self,
        start: int,
        step: int,
        target: SearchTarget,
        *,
        should_stop: Callable[[], bool] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        progress_interval: int = 100_000,
    ) -> Iterator[CharmResult]:
        """完全一致検索。"""
        id1, sp1, id2, sp2, slot_target, origin = target.as_raw()
        if id1 == -1 and id2 == -1:
            id1 = 0
        len1 = len(self.table.skill1)
        len2 = len(self.table.skill2)
        skip2 = id2 == -1
        self.jump(start)
        for i in range(step):
            if should_stop is not None and should_stop():
                return
            self.roll()
            if self.r0 % len1 == id1 and (
                skip2 or (self.r2 % 100 >= self.th and self.r3 % len2 == id2)
            ):
                c = self.getcharm(origin)
                if c.skill1_pts == sp1 and c.slot == slot_target:
                    if skip2:
                        cond = c.skill2_idx == -1 or c.skill2_idx == c.skill1_idx or c.skill2_pts == 0
                    else:
                        cond = c.skill2_pts == sp2
                    if cond:
                        yield self._make_result(c, self.f - 7)
            if on_progress is not None and progress_interval and i % progress_interval == 0:
                on_progress(i, step)

    def search_greater(
        self,
        start: int,
        step: int,
        target: SearchTarget,
        *,
        should_stop: Callable[[], bool] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        progress_interval: int = 100_000,
    ) -> Iterator[CharmResult]:
        """しきい値以上検索。"""
        id1, sp1, id2, sp2, slot_target, origin = target.as_raw()
        len1 = len(self.table.skill1)
        len2 = len(self.table.skill2)
        skip1 = id1 == -1
        skip2 = id2 == -1
        self.jump(start)
        for i in range(step):
            if should_stop is not None and should_stop():
                return
            self.roll()
            if (skip1 or self.r0 % len1 == id1) and (
                skip2 or (self.r2 % 100 >= self.th and self.r3 % len2 == id2)
            ):
                c = self.getcharm(origin)
                if skip1 and c.skill1_idx == c.skill2_idx:
                    continue
                if (
                    (skip1 or c.skill1_pts >= sp1)
                    and (skip2 or c.skill2_pts >= sp2)
                    and c.slot >= slot_target
                ):
                    yield self._make_result(c, self.f - 7)
            if on_progress is not None and progress_interval and i % progress_interval == 0:
                on_progress(i, step)

    # -- 報酬列検索 ---------------------------------------------------------
    def search_reward(
        self,
        start: int,
        step: int,
        bonus_threshold: int,
        target: list[str],
        reward_table: dict[str, int],
        *,
        should_stop: Callable[[], bool] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> Iterator[FrameResult]:
        """アイテム報酬列からフレームを特定する (search_reward 相当)。

        Args:
            bonus_threshold: ボーナス判定しきい値 (報酬テーブルで設定)
            target: 観測した報酬アイテム名のリスト (4〜8個)
            reward_table: {アイテム名: 累積しきい値 0-100} の dict (順序保持)
        """
        if not (4 <= len(target) <= 8):
            return

        keys = list(reward_table.keys())
        reward_index = {k: i for i, k in enumerate(keys)}
        try:
            pattern = [reward_index[t] for t in target]
        except KeyError:
            return

        lut = reward_lookup_table(reward_table)

        # 検索用に別エンジンを作成 (self の状態を汚さない)
        se = MHXXEngine(self.kind)
        se.jump(start)
        for _ in range(7):
            se.descend()

        hits = list(search_stride(se, step, pattern, 1, lut, should_stop=should_stop))

        for hit_i, i in enumerate(hits):
            verify_frame = start + i - 7 - 1
            self.jump(verify_frame)
            four_nums = [self.x, self.y, self.z, self.w]
            if check_reward_bonus(len(target), four_nums, bonus_threshold):
                result_frame = start + i - min(len(target) - 3, 4)
                yield FrameResult(frame=result_frame, elapsed=self.watch(result_frame))
            if on_progress is not None:
                on_progress(hit_i + 1, len(hits))

    # -- 調合列検索 ---------------------------------------------------------
    def search_combo(
        self,
        start: int,
        step: int,
        combo_positions: list[int],
        *,
        should_stop: Callable[[], bool] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> Iterator[FrameResult]:
        """調合品数の列からフレームを特定する (search_combo 相当)。

        Args:
            combo_positions: 画面で確認した調合数値列 (スペース区切りの整数リスト)
                              例: [0, 3, 6, 9, 11, 13, 16, ...]
        """
        raw = list(combo_positions)
        pos = raw[3:]  # 先頭3つをスキップ
        if pos and pos[-1] == 99:
            pos = pos[:-1]  # 末尾の99を除去
        if len(pos) <= 1:
            return

        dif = [pos[i + 1] - pos[i] for i in range(len(pos) - 1)]
        invalid = find_invalid_combo_differences(dif)
        if invalid:
            return

        lut = combo_lookup_table()

        se = MHXXEngine(self.kind)
        se.jump(start)
        for _ in range(7):
            se.descend()

        hits = list(search_stride(se, step, dif, 5, lut, should_stop=should_stop))

        for hit_i, i in enumerate(hits):
            j = i - 5 * 3 - 15 + 2 * (len(raw) - 1)
            result_frame = start + j
            if result_frame >= 0:
                yield FrameResult(frame=result_frame, elapsed=self.watch(result_frame))
            if on_progress is not None:
                on_progress(hit_i + 1, len(hits))

    # -- 周辺確認 (around) -------------------------------------------------
    def around(self, frame: int, num1: int, origin: int) -> list[tuple[int, Charm]]:
        """指定フレームの前後 num1 件ずつのお守りを (オフセット, Charm) で返す。"""
        results: list[tuple[int, Charm]] = []
        self.jump(frame - num1)
        for i in range(-num1, num1):
            offset = self.f - 7 - frame
            results.append((offset, Charm.from_raw(self.getcharm(origin))))
            self.roll()
            if i == -1:
                results.append((0, Charm.from_raw(self.getcharm(origin))))
                self.roll()
        return results

    # -- 連続お守り表示 (sequence_charm) ------------------------------------
    def sequence_charm(
        self,
        frame: int,
        count: int,
        origin: int,
    ) -> list[tuple[int, Charm]]:
        """指定フレームから count 個分の連続したお守りを (フレーム, Charm) で返す。

        Args:
            frame: 開始フレーム
            count: 表示個数
            origin: 0=マカ, 1=炭鉱
        """
        results: list[tuple[int, Charm]] = []
        self.jump(frame)
        for _ in range(count):
            results.append((self.f - 7, Charm.from_raw(self.getcharm(origin))))
            self.roll()
        return results

    # -- 狙い目 (aim point) ------------------------------------------------
    def aimpoint_blue(self) -> int:
        """風化したお守り(kind0)専用の簡易 aim point。有効な狙い目数を返す。"""
        num1 = 1
        for _ in range(9):
            self.descend()
        if self.w % 100 < self.th:
            num1 += 1
        for _ in range(2):
            self.descend()
        if self.w % 100 >= self.th:
            num1 += 1
        for _ in range(11):
            self.ascend()
        return num1

    def _aimpoint_melding(
        self, num1: int, color_func: Callable[[int, int], list[int]], rank: int
    ) -> AimPointRow:
        e = self.table.index
        a = [0] * (num1 + 3)
        b = [False] * (num1 + 3)
        for _ in range(7):
            self.descend()
        for i in range(num1):
            self.descend()
            a[i + 3] = self.w
        for _ in range(num1 + 7):
            self.ascend()

        for i in range(num1):
            c = i
            d = color_func(a[i + 3], rank)
            for j in d:
                self.set_kind(j)
                if c == 0 and e == j:
                    b[i] = True
                if c >= 0:
                    c -= 4 if a[c] % 100 < self.th else 6
        row = _format_aimpoint(b, lambda v: v)
        self.set_kind(e)
        return row

    def aimpoint_halcyon(self, show_all_ranks: bool = True) -> list[AimPointRow]:
        ranks = [4, 3, 2, 1] if show_all_ranks else [4]
        rows = []
        for rank in ranks:
            row = self._aimpoint_melding((6 - 1) * 6 + 1, _halcyon_colors, rank)
            rows.append(AimPointRow(label=f"rank{rank}", count=row.count, pattern=row.pattern))
        return rows

    def aimpoint_juju(self, show_all_ranks: bool = True) -> list[AimPointRow]:
        ranks = [4, 3, 2, 1] if show_all_ranks else [4]
        rows = []
        for rank in ranks:
            row = self._aimpoint_melding((4 - 1) * 6 + 1, _juju_colors, rank)
            rows.append(AimPointRow(label=f"rank{rank}", count=row.count, pattern=row.pattern))
        return rows

    def aimpoint_quest(self, num_of_charms: int) -> AimPointRow:
        num1 = max(2, num_of_charms)
        num = (num1 - 1) * 7 + 1
        a = [0] * num
        b = [num1 + 1] * num
        b[0] = 1
        for _ in range(7):
            self.descend()
        for i in range(num - 3):
            self.descend()
            a[i + 3] = self.w
        for _ in range(num + 4):
            self.ascend()
        for i in range(num):
            if i + 4 < num and a[i + 4] % 100 < self.th:
                b[i + 4] = min(b[i + 4], b[i] + 1)
            if i + 7 < num and a[i + 7] % 100 >= self.th:
                b[i + 7] = min(b[i + 7], b[i] + 1)
        return _format_aimpoint(b, lambda v: v <= num1)
