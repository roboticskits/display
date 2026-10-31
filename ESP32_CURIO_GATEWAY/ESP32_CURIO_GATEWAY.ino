/* =============================================================================
 * ESP32_CURIO_GATEWAY.ino
 * CURIO MAKER LABS  —  ESP32-S3-WROOM-1-N16R8
 *
 * Supersedes ESP32_PLAY_UPLOAD_FINAL.ino. Does everything that one did, plus
 * Wi-Fi and live Wi-Fi / Bluetooth status & scan RPCs for the DWIN Settings
 * pages, so the STM32 can reach the internet and manage connectivity with NO
 * computer attached.
 *
 * TWO JOBS
 * --------
 *   1. BLE <-> UART bridge  — the phone uploads code to the STM32 (unchanged
 *                             behaviour, plus the IOTR:/LIVE: passthrough fix
 *                             and live BLE connection status reporting)
 *   2. Wi-Fi IoT gateway    — answers the STM32's IOT: requests itself, plus
 *                             wifi_scan, wifi_connect, wifi_disconnect,
 *                             wifi_status, ble_status, and status.
 *
 * WIRING (schematic p2, jumpers J4/J5 MUST be fitted)
 * ---------------------------------------------------
 *   ESP32 IO17 (TX1) --J4--> STM32 PC7 (USART6 RX)
 *   ESP32 IO18 (RX1) <--J5-- STM32 PC6 (USART6 TX)
 *   921600 8N1, matching UART(6) in the STM32's main.py
 *   ESP32 TXD0/RXD0 (J2 CON3) -> 115200 8N1 debug & TTL test port
 *
 * PROTOCOL (identical to the browser gateway — see IOT_EXTENSION_PLAN.md §3)
 * -------------------------------------------------------------------------
 *   STM32 -> here   IOT:{"id":7,"op":"http","method":"GET","url":"..."}\n
 *                   (optional: "body", "ctype", "headers":{...}, "timeout":ms)
 *   STM32 -> here   IOT:{"id":8,"op":"wifi_scan"}\n
 *   STM32 -> here   IOT:{"id":9,"op":"wifi_connect","ssid":"...","pass":"..."}\n
 *   STM32 -> here   IOT:{"id":10,"op":"wifi_status"}\n
 *   STM32 -> here   IOT:{"id":11,"op":"ble_status"}\n
 *   STM32 -> here   IOT:{"id":12,"op":"status"}\n
 *   here  -> STM32  IOTR:{"id":7,"code":200,"body":"...","err":""}\n
 *   here  -> STM32  NET:up | NET:down     (who should answer requests)
 *   here  -> STM32  STAT:{"wifi_up":...,"ssid":"...","ip":"...","rssi":...,
 *                         "ble_up":true,"ble_connected":...,"ble_name":"..."}\n
 *
 * CORES
 * -----
 *   Core 1  loop()    BLE + UART bridge. Must never block.
 *   Core 0  netTask   Wi-Fi scan/connect & HTTPClient (blocks for seconds),
 *                     replies over UART.
 *
 * REQUIRES
 * --------
 *   ArduinoJson v7   (Library Manager). v6 will not compile — v7 replaced
 *                    StaticJsonDocument/DynamicJsonDocument with JsonDocument.
 * ========================================================================== */

#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <Preferences.h>
#include <ArduinoJson.h>

#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

/* ================= CONFIG ================= */
#define MAX_DATA        51200      // BLE upload buffer (code can be large)
#define UART_RX         18         // ESP32 RX1  <- STM32 PC6 TX
#define UART_TX         17         // ESP32 TX1  -> STM32 PC7 RX
#define UART_BAUD       921600

#define MAX_BODY        2048       // STM32 heap cannot hold more than this
#define HTTP_TIMEOUT_MS 8000       // STM32 waits 12 s, so we always lose first
#define WIFI_JOIN_MS    15000
#define TS_MIN_WRITE_MS 15000      // ThingSpeak free-tier rate limit
#define STM_LINE_MAX    4096
#define BLE_NOTIFY_MAX  180        // conservative vs the negotiated MTU
#define BLE_DEV_NAME    "ESP32-BLE-CURIO_V2"

#define SERVICE_UUID "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
#define RX_UUID      "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
#define TX_UUID      "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

