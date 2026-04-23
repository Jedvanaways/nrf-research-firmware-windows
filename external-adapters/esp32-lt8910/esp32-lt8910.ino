/*
 * ESP32 + LT8910/LT8920 packet forwarder
 *
 * Captures raw nRF24-incompatible LT8910 packets and POSTs them to the
 * nrf24-console web app at http://<APP_HOST>:<APP_PORT>/api/external/packet.
 *
 * Hardware:
 *   - ESP32 WROOM-32 (or any ESP32 variant)
 *   - LT8910 / LT8920 module on SPI
 *
 *   LT8910 pin       ESP32 pin (change in CONFIG if you wire differently)
 *   ---------------  ----------------------
 *   VCC              3.3V
 *   GND              GND
 *   SCK              GPIO 18
 *   MOSI             GPIO 23
 *   MISO             GPIO 19
 *   SS / CS          GPIO  5
 *   PKT / IRQ        GPIO  4  (optional, enables IRQ-based packet detection)
 *
 * Arduino libraries required:
 *   - WiFi (built-in)
 *   - HTTPClient (built-in)
 *   - ArduinoJson  (install via Library Manager)
 *   - A LT8910 / LT8900 SPI driver — the community ones on GitHub vary in quality.
 *     Suggested starting points:
 *       https://github.com/Kiwisincebirth/Arduino-LT8900
 *       https://github.com/JimQode/LT8900    (both need light porting for ESP32)
 *
 * This file is a SKELETON — you'll need to plug in the real LT8910 library
 * calls where marked `// TODO:`. See the companion README for protocol notes
 * and sync-word discovery tactics.
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <SPI.h>

// ------------------------------- CONFIG ---------------------------------

// WiFi
static const char* WIFI_SSID     = "your-ssid";
static const char* WIFI_PASSWORD = "your-password";

// nrf24-console endpoint on your PC / Pi
static const char* APP_HOST = "192.168.1.100";   // the machine running app/app.py
static const uint16_t APP_PORT = 8787;

// LT8910 SPI pins (change to match your wiring)
static const int PIN_SS   = 5;
static const int PIN_SCK  = 18;
static const int PIN_MOSI = 23;
static const int PIN_MISO = 19;
static const int PIN_PKT  = 4;   // LT8910 PKT flag (packet received interrupt); -1 to disable

// LT8910 radio config — TUNE THESE FOR YOUR TARGET DEVICE
// Sync word is the critical bit: it must match the access code the
// target device uses, or the LT8910 will just ignore packets. Common
// defaults are 0x7262 for preamble + your device's sync. See README.
static const uint32_t LT_SYNC_WORD_H = 0x00000000;
static const uint32_t LT_SYNC_WORD_L = 0x7262D547;   // example; edit to match your device
static const uint8_t  LT_CHANNEL     = 42;           // target channel (0-79, ~2402+ MHz)
static const bool     LT_RATE_1M     = true;         // false = 250 kbps

// How long to wait between scan channels if you don't know the channel yet
static const uint16_t SCAN_DWELL_MS = 200;
static const bool     SCAN_ENABLED  = false;    // set true to channel-hop

// How many packets we'll buffer before flushing over HTTP
static const size_t MAX_BATCH = 8;

// ------------------------------------------------------------------------

struct CapturedPacket {
    uint32_t t_ms;
    uint8_t  ch;
    uint8_t  length;
    int8_t   rssi;
    uint8_t  payload[32];
};

static CapturedPacket g_batch[MAX_BATCH];
static size_t         g_batch_count = 0;


static void connectWifi() {
    Serial.printf("WiFi: connecting to %s...\n", WIFI_SSID);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print('.');
    }
    Serial.printf("\nWiFi ok, IP=%s\n", WiFi.localIP().toString().c_str());
}


static void lt8910_init() {
    // TODO: initialise the LT8910 via your chosen library.
    // Typical sequence:
    //   lt.begin(PIN_SS, PIN_PKT);
    //   lt.setDataRate(LT_RATE_1M ? 1 : 0);
    //   lt.setChannel(LT_CHANNEL);
    //   lt.setSyncWord(LT_SYNC_WORD_H, LT_SYNC_WORD_L);
    //   lt.setReceiveMode();
    Serial.println("LT8910: TODO — integrate your LT8910 library here");
}


static bool lt8910_read_packet(CapturedPacket& out) {
    // TODO: poll (or IRQ-trigger) the LT8910 and return true on a new packet.
    //   if (lt.available()) {
    //       out.length = lt.readPacket(out.payload, sizeof(out.payload));
    //       out.rssi   = lt.readRssi();
    //       out.ch     = LT_CHANNEL;
    //       out.t_ms   = millis();
    //       return true;
    //   }
    return false;
}


static void hexify(const uint8_t* buf, size_t len, char* out) {
    static const char* HEX = "0123456789ABCDEF";
    size_t j = 0;
    for (size_t i = 0; i < len; i++) {
        if (i > 0) out[j++] = ':';
        out[j++] = HEX[(buf[i] >> 4) & 0xF];
        out[j++] = HEX[ buf[i]       & 0xF];
    }
    out[j] = 0;
}


static void flushBatch() {
    if (g_batch_count == 0) return;
    if (WiFi.status() != WL_CONNECTED) {
        g_batch_count = 0;
        return;
    }

    String url = String("http://") + APP_HOST + ":" + APP_PORT + "/api/external/packets";
    HTTPClient http;
    http.begin(url);
    http.addHeader("Content-Type", "application/json");

    StaticJsonDocument<1024> doc;
    JsonArray arr = doc.to<JsonArray>();
    for (size_t i = 0; i < g_batch_count; i++) {
        JsonObject o = arr.createNestedObject();
        o["source"]  = "esp32-lt8910";
        o["ch"]      = g_batch[i].ch;
        o["length"]  = g_batch[i].length;
        o["rssi"]    = g_batch[i].rssi;
        char hex[32 * 3 + 1];
        hexify(g_batch[i].payload, g_batch[i].length, hex);
        o["payload"] = hex;
    }

    String body;
    serializeJson(doc, body);
    int status = http.POST(body);
    Serial.printf("POST /api/external/packets (%d pkts) -> %d\n",
                  (int)g_batch_count, status);
    http.end();
    g_batch_count = 0;
}


void setup() {
    Serial.begin(115200);
    delay(200);
    Serial.println("\n== ESP32 + LT8910 packet forwarder ==");

    SPI.begin(PIN_SCK, PIN_MISO, PIN_MOSI, PIN_SS);
    pinMode(PIN_SS, OUTPUT);
    digitalWrite(PIN_SS, HIGH);
    if (PIN_PKT >= 0) pinMode(PIN_PKT, INPUT);

    connectWifi();
    lt8910_init();
}


void loop() {
    // Drain any waiting packets.
    CapturedPacket p;
    while (g_batch_count < MAX_BATCH && lt8910_read_packet(p)) {
        g_batch[g_batch_count++] = p;
    }

    // Flush when we have packets and either the batch is full or ~200 ms
    // have elapsed since the last flush.
    static uint32_t last_flush = 0;
    if (g_batch_count >= MAX_BATCH ||
        (g_batch_count > 0 && millis() - last_flush > 200)) {
        flushBatch();
        last_flush = millis();
    }

    // Optional channel hopping
    if (SCAN_ENABLED) {
        static uint32_t last_hop = 0;
        if (millis() - last_hop > SCAN_DWELL_MS) {
            // TODO: lt.setChannel((currentChannel + 1) % 80);
            last_hop = millis();
        }
    }
}
