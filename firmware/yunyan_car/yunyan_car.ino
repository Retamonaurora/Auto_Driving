/* 云衍小车 ROS 2 学习版：离散 HTTP 控制 + 软件超时停车。
 * 烧录前确认与原车一致的 GPIO 和安全供电；架空车轮首次测试。
 * 这是实验软件保护，不替代人工断电、硬件急停和安全电路。
 *
 * Wi-Fi 凭据不入库：复制 wifi_credentials.h.example 为 wifi_credentials.h 后填写，
 * 该文件已被 .gitignore 排除。
 */
#include <WiFi.h>
#include <WebServer.h>
#include <U8g2lib.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <freertos/task.h>

#include "wifi_credentials.h"

#define INA1 12
#define INA2 13
#define INB1 14
#define INB2 21
// U8g2 构造参数为 SCL、SDA，与用户原始实际代码一致。
U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE, 42, 41);
WebServer server(80);
SemaphoreHandle_t motorMutex = nullptr;
enum Motion { STOPPED, FORWARD, BACK, LEFT, RIGHT };
Motion currentMotion = STOPPED;
uint32_t lastMotionMs = 0;
const uint32_t COMMAND_TIMEOUT_MS = 800;

const char* motionName(Motion m) {
  switch (m) {
    case FORWARD: return "FORWARD";
    case BACK: return "BACK";
    case LEFT: return "LEFT";
    case RIGHT: return "RIGHT";
    default: return "STOP";
  }
}

// 只允许在持有 motorMutex 时调用。每次先停止，再设置新的方向。
void applyMotionLocked(Motion m) {
  digitalWrite(INA1, LOW); digitalWrite(INA2, LOW);
  digitalWrite(INB1, LOW); digitalWrite(INB2, LOW);
  if (m == FORWARD || m == RIGHT) digitalWrite(INA1, HIGH);
  if (m == BACK) digitalWrite(INA2, HIGH);
  if (m == FORWARD || m == LEFT) digitalWrite(INB1, HIGH);
  if (m == BACK) digitalWrite(INB2, HIGH);
  currentMotion = m;
}

void requestMotion(Motion m) {
  if (m != STOPPED && WiFi.status() != WL_CONNECTED) {
    server.send(503, "text/plain", "WIFI_DISCONNECTED");
    return;
  }
  if (xSemaphoreTake(motorMutex, pdMS_TO_TICKS(50)) != pdTRUE) {
    server.send(503, "text/plain", "BUSY");
    return;
  }
  // 每次有效运动请求都刷新车端期限；STOP 不启动电机。
  if (m != STOPPED) lastMotionMs = millis();
  if (currentMotion != m) applyMotionLocked(m);
  xSemaphoreGive(motorMutex);
  server.send(200, "text/plain", "OK");
}

// 单独任务避免仅因 HTTP/OLED 主循环卡住就完全失去超时处理能力。
// MCU 整体卡死、供电故障、网络延迟包、驱动故障等仍需实体保护。
void watchdogTask(void*) {
  for (;;) {
    bool wifiLost = WiFi.status() != WL_CONNECTED;
    if (xSemaphoreTake(motorMutex, pdMS_TO_TICKS(20)) == pdTRUE) {
      if (currentMotion != STOPPED &&
          (wifiLost || (uint32_t)(millis() - lastMotionMs) >= COMMAND_TIMEOUT_MS)) {
        applyMotionLocked(STOPPED);
      }
      xSemaphoreGive(motorMutex);
    }
    vTaskDelay(pdMS_TO_TICKS(20));
  }
}