/* ================= TYPES =================
 * Must be declared before ANY function that mentions it. The Arduino builder
 * auto-generates prototypes and injects them just below the #includes — if
 * this struct lived further down, those prototypes would reference a type
 * that does not exist yet and the build fails with
 * "'HttpResult' does not name a type".
 */
struct HttpResult {
  int    code = 0;
  String body;
  String err;
};

/* ================= GLOBALS ================= */
HardwareSerial STM(1);
Preferences    prefs;

// Allocated from PSRAM in setup(), NOT static arrays. As statics these two
// ate 100 KB of DRAM — over half the global footprint — starving the mbedTLS
// handshake, which needs ~40 KB of contiguous heap. The N16R8 has 8 MB of
// PSRAM doing nothing, so put them there and give TLS the DRAM back.
uint8_t* bleRxBuffer = nullptr;
uint8_t* bleBuffer   = nullptr;
size_t   bleRxIndex = 0;
size_t   bleLen     = 0;
volatile bool bleReady        = false;
volatile bool deviceConnected = false;
volatile bool bleAdvertising  = false;
volatile bool statusDirty     = true;

// Latches while a multi-write control line (IOTR:/LIVE:) is still arriving.
volatile bool ctrlPassThrough = false;

BLECharacteristic* pTxCharacteristic = nullptr;

// Bluetooth settings changed from the DWIN display (STM32 ops ble_adv,
// ble_disconnect, ble_name). The name always starts with BLE_DEV_NAME so apps
// that look for "ESP32-BLE-CURIO..." still find the board; an optional label
// (A-Z, 0-9, '-', max 8) is added: "ESP32-BLE-CURIO_V2-CLASS5".
BLEServer* pBleServer   = nullptr;
String   bleName        = BLE_DEV_NAME;
String   bleLabel       = "";
bool     bleVisible     = true;     // advertise when no device is connected
uint32_t restartAt      = 0;        // ESP.restart() after a rename (0 = none)

QueueHandle_t     netQueue;   // carries String* to netTask
SemaphoreHandle_t uartMux;    // one writer on the UART at a time

String stmLine;               // UART1 (STM32) line assembler
String usbLine;               // UART0 (TTL debug/test) line assembler

int    lastScanCount = -1;    // number of networks from most recent scan
String topScanSsid   = "";    // strongest SSID from most recent scan
bool   wifiEnabled   = true;  // saved in NVS; OFF also turns off the Wi-Fi radio

// ThingSpeak session, mirrored from the STM32's ts_connect block
String   tsId, tsWriteKey, tsReadKey;
uint32_t lastTsWrite = 0;

// Where the ThingSpeak blocks actually point. The `set cloud server` block
// swaps this for a self-hosted Curio Cloud instance.
const char* TS_DEFAULT = "https://api.thingspeak.com";
String      tsBase     = TS_DEFAULT;

/* ================= UART OUT ================= */

// Every UART write goes through here so a reply can never interleave with a
// BLE-forwarded upload chunk.
void stmWrite(const String& s) {
  xSemaphoreTake(uartMux, portMAX_DELAY);
  STM.print(s);
  xSemaphoreGive(uartMux);
}

void stmWriteRaw(const uint8_t* buf, size_t len) {
  xSemaphoreTake(uartMux, portMAX_DELAY);
  STM.write(buf, len);
  STM.println();
  xSemaphoreGive(uartMux);
}

/* ================= BLE OUT ================= */

void bleNotify(const String& line) {
  if (!deviceConnected || !pTxCharacteristic) return;
  String s = line + "\n";                 // browser splits on newline
  for (size_t i = 0; i < s.length(); i += BLE_NOTIFY_MAX) {
    pTxCharacteristic->setValue(s.substring(i, i + BLE_NOTIFY_MAX).c_str());
    pTxCharacteristic->notify();
    delay(3);                             // let the BLE stack drain
  }
}

/* ================= Wi-Fi & Status ================= */

bool wifiReady() { return WiFi.status() == WL_CONNECTED; }

String buildStatusJson() {
  JsonDocument doc;
  bool wUp = wifiReady();
  doc["wifi_enabled"]  = wifiEnabled;
  doc["wifi_up"]       = wUp;
  doc["ssid"]          = wUp ? WiFi.SSID() : "";
  doc["ip"]            = wUp ? WiFi.localIP().toString() : "";
  doc["rssi"]          = wUp ? (int)WiFi.RSSI() : 0;
  doc["scan_count"]    = lastScanCount;
  doc["top_ssid"]      = topScanSsid;
  doc["ble_up"]        = true;
  doc["ble_connected"] = (bool)deviceConnected;
  doc["ble_adv"]       = (bool)bleAdvertising;
  doc["ble_visible"]   = bleVisible;
  doc["ble_name"]      = bleName;

  String json;
  serializeJson(doc, json);
  return json;
}

