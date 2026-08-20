# Arduino Leonardo スケッチ — MHXX お守り自動ループ

## 概要

Arduino Leonardo が Switch の **USB コントローラー** として動作し、
スマホアプリから `NEXT` コマンドを受け取るたびにボタンシーケンスを実行します。
お守り画面が表示されたら `READY` をアプリに送信し、アプリが OCR で結果を確認します。

```
スマホ ──USB─→ Arduino Leonardo ──USB─→ Switch (コントローラーとして認識)
スマホ ←USB── Arduino Leonardo          (シリアル通信でコマンド受信/READY送信)
                                  ↑
                          USB ハブ経由で両方を 1 本の USB OTG に集約
```

---

## 必要なもの

| 品目 | 詳細 |
|------|------|
| Arduino Leonardo | VID=0x2341, PID=0x0036 |
| SwitchControlLibrary | https://github.com/celclow/SwitchControlLibrary |
| USB ハブ (USB-A × 3 以上) | Switch + スマホ OTG + Arduino を繋ぐ |
| USB OTG ケーブル | スマホ USB-C → USB-A 変換 |

---

## ライブラリのインストール

1. Arduino IDE を開く
2. スケッチ → ライブラリを管理 → 「SwitchControlLibrary」で検索
3. インストール

---

## スケッチ本体

以下をコピーして Arduino IDE に貼り付け、Leonardo に書き込んでください。

```cpp
/**
 * MHXX_AutoLoop.ino
 * MHXX お守り自動ループ コントローラー for Arduino Leonardo
 *
 * プロトコル (115200 bps / 8N1):
 *   受信: "NEXT\n" → ボタンシーケンス実行 → "READY\n" 送信
 *   受信: "STOP\n" → 何もしない → "OK\n" 送信
 */

#include <SwitchControlLibrary.h>

// シリアル設定
const long BAUD = 115200;

// ボタン押下ヘルパー
void pressBtn(uint16_t btn, unsigned long holdMs, unsigned long releaseMs) {
    SwitchControlLibrary().pressButton(btn);
    delay(holdMs);
    SwitchControlLibrary().releaseButton(btn);
    delay(releaseMs);
}

// ハットスイッチヘルパー (方向キー)
void pressHat(uint8_t dir, unsigned long holdMs, unsigned long releaseMs) {
    SwitchControlLibrary().moveHat(dir);
    delay(holdMs);
    SwitchControlLibrary().moveHat(DPAD_CENTER);
    delay(releaseMs);
}

/**
 * お守り確認→再ロールのボタンシーケンス
 *
 * 【重要】このシーケンスはゲームの状態によって異なります。
 * 以下は「マカフシギ調合でお守りを生成し直す」一例です。
 * ご自身の手順に合わせて編集してください。
 *
 * 目安:
 *   - A ボタン: 決定 / 次へ
 *   - B ボタン: キャンセル / 戻る
 *   - delay() の引数は ms 単位 (アニメーション速度に合わせて調整)
 */
void performNextLoop() {
    // ① 現在のお守り画面からキャンセルして戻る
    pressBtn(Button::B, 80, 800);

    // ② 再度「調合/採掘」メニューに入る (Aボタン)
    pressBtn(Button::A, 80, 1000);

    // ③ 確認ダイアログを進める
    pressBtn(Button::A, 80, 500);
    pressBtn(Button::A, 80, 2000);  // アニメーション待ち

    // ④ 結果画面が出たら READY を送信 → スマホが OCR を実行
    // (ここまで来た時点でお守り結果が画面に表示されている想定)
}

// ------------------------------------------------------------------

void setup() {
    Serial.begin(BAUD);
    SwitchControlLibrary().begin();
    delay(500);
    // 起動確認
    Serial.println("BOOT");
}

void loop() {
    if (Serial.available() > 0) {
        String cmd = Serial.readStringUntil('\n');
        cmd.trim();

        if (cmd == "NEXT") {
            performNextLoop();
            // スマホに「画面表示完了 → OCR してください」を通知
            Serial.println("READY");

        } else if (cmd == "STOP") {
            // ループ停止 (何もしない)
            Serial.println("OK");
        }
    }
}
```

---

## ボタンシーケンスのカスタマイズ

`performNextLoop()` の中身はプレイスタイルによって変わります。
以下を参考に編集してください。

| 状況 | 典型的なシーケンス |
|------|-------------------|
| マカフシギ調合 | B → A → A (確認) → 待機 |
| 炭鉱採掘 (リセット法) | HOME → … → A (ロード) → 待機 |
| ルームサービス | B → A → A → 待機 |

---

## タイミング調整のコツ

- `delay()` の値はゲームのアニメーション速度に合わせてください
- スマホアプリの「待機時間」スピナーは **Arduino の処理合計時間 + 余裕 1〜2 秒** に設定
- Arduino から `READY` が届けば待機時間より早く OCR が走ります

---

## 接続図

```
Nintendo Switch
   USB-C ─────────────────────┐
                              │
                        [USB ハブ]
                         │       │
              USB-A ─────┘   USB-A ──── Arduino Leonardo
                                              │
                                        USB ─┘ (OTG アダプター経由)
                                              │
                                       Android スマホ
```

---

## トラブルシューティング

| 症状 | 対処 |
|------|------|
| Arduino が認識されない | USB OTG の「許可」ダイアログで「OK」を選ぶ |
| Switch がコントローラーとして認識しない | Leonardo に正しくスケッチが書き込まれているか確認 |
| `READY` が届かない | `performNextLoop()` 最後の `Serial.println("READY")` が実行されているか確認 |
| OCR が合わない | スマホの「待機時間」を長くしてお守り画面が完全表示されてから撮影させる |
| 文字化け | ボーレートが 115200 になっているか確認 |
