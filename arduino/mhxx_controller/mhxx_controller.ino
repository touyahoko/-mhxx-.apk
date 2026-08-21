/**
 * mhxx_controller.ino
 * Arduino Leonardo 用  Nintendo Switch Pro Controller エミュレーター
 * + スマホ(またはPC)からのシリアルコマンドインターフェース
 *
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 * 接続構成 (写真の通り)
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 *
 *  スマホ (USB-C)
 *    └─ OTG アダプター (USB-C → USB-A)
 *        └─ ANYOYO キャプチャーカード / USB ハブ
 *            ├─ USB-A → [このボード] Arduino Leonardo
 *            │             ├─ CDC シリアル → スマホがコマンドを送受信
 *            │             └─ HID Gamepad → Switch が Proコントローラーとして認識
 *            └─ 映像入力 (Switch USB-C) → UVC カメラとしてスマホへ
 *
 *  Arduino Leonardo は「コンポジット USB デバイス」として動作:
 *    - スマホ側: CDC/ACM シリアル (115200bps) でコマンドを受け取る
 *    - Switch側: USB HID Pro Controller としてボタン入力を送る
 *  これにより 1 本の USB ケーブル + ANYOYO ハブで両方を同時に実現する。
 *
 *  必要なもの:
 *    - Arduino Leonardo (ATmega32U4)
 *    - ANYOYO または同等の USB キャプチャー付きハブ
 *    - USB-C OTG アダプター (スマホ接続用)
 *
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 * Switch への認識設定 (必須! boards.txt の変更)
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 *  Arduino IDE のインストール先にある
 *  hardware/arduino/avr/boards.txt を開き、
 *  leonardo.vid.0 / pid.0 の行を以下に変更する:
 *
 *    leonardo.vid.0=0x057E    <- Nintendo Co., Ltd
 *    leonardo.pid.0=0x2009    <- Pro Controller
 *
 *  変更後、Arduino IDE を再起動してからスケッチを書き込む。
 *  これにより Switch が「Proコントローラー」として認識する。
 *
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 * コマンド仕様 (改行 \n 区切り)
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 *  送信 (スマホ → Arduino):
 *    READY              接続確認 → "OK\n"
 *    PRESS:A            A ボタン 1 回プレス → "OK\n"
 *    PRESS:B            B ボタン 1 回プレス → "OK\n"
 *    PRESS:X            X ボタン 1 回プレス → "OK\n"
 *    PRESS:Y            Y ボタン 1 回プレス → "OK\n"
 *    PRESS:L            L ボタン 1 回プレス → "OK\n"
 *    PRESS:R            R ボタン 1 回プレス → "OK\n"
 *    PRESS:ZL           ZL ボタン 1 回プレス
 *    PRESS:ZR           ZR ボタン 1 回プレス
 *    PRESS:PLUS         + ボタン 1 回プレス
 *    PRESS:MINUS        - ボタン 1 回プレス
 *    PRESS:HOME         HOME ボタン 1 回プレス
 *    PRESS:UP           十字キー上 1 回
 *    PRESS:DOWN         十字キー下 1 回
 *    HOLD:A:<n>         A を n フレーム(16ms/frame)保持 → "OK\n"
 *    MASH:A:<n>         A を n 回交互にマッシュ (フレーム前進用)
 *    WAIT:<n>           n フレーム何も押さずに待つ → "OK\n"
 *    SEQ:APPRAISE       お守り鑑定シーケンス → "DONE:APPRAISE\n"
 *    SEQ:BACK           キャンセル/戻りシーケンス → "DONE:BACK\n"
 *    STOP               現在の処理を中断 → "OK\n"
 *
 *  受信 (Arduino → スマホ):
 *    "OK\n"             成功
 *    "DONE:<SEQ>\n"     シーケンス完了
 *    "ERR:<reason>\n"   エラー
 */

#include <HID.h>