const char PAGE[] PROGMEM = R"HTML(
<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>云衍小车</title><style>
body{text-align:center;font-family:sans-serif;touch-action:manipulation}
button{width:105px;height:85px;margin:6px;font-size:22px;touch-action:none}
</style></head><body><h2>云衍小车</h2><p>按住移动，松开停止；请勿同时使用其他控制端。</p>
<div><button data-cmd="forward">前进</button></div>
<div><button data-cmd="left">左转</button><button id="stop">停止</button><button data-cmd="right">右转</button></div>
<div><button data-cmd="back">后退</button></div><p id="status">等待操作</p>
<script>
let desired='stop', activePointer=null, running=false;
const status=document.getElementById('status');
async function pump(){
  if(running)return; running=true;
  while(true){
    const sent=desired;
    try { const r=await fetch('/'+sent,{cache:'no-store'}); if(!r.ok)throw Error(r.status); status.textContent='命令: '+sent; }
    catch(e){ status.textContent='通信异常，请立即人工断电检查'; desired='stop'; }
    if(desired==='stop' && sent==='stop')break;
    await new Promise(r=>setTimeout(r,150));
  }
  running=false;
}
function stop(){desired='stop';activePointer=null;pump();}
document.querySelectorAll('[data-cmd]').forEach(b=>{
  b.addEventListener('pointerdown',e=>{e.preventDefault(); if(activePointer!==null)return; activePointer=e.pointerId; desired=b.dataset.cmd; b.setPointerCapture(e.pointerId); pump();});
  b.addEventListener('pointerup',stop); b.addEventListener('pointercancel',stop); b.addEventListener('lostpointercapture',stop);
});
document.getElementById('stop').addEventListener('click',stop);
window.addEventListener('blur',stop);
document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});
document.addEventListener('contextmenu',e=>e.preventDefault());
</script></body></html>
)HTML";

void showStatus() {
  Motion m = STOPPED;
  if (xSemaphoreTake(motorMutex, pdMS_TO_TICKS(20)) == pdTRUE) {
    m = currentMotion;
    xSemaphoreGive(motorMutex);
  }
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_ncenB14_tr);
  u8g2.drawStr(0, 18, motionName(m));
  u8g2.setFont(u8g2_font_6x10_tr);
  if (WiFi.status() == WL_CONNECTED) {
    String ip = "IP:" + WiFi.localIP().toString();
    u8g2.drawStr(0, 36, ip.c_str());
    u8g2.drawStr(0, 52, "WiFi OK");
  } else {
    u8g2.drawStr(0, 36, "WiFi");
    u8g2.drawStr(0, 52, "DISCONNECT");
  }
  u8g2.sendBuffer();
}

void setup() {
  pinMode(INA1, OUTPUT); pinMode(INA2, OUTPUT);
  pinMode(INB1, OUTPUT); pinMode(INB2, OUTPUT);
  digitalWrite(INA1, LOW); digitalWrite(INA2, LOW);
  digitalWrite(INB1, LOW); digitalWrite(INB2, LOW);
  Serial.begin(115200);
  motorMutex = xSemaphoreCreateMutex();
  if (!motorMutex) { Serial.println("Mutex error"); for (;;) delay(1000); }
  if (xTaskCreate(watchdogTask, "car_watchdog", 3072, nullptr, 2, nullptr) != pdPASS) {
    Serial.println("Watchdog task error"); for (;;) delay(1000);
  }
  u8g2.begin();
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  server.on("/", [](){ server.send_P(200, "text/html; charset=utf-8", PAGE); });
  server.on("/forward", [](){ requestMotion(FORWARD); });
  server.on("/back", [](){ requestMotion(BACK); });
  server.on("/left", [](){ requestMotion(LEFT); });
  server.on("/right", [](){ requestMotion(RIGHT); });
  server.on("/stop", [](){ requestMotion(STOPPED); });
  server.begin();
}

void loop() {
  // 处理网页控制请求
  server.handleClient();

  // 每 500 毫秒刷新一次 OLED
  static uint32_t lastDisplay = 0;

  if ((uint32_t)(millis() - lastDisplay) >= 500) {
    lastDisplay = millis();
    showStatus();
  }

  // 每 2 秒打印一次 Wi-Fi 状态
  static uint32_t lastSerial = 0;

  if ((uint32_t)(millis() - lastSerial) >= 2000) {
    lastSerial = millis();

    Serial.print("System running. WiFi: ");

    if (WiFi.status() == WL_CONNECTED) {
      Serial.print("CONNECTED, IP: ");
      Serial.println(WiFi.localIP());
    } else {
      Serial.println("DISCONNECTED");
    }
  }

  delay(5);
}