// Tell the STM32 who should answer IoT requests and report full Wi-Fi + BLE
// status for the DWIN Settings pages.
void announceNet(bool force = false) {
  static int  lastNet = -1;
  static int  lastBle = -1;
  static String lastSsid = "";

  int nowNet = wifiReady() ? 1 : 0;
  int nowBle = deviceConnected ? 1 : 0;
  String nowSsid = nowNet ? WiFi.SSID() : "";

  if (!force && !statusDirty && nowNet == lastNet && nowBle == lastBle && nowSsid == lastSsid) {
    return;
  }
  statusDirty = false;
  lastNet  = nowNet;
  lastBle  = nowBle;
  lastSsid = nowSsid;

  stmWrite(nowNet ? "NET:up\n" : "NET:down\n");
  Serial.printf("NET:%s\n", nowNet ? "up" : "down");

  String statJson = buildStatusJson();
  String statLine = "STAT:" + statJson + "\n";
  stmWrite(statLine);
  Serial.print(statLine);
}

bool wifiJoin(const String& ssid, const String& pass, bool forceReconnect = false) {
  if (!wifiEnabled || ssid.length() == 0) return false;

  // Already on this network? Do nothing unless forced.
  if (!forceReconnect && wifiReady() && WiFi.SSID() == ssid) {
    Serial.printf("Wi-Fi already on '%s' - keeping it\n", ssid.c_str());
    return true;
  }

  Serial.printf("Wi-Fi joining '%s'...\n", ssid.c_str());
  WiFi.mode(WIFI_STA);
  if (wifiReady() || forceReconnect) {
    WiFi.disconnect(false, false);
    delay(100);
  }
  WiFi.begin(ssid.c_str(), pass.c_str());

  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < WIFI_JOIN_MS) {
    delay(200);
  }
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Wi-Fi join FAILED");
    statusDirty = true;
    return false;
  }

  Serial.print("Wi-Fi up, IP ");
  Serial.println(WiFi.localIP());

  prefs.begin("curio", false);            // survive a power cycle
  prefs.putString("ssid", ssid);
  prefs.putString("pass", pass);
  prefs.end();
  statusDirty = true;
  return true;
}

void wifiTryStored() {
  if (!wifiEnabled) return;
  prefs.begin("curio", true);
  String ssid = prefs.getString("ssid", "");
  String pass = prefs.getString("pass", "");
  prefs.end();
  if (ssid.length()) wifiJoin(ssid, pass);
}

HttpResult doWifiScan() {
  HttpResult r;
  if (!wifiEnabled) { r.err = "wifi-off"; return r; }
  WiFi.mode(WIFI_STA);
  int n = WiFi.scanNetworks(false, false);
  JsonDocument doc;
  JsonArray arr = doc.to<JsonArray>();

  topScanSsid = "";
  int bestRssi = -999;
  int added = 0;

  if (n > 0) {
    for (int i = 0; i < n && added < 12; ++i) {
      String s = WiFi.SSID(i);
      if (s.length() == 0) continue;
      int rssi = (int)WiFi.RSSI(i);
      if (rssi > bestRssi) {
        bestRssi = rssi;
        topScanSsid = s;
      }
      // Deduplicate SSIDs (scan returns multiple BSSIDs for mesh/enterprise)
      bool seen = false;
      for (JsonVariant v : arr) {
        if (v["ssid"].as<String>() == s) {
          seen = true;
          break;
        }
      }
      if (seen) continue;

      JsonObject item = arr.add<JsonObject>();
      item["ssid"] = s;
      item["rssi"] = rssi;
      item["open"] = (WiFi.encryptionType(i) == WIFI_AUTH_OPEN);
      added++;
    }
  }
  lastScanCount = added;
  WiFi.scanDelete();
  statusDirty = true;

  r.code = 200;
  serializeJson(arr, r.body);
  return r;
}

/* ================= HTTP ================= */