// ───────────────────────────────────────────────────────────
// Switch Pro Controller USB HID 記述子
//   参考: https://github.com/dekuNukem/Nintendo_Switch_Reverse_Engineering
// ───────────────────────────────────────────────────────────
static const uint8_t _hidReportDesc[] PROGMEM = {
  0x05, 0x01,        // Usage Page (Generic Desktop)
  0x09, 0x05,        // Usage (Gamepad)
  0xA1, 0x01,        // Collection (Application)
  // ─ ボタン 14 個 (Y B A X L R ZL ZR MINUS PLUS L3 R3 HOME CAPTURE) ─
  0x15, 0x00,        //   Logical Min (0)
  0x25, 0x01,        //   Logical Max (1)
  0x75, 0x01,        //   Report Size (1)
  0x95, 0x0E,        //   Report Count (14)
  0x05, 0x09,        //   Usage Page (Button)
  0x19, 0x01,        //   Usage Min (Button 1)
  0x29, 0x0E,        //   Usage Max (Button 14)
  0x81, 0x02,        //   Input (Data, Variable, Absolute)
  // ─ 2 ビットパディング ─
  0x75, 0x01,
  0x95, 0x02,
  0x81, 0x03,        //   Input (Constant)
  // ─ HAT スイッチ (D-Pad) ─
  0x05, 0x01,        //   Usage Page (Generic Desktop)
  0x09, 0x39,        //   Usage (Hat switch)
  0x15, 0x00,        //   Logical Min (0)
  0x25, 0x07,        //   Logical Max (7)
  0x35, 0x00,        //   Physical Min (0)
  0x46, 0x3B, 0x01,  //   Physical Max (315)
  0x65, 0x14,        //   Unit (Eng Rot: Degree)
  0x75, 0x04,        //   Report Size (4)
  0x95, 0x01,        //   Report Count (1)
  0x81, 0x42,        //   Input (Data, Variable, Absolute, Null State)
  // ─ 4 ビットパディング ─
  0x65, 0x00,
  0x75, 0x04,
  0x95, 0x01,
  0x81, 0x03,
  // ─ アナログスティック (Lx Ly Rx Ry) 各 1 byte ─
  0x09, 0x30,        //   Usage (X)
  0x09, 0x31,        //   Usage (Y)
  0x09, 0x32,        //   Usage (Z)
  0x09, 0x35,        //   Usage (Rz)
  0x15, 0x00,
  0x26, 0xFF, 0x00,
  0x75, 0x08,
  0x95, 0x04,
  0x81, 0x02,
  0xC0               // End Collection
};

// ───────────────────────────────────────────────────────────
// 入力レポート構造体  (8 バイト)
// ───────────────────────────────────────────────────────────
struct SwitchReport {
  uint16_t buttons;  // bit 0=Y  1=B  2=A  3=X  4=L  5=R  6=ZL  7=ZR
                     // bit 8=-  9=+  10=L3 11=R3 12=HOME 13=CAP
  uint8_t  hat;      // 0=U 1=UR 2=R 3=DR 4=D 5=DL 6=L 7=UL 8=Center
  uint8_t  lx, ly;   // 左スティック (中央 = 128)
  uint8_t  rx, ry;   // 右スティック
} __attribute__((packed));

// ボタンビット定数
#define BTN_Y      0x0001
#define BTN_B      0x0002
#define BTN_A      0x0004
#define BTN_X      0x0008
#define BTN_L      0x0010
#define BTN_R      0x0020
#define BTN_ZL     0x0040
#define BTN_ZR     0x0080
#define BTN_MINUS  0x0100
#define BTN_PLUS   0x0200
#define BTN_L3     0x0400
#define BTN_R3     0x0800
#define BTN_HOME   0x1000
#define BTN_CAP    0x2000

#define HAT_UP     0
#define HAT_UR     1
#define HAT_RIGHT  2
#define HAT_DR     3
#define HAT_DOWN   4
#define HAT_DL     5
#define HAT_LEFT   6
#define HAT_UL     7
#define HAT_CTR    8