// headers: extra request headers, e.g. {"Authorization": "Bearer ..."} for an
// LLM API; timeoutMs: read timeout (an LLM answer can take 10-30 s).
HttpResult doHttpEx(const String& method, const String& url,
                    const String& body, const String& ctype,
                    JsonObjectConst headers, uint32_t timeoutMs) {
  HttpResult r;
  if (!wifiReady())      { r.err = "offline"; return r; }
  if (url.length() == 0) { r.err = "no-url"; return r; }

  WiFiClientSecure* secure = nullptr;
  HTTPClient http;
  bool opened;

  if (url.startsWith("https://")) {
    secure = new WiFiClientSecure();
    // TODO(security): swap for secure->setCACertBundle(rootca_crt_bundle_start)
    // to actually validate the server. See the header note.
    secure->setInsecure();
    opened = http.begin(*secure, url);
  } else {
    opened = http.begin(url);
  }

  if (!opened) {
    r.err = "bad-url";
    Serial.printf("HTTP begin() refused: %s\n", url.c_str());
    delete secure;
    return r;
  }
  Serial.printf("HTTP %s %s\n", method.c_str(), url.c_str());

  http.setTimeout((uint16_t)constrain(timeoutMs, 1000UL, 45000UL));
  http.setConnectTimeout(HTTP_TIMEOUT_MS);
  if (ctype.length()) http.addHeader("Content-Type", ctype);
  for (JsonPairConst kv : headers) http.addHeader(kv.key().c_str(), kv.value().as<String>());

  int code;
  if (method == "POST")        code = http.POST(body);
  else if (method == "DELETE") code = http.sendRequest("DELETE", (uint8_t*)body.c_str(), body.length());
  else                         code = http.GET();

  if (code > 0) {
    r.code = code;
    r.body = http.getString();
    if (r.body.length() > MAX_BODY) {
      r.body = r.body.substring(0, MAX_BODY);
      r.err  = "truncated";
    }
  } else {
    r.err = String("net:") + http.errorToString(code);
    Serial.printf("HTTP FAILED code=%d (%s)  freeHeap=%u largestBlock=%u\n",
                  code, http.errorToString(code).c_str(),
                  (unsigned)ESP.getFreeHeap(),
                  (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));

    String host = url;
    int q = host.indexOf("://");
    if (q >= 0) host = host.substring(q + 3);
    q = host.indexOf('/');
    if (q >= 0) host = host.substring(0, q);
    q = host.indexOf(':');
    if (q >= 0) host = host.substring(0, q);

    IPAddress resolved;
    bool dnsOk = WiFi.hostByName(host.c_str(), resolved);
    Serial.printf("   DNS %s -> %s | dnsServer=%s ip=%s rssi=%d\n",
                  host.c_str(),
                  dnsOk ? resolved.toString().c_str() : "RESOLVE FAILED",
                  WiFi.dnsIP().toString().c_str(),
                  WiFi.localIP().toString().c_str(),
                  (int)WiFi.RSSI());
  }

  http.end();
  delete secure;
  return r;
}

HttpResult doHttp(const String& method, const String& url,
                  const String& body, const String& ctype) {
  return doHttpEx(method, url, body, ctype, JsonObjectConst(), HTTP_TIMEOUT_MS);
}

/* ================= ThingSpeak ================= */

HttpResult tsWrite(JsonObject fields) {
  HttpResult r;
  if (tsWriteKey.length() == 0) { r.err = "no-channel"; return r; }

  uint32_t since = millis() - lastTsWrite;
  if (tsBase == TS_DEFAULT && lastTsWrite && since < TS_MIN_WRITE_MS) {
    r.err = "rate-limited";
    return r;
  }

  String form = "api_key=" + tsWriteKey;
  for (JsonPair kv : fields) {
    form += "&field";
    form += kv.key().c_str();
    form += "=";
    form += kv.value().as<String>();
  }

  r = doHttp("POST", tsBase + "/update", form,
             "application/x-www-form-urlencoded");

  if (r.code == 200 && r.body == "0") r.err = "rejected";
  else if (r.code == 200)             lastTsWrite = millis();
  return r;
}

HttpResult tsRead() {
  HttpResult r;
  if (tsId.length() == 0) { r.err = "no-channel"; return r; }
  String url = tsBase + "/channels/" + tsId + "/feeds/last.json";
  if (tsReadKey.length()) url += "?api_key=" + tsReadKey;
  return doHttp("GET", url, "", "");
}

/* ================= REQUEST HANDLING (core 0) ================= */

void sendReply(uint32_t id, const HttpResult& r) {
  JsonDocument doc;
  doc["id"]   = id;
  doc["code"] = r.code;
  doc["body"] = r.body;
  doc["err"]  = r.err;

  // CAREFUL: serializeJson() CLEARS its destination String before writing.
  // Serialize into its own String first, then concatenate.
  String json;
  serializeJson(doc, json);
  String out = "IOTR:" + json + "\n";
  stmWrite(out);
  Serial.print(out);

  Serial.printf("IOTR #%u code=%d err=%s bytes=%u\n",
                (unsigned)id, r.code,
                r.err.length() ? r.err.c_str() : "-", (unsigned)out.length());
}

void handleIotLine(const String& line) {
  JsonDocument req;
  DeserializationError e = deserializeJson(req, line.substring(4));  // skip "IOT:"
  if (e) {
    Serial.printf("IOT parse error: %s\n", e.c_str());
    return;
  }

  uint32_t id = req["id"] | 0;
  String   op = req["op"] | "";
  HttpResult r;

  if (op == "http") {
    r = doHttpEx(req["method"] | "GET", req["url"] | "",
                 req["body"] | "", req["ctype"] | "",
                 req["headers"].as<JsonObjectConst>(), req["timeout"] | (uint32_t)HTTP_TIMEOUT_MS);

  } else if (op == "wifi_check") {
    // With an ssid: actually join (and remember). Without: just report.
    String ssid = req["ssid"] | "";
    if (ssid.length()) wifiJoin(ssid, req["pass"] | "");
    bool up = wifiReady();
    r.code = up ? 200 : 0;
    r.body = up ? "1" : "0";
    r.err  = up ? "" : "offline";
    announceNet(true);

  } else if (op == "wifi_scan") {
    r = doWifiScan();
    announceNet(true);

  } else if (op == "wifi_connect") {
    String ssid = req["ssid"] | "";
    String pass = req["pass"] | "";
    bool force  = req["force"] | false;
    if (ssid.length() == 0) {
      r.code = 0;
      r.err  = "no-ssid";
    } else {
      bool ok = wifiJoin(ssid, pass, force);
      JsonDocument info;
      info["connected"] = ok;
      info["ssid"]      = ok ? WiFi.SSID() : ssid;
      info["ip"]        = ok ? WiFi.localIP().toString() : "";
      info["rssi"]      = ok ? (int)WiFi.RSSI() : 0;
      serializeJson(info, r.body);
      r.code = ok ? 200 : 0;
      r.err  = ok ? "" : "join-failed";
    }
    announceNet(true);

  } else if (op == "wifi_disconnect") {
    bool forget = req["forget"] | false;
    WiFi.disconnect(false, forget);
    if (forget) {
      prefs.begin("curio", false);
      prefs.remove("ssid");
      prefs.remove("pass");
      prefs.end();
    }
    delay(100);
    r.code = 200;
    r.body = "0";
    announceNet(true);

  } else if (op == "wifi_enable") {
    bool on = req["on"] | false;
    prefs.begin("curio", false);
    prefs.putBool("wifi_enabled", on);
    prefs.end();
    wifiEnabled = on;
    if (on) {
      WiFi.mode(WIFI_STA);
      wifiTryStored();
    } else {
      WiFi.disconnect(true, false);
      WiFi.mode(WIFI_OFF);
      lastScanCount = -1;
      topScanSsid = "";
    }
    JsonDocument info;
    info["enabled"] = wifiEnabled;
    info["connected"] = wifiReady();
    serializeJson(info, r.body);
    r.code = 200;
    statusDirty = true;
    announceNet(true);

  } else if (op == "wifi_status") {
    prefs.begin("curio", true);
    String savedSsid = prefs.getString("ssid", "");
    prefs.end();

    bool up = wifiReady();
    JsonDocument info;
    info["connected"]  = up;
    info["enabled"]    = wifiEnabled;
    info["ssid"]       = up ? WiFi.SSID() : "";
    info["saved_ssid"] = savedSsid;
    info["ip"]         = up ? WiFi.localIP().toString() : "";
    info["rssi"]       = up ? (int)WiFi.RSSI() : 0;
    info["mac"]        = WiFi.macAddress();
    info["scan_count"] = lastScanCount;
    info["top_ssid"]   = topScanSsid;
    serializeJson(info, r.body);
    r.code = 200;
    announceNet(true);

  } else if (op == "ble_status") {
    JsonDocument info;
    info["available"]   = true;
    info["connected"]   = (bool)deviceConnected;
    info["advertising"] = (bool)bleAdvertising;
    info["visible"]     = bleVisible;
    info["name"]        = bleName;
    serializeJson(info, r.body);
    r.code = 200;
    announceNet(true);

  } else if (op == "ble_adv") {                    // {"on": true|false}: visible to phones or hidden
    bleVisible = req["on"] | true;
    prefs.begin("curio", false);
    prefs.putBool("ble_vis", bleVisible);
    prefs.end();
    if (!deviceConnected) {
      if (bleVisible) BLEDevice::startAdvertising();
      else            BLEDevice::stopAdvertising();
      bleAdvertising = bleVisible;
    }
    statusDirty = true;
    r.code = 200;
    r.body = bleVisible ? "1" : "0";
    announceNet(true);

  } else if (op == "ble_disconnect") {             // drop the phone / app connected now
    if (deviceConnected && pBleServer) pBleServer->disconnect(pBleServer->getConnId());
    r.code = 200;
    r.body = deviceConnected ? "1" : "0";
    announceNet(true);

  } else if (op == "ble_name") {                   // {"label": "CLASS5"}: new name after a restart
    String in = req["label"] | "";
    String label = "";
    for (size_t i = 0; i < in.length() && label.length() < 8; ++i) {
      char c = toupper(in[i]);
      if ((c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '-') label += c;
    }
    prefs.begin("curio", false);
    prefs.putString("ble_label", label);
    prefs.end();
    bleLabel = label;
    bleName  = label.length() ? String(BLE_DEV_NAME) + "-" + label : String(BLE_DEV_NAME);
    r.code = 200;
    r.body = bleName;                              // the Bluetooth stack needs a restart for it
    restartAt = millis() + 1500;
    announceNet(true);

  } else if (op == "status") {
    r.code = 200;
    r.body = buildStatusJson();
    announceNet(true);

  } else if (op == "ts_server") {
    String u = req["url"] | "";
    u.trim();
    while (u.endsWith("/")) u.remove(u.length() - 1);   // avoid '//update'
    tsBase = u.length() ? u : String(TS_DEFAULT);
    Serial.printf("cloud server -> %s\n", tsBase.c_str());
    r.code = 200;
    r.body = tsBase;

  } else if (op == "ts_auto") {
    String u = req["url"] | "";
    u.trim();
    while (u.endsWith("/")) u.remove(u.length() - 1);
    if (u.length()) tsBase = u;

    if (tsBase == TS_DEFAULT) {
      r.err = "auto-connect needs our own cloud, not ThingSpeak";
    } else {
      String form = "device=" + String(req["device"] | "");
      HttpResult pr = doHttp("POST", tsBase + "/provision", form,
                             "application/x-www-form-urlencoded");
      if (pr.code != 200) {
        r = pr;
      } else {
        JsonDocument info;
        if (deserializeJson(info, pr.body)) {
          r.err = "bad provision reply";
        } else {
          tsId       = String((int)(info["channel_id"] | 0));
          tsWriteKey = String((const char*)(info["write_key"] | ""));
          tsReadKey  = String((const char*)(info["read_key"]  | ""));
          lastTsWrite = 0;
          r.code = 200;
          r.body = String((const char*)(info["code"] | ""));
          Serial.printf("auto-connected as %s -> channel %s\n",
                        r.body.c_str(), tsId.c_str());
        }
      }
    }

  } else if (op == "ts_connect") {
    tsId       = req["id_ch"] | "";
    tsWriteKey = req["wkey"]  | "";
    tsReadKey  = req["rkey"]  | "";
    lastTsWrite = 0;
    r.code = 200;
    r.body = "1";

  } else if (op == "ts_write") {
    JsonObject f = req["fields"].as<JsonObject>();
    r = tsWrite(f);

  } else if (op == "ts_read") {
    r = tsRead();

  } else {
    r.err = "bad-op:" + op;
  }

  sendReply(id, r);
}

void netTask(void*) {
  for (;;) {
    String* p = nullptr;
    if (xQueueReceive(netQueue, &p, portMAX_DELAY) == pdTRUE && p) {
      handleIotLine(*p);
      delete p;
    }
  }
}

/* ================= UART IN (core 1) ================= */

bool isLocalGatewayOp(const String& line) {
  return line.indexOf("\"wifi_check\"") >= 0 ||
         line.indexOf("\"wifi_scan\"") >= 0 ||
         line.indexOf("\"wifi_connect\"") >= 0 ||
         line.indexOf("\"wifi_disconnect\"") >= 0 ||
         line.indexOf("\"wifi_enable\"") >= 0 ||
         line.indexOf("\"wifi_status\"") >= 0 ||
         line.indexOf("\"ble_status\"") >= 0 ||
         line.indexOf("\"ble_adv\"") >= 0 ||
         line.indexOf("\"ble_disconnect\"") >= 0 ||
         line.indexOf("\"ble_name\"") >= 0 ||
         line.indexOf("\"status\"") >= 0;
}

void routeStmLine(const String& line) {
  if (line.length() == 0) return;

  // Local Wi-Fi / BLE management ops MUST be handled by the ESP32 even while
  // Wi-Fi is down — that is how we scan, join, and check status.
  bool localOp = isLocalGatewayOp(line);

  if (line.startsWith("IOT:") && (wifiReady() || localOp)) {
    // We can serve this ourselves. Consume it — do NOT also forward to BLE,
    // or the phone would answer the same id a second time.
    String* p = new String(line);
    if (xQueueSend(netQueue, &p, 0) != pdTRUE) {
      delete p;
      Serial.println("netQueue full — request dropped");
    }
    return;
  }

  // Board print() output, and IOT: requests we cannot serve (Wi-Fi down) —
  // pass them up to the phone, which may be able to.
  bleNotify(line);
}

void pumpUart() {
  while (STM.available()) {
    char c = (char)STM.read();
    if (c == '\n') {
      routeStmLine(stmLine);
      stmLine = "";
    } else if (c != '\r') {
      if (stmLine.length() < STM_LINE_MAX) stmLine += c;
      else stmLine = "";           // runaway line — drop it rather than leak
    }
  }

  // Also accept IOT: test/control commands on UART0 (Serial / J2 TTL header)
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') {
      String trimmed = usbLine;
      trimmed.trim();
      usbLine = "";
      if (trimmed.startsWith("IOT:")) {
        String* p = new String(trimmed);
        if (xQueueSend(netQueue, &p, 0) != pdTRUE) {
          delete p;
          Serial.println("netQueue full — request dropped");
        }
      } else if (trimmed == "STATUS" || trimmed == "STATUS?") {
        announceNet(true);
      }
    } else if (c != '\r') {
      if (usbLine.length() < STM_LINE_MAX) usbLine += c;
      else usbLine = "";
    }
  }
}