// ───────────────────────────────────────────────────────────
// グローバル変数
// ───────────────────────────────────────────────────────────
static SwitchReport g_report;
static HIDSubDescriptor g_node(_hidReportDesc, sizeof(_hidReportDesc));
static bool g_stopReq = false;

// コマンドバッファ (USB CDC または Serial1 から)
static String g_cmd = "";

// スマホとの通信は USB CDC Serial (OTG ハブ経由)
// Bluetooth は使用しない
#define CMD_SERIAL Serial

// ───────────────────────────────────────────────────────────
// ヘルパー: HID レポート送信
// ───────────────────────────────────────────────────────────
static void sendReport() {
  HID().SendReport(0, &g_report, sizeof(g_report));
}

static void resetReport() {
  g_report.buttons = 0;
  g_report.hat     = HAT_CTR;
  g_report.lx      = 128;
  g_report.ly      = 128;
  g_report.rx      = 128;
  g_report.ry      = 128;
  sendReport();
}

// ───────────────────────────────────────────────────────────
// ボタン操作プリミティブ
// ───────────────────────────────────────────────────────────
static const int FRAME_MS = 16;   // 約 60fps 換算

static void pressButton(uint16_t btn, int frames = 5) {
  g_report.buttons |= btn;
  for (int i = 0; i < frames && !g_stopReq; i++) {
    sendReport();
    delay(FRAME_MS);
  }
  g_report.buttons &= ~btn;
  sendReport();
  delay(80);  // 離した直後の無入力バッファ
}

static void pressHat(uint8_t hat, int frames = 5) {
  g_report.hat = hat;
  for (int i = 0; i < frames && !g_stopReq; i++) {
    sendReport();
    delay(FRAME_MS);
  }
  g_report.hat = HAT_CTR;
  sendReport();
  delay(80);
}

static void mashButton(uint16_t btn, int count) {
  for (int i = 0; i < count && !g_stopReq; i++) {
    pressButton(btn, 3);
    delay(50);
  }
}

static void waitFrames(int n) {
  for (int i = 0; i < n && !g_stopReq; i++) {
    sendReport();
    delay(FRAME_MS);
  }
}

// ───────────────────────────────────────────────────────────
// MHXX 専用シーケンス
// ───────────────────────────────────────────────────────────
/**
 * SEQ:APPRAISE
 * 前提: 鑑定 NPC との会話開始直前、またはメニュー選択後の確認画面にいる。
 *
 * フロー (MHXX お守り鑑定時の一般的な操作):
 *   1. A → 鑑定種別確定
 *   2. 待機 (鑑定アニメーション)
 *   3. A → 結果画面へ (スマホがここでキャプチャ・OCR を行う)
 */
static void seqAppraise() {
  // 鑑定確定
  pressButton(BTN_A, 5);
  delay(400);
  // 鑑定アニメーション待ち (お守り種別やハード速度で変わる)
  delay(2500);
  // 結果確認ボタン
  pressButton(BTN_A, 5);
  delay(600);
  CMD_SERIAL.println("DONE:APPRAISE");
}

/**
 * SEQ:BACK
 * 前提: 鑑定結果が表示されている画面。お守りを受け取らずキャンセルする。
 *
 * フロー:
 *   1. B → 受け取り確認をキャンセル
 *   2. B → 鑑定選択画面へ戻る
 *   3. B → NPC 会話メニューへ戻る (再鑑定のため)
 */
static void seqBack() {
  pressButton(BTN_B, 5);
  delay(400);
  pressButton(BTN_B, 5);
  delay(400);
  pressButton(BTN_B, 5);
  delay(600);
  CMD_SERIAL.println("DONE:BACK");
}

// ───────────────────────────────────────────────────────────
// コマンドパーサー
// ───────────────────────────────────────────────────────────
static void processCommand(const String& cmd) {
  g_stopReq = false;   // 新コマンド開始で中断フラグをリセット

  if (cmd == "READY") {
    CMD_SERIAL.println("OK");

  } else if (cmd == "PRESS:A")     { pressButton(BTN_A);     CMD_SERIAL.println("OK"); }
  else if (cmd == "PRESS:B")       { pressButton(BTN_B);     CMD_SERIAL.println("OK"); }
  else if (cmd == "PRESS:X")       { pressButton(BTN_X);     CMD_SERIAL.println("OK"); }
  else if (cmd == "PRESS:Y")       { pressButton(BTN_Y);     CMD_SERIAL.println("OK"); }
  else if (cmd == "PRESS:L")       { pressButton(BTN_L);     CMD_SERIAL.println("OK"); }
  else if (cmd == "PRESS:R")       { pressButton(BTN_R);     CMD_SERIAL.println("OK"); }
  else if (cmd == "PRESS:ZL")      { pressButton(BTN_ZL);    CMD_SERIAL.println("OK"); }
  else if (cmd == "PRESS:ZR")      { pressButton(BTN_ZR);    CMD_SERIAL.println("OK"); }
  else if (cmd == "PRESS:PLUS")    { pressButton(BTN_PLUS);  CMD_SERIAL.println("OK"); }
  else if (cmd == "PRESS:MINUS")   { pressButton(BTN_MINUS); CMD_SERIAL.println("OK"); }
  else if (cmd == "PRESS:HOME")    { pressButton(BTN_HOME);  CMD_SERIAL.println("OK"); }
  else if (cmd == "PRESS:UP")      { pressHat(HAT_UP);       CMD_SERIAL.println("OK"); }
  else if (cmd == "PRESS:DOWN")    { pressHat(HAT_DOWN);     CMD_SERIAL.println("OK"); }
  else if (cmd == "PRESS:LEFT")    { pressHat(HAT_LEFT);     CMD_SERIAL.println("OK"); }
  else if (cmd == "PRESS:RIGHT")   { pressHat(HAT_RIGHT);    CMD_SERIAL.println("OK"); }

  else if (cmd.startsWith("HOLD:A:")) {
    int frames = cmd.substring(7).toInt();
    pressButton(BTN_A, max(1, frames));
    CMD_SERIAL.println("OK");

  } else if (cmd.startsWith("MASH:A:")) {
    int count = cmd.substring(7).toInt();
    mashButton(BTN_A, max(1, count));
    CMD_SERIAL.println("OK");

  } else if (cmd.startsWith("WAIT:")) {
    int frames = cmd.substring(5).toInt();
    waitFrames(max(1, frames));
    CMD_SERIAL.println("OK");

  } else if (cmd == "SEQ:APPRAISE") {
    seqAppraise();

  } else if (cmd == "SEQ:BACK") {
    seqBack();

  } else if (cmd == "STOP") {
    g_stopReq = true;
    CMD_SERIAL.println("OK");

  } else {
    CMD_SERIAL.print("ERR:UNKNOWN:");
    CMD_SERIAL.println(cmd);
  }
}

// ───────────────────────────────────────────────────────────
// Arduino エントリーポイント
// ───────────────────────────────────────────────────────────
void setup() {
  HID().AppendDescriptor(&g_node);
  resetReport();
  delay(500);

  // USB CDC 安定待ち (OTG 接続後にホストが列挙するまで少し待つ)
  CMD_SERIAL.begin(115200);
  while (!CMD_SERIAL) { delay(10); }

  resetReport();
  CMD_SERIAL.println("MHXX_CTRL_READY");
}

void loop() {
  // シリアル受信バッファ処理
  Stream& src = CMD_SERIAL;
  while (src.available()) {
    char c = (char)src.read();
    if (c == '\r') continue;
    if (c == '\n') {
      g_cmd.trim();
      if (g_cmd.length() > 0) {
        processCommand(g_cmd);
      }
      g_cmd = "";
    } else {
      g_cmd += c;
    }
  }
}