/* ================= BLE CALLBACKS ================= */

class MyServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer*) {
    deviceConnected = true;
    bleAdvertising  = false;
    statusDirty     = true;
    Serial.println("BLE Client Connected");
  }
  void onDisconnect(BLEServer* pServer) {
    deviceConnected = false;
    if (bleVisible) pServer->startAdvertising();   // hidden: stay invisible
    bleAdvertising  = bleVisible;
    statusDirty     = true;
    Serial.println(bleVisible ? "BLE Client Disconnected - advertising restarted"
                              : "BLE Client Disconnected - hidden, not advertising");
  }
};

class RxCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic* c) {
    String val = c->getValue().c_str();
    size_t len = val.length();
    if (len == 0) return;

    // --- IMMEDIATE COMMAND DISPATCH ---
    if (val == "PLAY" || val == "STOP" || val == "UPLOAD" ||
        val == "PLAY\n" || val == "STOP\n" || val == "UPLOAD\n") {
      Serial.printf("Command Bypass: %s\n", val.c_str());
      stmWrite(val.endsWith("\n") ? val : (val + "\n"));
      return;
    }

    // --- CONTROL LINE PASSTHROUGH ---
    if (ctrlPassThrough || val.startsWith("IOTR:") || val.startsWith("LIVE:")) {
      stmWrite(val);
      ctrlPassThrough = !val.endsWith("\n");
      return;
    }

    // --- BULK DATA (code upload) ---
    if (!bleRxBuffer || !bleBuffer) return;      // allocation failed at boot
    if (bleRxIndex + len > MAX_DATA) {
      Serial.println("BLE overflow - resetting buffer");
      bleRxIndex = 0;
      return;
    }
    memcpy(bleRxBuffer + bleRxIndex, val.c_str(), len);
    bleRxIndex += len;

    if (bleRxIndex >= 5 && memcmp(bleRxBuffer + bleRxIndex - 5, "@@END", 5) == 0) {
      bleLen = bleRxIndex;
      memcpy(bleBuffer, bleRxBuffer, bleLen);
      bleReady   = true;
      bleRxIndex = 0;
      Serial.println("TOTAL DATA RECEIVED & READY FOR STM32");
    }
  }
};

/* ================= SETUP ================= */

void setup() {
  Serial.begin(115200);
  STM.begin(UART_BAUD, SERIAL_8N1, UART_RX, UART_TX);
  STM.setTimeout(50);              // never stall the bridge on a partial line

  // PSRAM first, plain heap as fallback if PSRAM is disabled in board options.
  bleRxBuffer = (uint8_t*)ps_malloc(MAX_DATA);
  bleBuffer   = (uint8_t*)ps_malloc(MAX_DATA);
  if (!bleRxBuffer) bleRxBuffer = (uint8_t*)malloc(MAX_DATA);
  if (!bleBuffer)   bleBuffer   = (uint8_t*)malloc(MAX_DATA);
  Serial.printf("BLE buffers: %s  psram=%u  freeHeap=%u\n",
                (bleRxBuffer && bleBuffer) ? "ok" : "ALLOC FAILED",
                (unsigned)ESP.getFreePsram(), (unsigned)ESP.getFreeHeap());

  uartMux  = xSemaphoreCreateMutex();
  netQueue = xQueueCreate(4, sizeof(String*));

  // Network work runs on core 0 so HTTPClient's multi-second blocking never
  // stalls the BLE/UART bridge on core 1.
  xTaskCreatePinnedToCore(netTask, "netTask", 16384, nullptr, 1, nullptr, 0);

  prefs.begin("curio", true);                      // Bluetooth name label + visibility from the display
  bleLabel   = prefs.getString("ble_label", "");
  bleVisible = prefs.getBool("ble_vis", true);
  prefs.end();
  bleName = bleLabel.length() ? String(BLE_DEV_NAME) + "-" + bleLabel : String(BLE_DEV_NAME);

  BLEDevice::init(bleName.c_str());
  BLEDevice::setMTU(512);

  BLEServer* pServer = BLEDevice::createServer();
  pBleServer = pServer;
  pServer->setCallbacks(new MyServerCallbacks());

  BLEService* pService = pServer->createService(SERVICE_UUID);

  pTxCharacteristic = pService->createCharacteristic(
                        TX_UUID, BLECharacteristic::PROPERTY_NOTIFY);
  pTxCharacteristic->addDescriptor(new BLE2902());

  BLECharacteristic* pRx = pService->createCharacteristic(
                             RX_UUID,
                             BLECharacteristic::PROPERTY_WRITE |
                             BLECharacteristic::PROPERTY_WRITE_NR);
  pRx->setCallbacks(new RxCallbacks());

  pService->start();
  BLEAdvertising* pAdv = BLEDevice::getAdvertising();
  pAdv->addServiceUUID(SERVICE_UUID);
  if (bleVisible) pAdv->start();
  bleAdvertising = bleVisible;

  Serial.printf("CURIO gateway up. BLE name %s, %s.\n", bleName.c_str(), bleVisible ? "advertising" : "hidden");

  prefs.begin("curio", true);
  wifiEnabled = prefs.getBool("wifi_enabled", true);
  prefs.end();
  if (wifiEnabled) {
    WiFi.mode(WIFI_STA);
    wifiTryStored();               // reconnect with no computer attached
  } else {
    WiFi.mode(WIFI_OFF);
  }
  announceNet(true);
}

/* ================= LOOP (core 1 — never blocks) ================= */

void loop() {
  pumpUart();

  if (restartAt && (int32_t)(millis() - restartAt) >= 0) {   // new Bluetooth name
    Serial.println("Restarting for the new Bluetooth name");
    delay(50);
    ESP.restart();
  }

  if (bleReady) {
    bleReady = false;
    Serial.printf("Sending to STM32 (%u bytes)...\n", (unsigned)bleLen);
    stmWriteRaw(bleBuffer, bleLen);
  }

  if (statusDirty) {
    announceNet(true);
  }

  // Re-announce periodically: the STM32 may have rebooted and missed it.
  static uint32_t lastAnnounce = 0;
  if (millis() - lastAnnounce > 5000) {
    lastAnnounce = millis();
    announceNet(true);
  }

  delay(2);
}
