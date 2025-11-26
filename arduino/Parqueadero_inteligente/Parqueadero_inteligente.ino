// esp32_parqueadero.ino
#include <WiFi.h>
#include <HTTPClient.h>
#include <SPI.h>
#include <MFRC522.h>
#include <ESP32Servo.h>

// ---------- WIFI / SERVER ----------
const char* ssid ="juanpablo";
const char* password ="soyjuanpablo";
String serverURL = "http://10.161.108.244:5000";

// ---------- SERVO ----------
#define SERVO_PIN 13
Servo servoBarrera;

// ---------- RFID ENTRADA ----------
#define SS_PIN_ENTRADA  5
#define RST_PIN_ENTRADA 22
MFRC522 rfid_entrada(SS_PIN_ENTRADA, RST_PIN_ENTRADA);

// ---------- RFID SALIDA ----------
#define SS_PIN_SALIDA   21
#define RST_PIN_SALIDA  2
MFRC522 rfid_salida(SS_PIN_SALIDA, RST_PIN_SALIDA);

// 🆕 SENSORES DE ESPACIOS ----------
#define SENSOR_1 32
#define SENSOR_2 33
#define SENSOR_3 34

// ---------- CONTROL ----------
unsigned long ultimaLecturaEntrada = 0;
unsigned long ultimaLecturaSalida = 0;
unsigned long lastSensorUpdate = 0;
const unsigned long debounce_ms = 2000;
const unsigned long sensorInterval = 2000;
String lastUIDEntrada = "";
String lastUIDSalida = "";

// 🆕 VARIABLES PARA SENSORES
bool lastSensorState1 = false;
bool lastSensorState2 = false;
bool lastSensorState3 = false;

// ---------- FUNCIONES DE BARRERA ----------
void abrirBarrera() {
  Serial.println("🔓 Abriendo barrera...");
  for (int pos = 90; pos >= 0; pos--) {
    servoBarrera.write(pos);
    delay(15);
  }
}

void cerrarBarrera() {
  Serial.println("🔒 Cerrando barrera...");
  for (int pos = 0; pos <= 90; pos++) {
    servoBarrera.write(pos);
    delay(15);
  }
}

void abrirBarreraTemporizada(int msDelay) {
  Serial.println("🚦 Abriendo barrera por " + String(msDelay) + "ms");
  abrirBarrera();
  delay(msDelay);
  cerrarBarrera();
  Serial.println("✅ Barrera cerrada");
}

// ---------- UTILIDADES HTTP ----------
bool httpPostJson(String endpoint, String jsonPayload, String &responseOut) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("❌ WiFi no conectado");
    return false;
  }
  
  HTTPClient http;
  String url = serverURL + endpoint;
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(5000);
  
  Serial.println("📤 Enviando POST a: " + url);
  Serial.println("📦 Payload: " + jsonPayload);
  
  int code = http.POST(jsonPayload);
  if (code > 0) {
    responseOut = http.getString();
    Serial.println("✅ HTTP POST exitoso - Código: " + String(code));
    http.end();
    return true;
  } else {
    Serial.println("❌ HTTP POST error: " + String(code));
    http.end();
    return false;
  }
}

// ---------- LEER UID RC522 ----------
String leerUID(MFRC522 &mfrc522) {
  String uid = "";
  for (byte i = 0; i < mfrc522.uid.size; i++) {
    if (mfrc522.uid.uidByte[i] < 0x10) uid += "0";
    uid += String(mfrc522.uid.uidByte[i], HEX);
  }
  uid.toUpperCase();
  return uid;
}

// 🆕 FUNCIÓN PARA LEER SENSORES (SILENCIOSA)
void leerSensores() {
  bool sensor1 = digitalRead(SENSOR_1) == LOW;
  bool sensor2 = digitalRead(SENSOR_2) == LOW;
  bool sensor3 = digitalRead(SENSOR_3) == LOW;
  
  if (sensor1 != lastSensorState1 || sensor2 != lastSensorState2 || sensor3 != lastSensorState3) {
    String jsonSensores = "{";
    jsonSensores += "\"sensor_1\":" + String(sensor1 ? "true" : "false");
    jsonSensores += ",\"sensor_2\":" + String(sensor2 ? "true" : "false");
    jsonSensores += ",\"sensor_3\":" + String(sensor3 ? "true" : "false");
    jsonSensores += "}";
    
    String respuesta;
    httpPostJson("/api/sensores/actualizar", jsonSensores, respuesta);
    
    lastSensorState1 = sensor1;
    lastSensorState2 = sensor2;
    lastSensorState3 = sensor3;
  }
}

// 🆕 FUNCIÓN CORREGIDA PARA ENTRADA - SOLO ABRE BARRERA CUANDO HAY ESPACIO
void procesarEntrada(String tarjeta_rfid) {
  Serial.println("🎫 PROCESANDO ENTRADA - Tarjeta: " + tarjeta_rfid);
  
  String respuesta;
  String json = "{\"tarjeta_rfid\":\"" + tarjeta_rfid + "\"}";
  
  if (httpPostJson("/api/entrada/detectar", json, respuesta)) {
    respuesta.trim();
    
    Serial.println("=== PROCESANDO ENTRADA ===");
    
    // 🆕 VERIFICAR SI SE PERMITE LA ENTRADA ANTES DE ABRIR BARRERA
    bool entrada_permitida = respuesta.indexOf("ENTRADA_PERMITIDA") >= 0;
    bool usuario_nuevo = respuesta.indexOf("USUARIO_NUEVO") >= 0;
    bool no_espacios = respuesta.indexOf("NO_HAY_ESPACIOS") >= 0;
    bool saldo_insuficiente = respuesta.indexOf("SALDO_INSUFICIENTE") >= 0;
    bool entrada_duplicada = respuesta.indexOf("ENTRADA_DUPLICADA") >= 0;
    
    String accion = "";
    int idx_accion = respuesta.indexOf("\"accion\"");
    if (idx_accion >= 0) {
      int start = respuesta.indexOf(":", idx_accion) + 1;
      int end = respuesta.indexOf(",", start);
      if (end == -1) end = respuesta.indexOf("}", start);
      if (end > start) {
        accion = respuesta.substring(start, end);
        accion.replace("\"", "");
        accion.trim();
      }
    }
    
    Serial.println("Accion detectada: '" + accion + "'");
    Serial.println("======================");
    
    // 🎯 SOLO ABRIR BARRERA EN CASOS ESPECÍFICOS
    if (entrada_permitida || accion == "ENTRADA_PERMITIDA") {
      Serial.println("✅ ENTRADA PERMITIDA - Abriendo barrera");
      
      String espacio = "";
      int idx_espacio = respuesta.indexOf("\"espacio\"");
      if (idx_espacio >= 0) {
        int start = respuesta.indexOf(":", idx_espacio) + 1;
        int end = respuesta.indexOf(",", start);
        if (end == -1) end = respuesta.indexOf("}", start);
        if (end > start) {
          espacio = respuesta.substring(start, end);
          espacio.replace("\"", "");
          espacio.trim();
          Serial.println("📍 Espacio asignado: " + espacio);
        }
      }
      
      abrirBarreraTemporizada(5000);
    }
    else if (usuario_nuevo || accion == "USUARIO_NUEVO") {
      Serial.println("👤 USUARIO NUEVO - Abriendo barrera para registro");
      
      String url_registro = "";
      int idx_url = respuesta.indexOf("url_registro");
      if (idx_url >= 0) {
        int start = respuesta.indexOf(":", idx_url) + 1;
        int end = respuesta.indexOf(",", start);
        if (end == -1) end = respuesta.indexOf("}", start);
        if (end > start) {
          url_registro = respuesta.substring(start, end);
          url_registro.replace("\"", "");
          url_registro.trim();
          Serial.println("📱 URL Registro: " + url_registro);
        }
      }
      
      abrirBarreraTemporizada(5000);
    }
    else if (no_espacios || accion == "NO_HAY_ESPACIOS") {
      Serial.println("🅿️ ❌ NO HAY ESPACIOS DISPONIBLES");
      Serial.println("🚫 Barrera NO se abre - Espere a que se libere un espacio");
      // 🆕 NO ABRIR BARRERA
    }
    else if (saldo_insuficiente || accion == "SALDO_INSUFICIENTE") {
      Serial.println("💰 ❌ SALDO INSUFICIENTE");
      Serial.println("🚫 Barrera NO se abre - Recargue su saldo");
      // 🆕 NO ABRIR BARRERA
      
      String url_recarga = "";
      int idx_url = respuesta.indexOf("url_recarga");
      if (idx_url >= 0) {
        int start = respuesta.indexOf(":", idx_url) + 1;
        int end = respuesta.indexOf(",", start);
        if (end == -1) end = respuesta.indexOf("}", start);
        if (end > start) {
          url_recarga = respuesta.substring(start, end);
          url_recarga.replace("\"", "");
          url_recarga.trim();
          Serial.println("📱 URL Recarga: " + url_recarga);
        }
      }
    }
    else if (entrada_duplicada || accion == "ENTRADA_DUPLICADA") {
      Serial.println("⚠️ 🚫 YA TIENE ENTRADA ACTIVA");
      Serial.println("🚫 Barrera NO se abre - Ya está dentro del parqueadero");
      // 🆕 NO ABRIR BARRERA
    }
    else {
      Serial.println("❌ 🤔 Respuesta no reconocida del servidor");
      Serial.println("🚫 Barrera NO se abre por seguridad");
      // 🆕 NO ABRIR BARRERA
    }
    
  } else {
    Serial.println("❌ 🌐 Error de comunicación con el servidor");
    Serial.println("🚫 Barrera NO se abre por seguridad");
  }
}

// 🆕 FUNCIÓN MEJORADA PARA SALIDA
void procesarSalida(String tarjeta_rfid) {
  Serial.println("🎫 PROCESANDO SALIDA - Tarjeta: " + tarjeta_rfid);
  
  String respuesta;
  String json = "{\"tarjeta_rfid\":\"" + tarjeta_rfid + "\"}";
  
  if (httpPostJson("/api/salida/detectar", json, respuesta)) {
    if (respuesta.indexOf("SALIDA_PERMITIDA") >= 0 || respuesta.indexOf("ABRIR_BARRERA") >= 0) {
      Serial.println("✅ SALIDA PERMITIDA - Abriendo barrera");
      
      // Extraer monto cobrado
      String monto_cobrado = "";
      int idx_monto = respuesta.indexOf("\"monto_cobrado\"");
      if (idx_monto >= 0) {
        int start = respuesta.indexOf(":", idx_monto) + 1;
        int end = respuesta.indexOf(",", start);
        if (end == -1) end = respuesta.indexOf("}", start);
        if (end > start) {
          monto_cobrado = respuesta.substring(start, end);
          monto_cobrado.replace("\"", "");
          monto_cobrado.trim();
          Serial.println("💰 Monto cobrado: $" + monto_cobrado);
        }
      }
      
      // Extraer nuevo saldo
      String nuevo_saldo = "";
      int idx_saldo = respuesta.indexOf("\"nuevo_saldo\"");
      if (idx_saldo >= 0) {
        int start = respuesta.indexOf(":", idx_saldo) + 1;
        int end = respuesta.indexOf(",", start);
        if (end == -1) end = respuesta.indexOf("}", start);
        if (end > start) {
          nuevo_saldo = respuesta.substring(start, end);
          nuevo_saldo.replace("\"", "");
          nuevo_saldo.trim();
          Serial.println("💳 Nuevo saldo: $" + nuevo_saldo);
        }
      }

      // Extraer factura URL
      String factura_url = "";
      int idx_factura = respuesta.indexOf("\"factura_url\"");
      if (idx_factura >= 0) {
        int start = respuesta.indexOf(":", idx_factura) + 1;
        int end = respuesta.indexOf(",", start);
        if (end == -1) end = respuesta.indexOf("}", start);
        if (end > start) {
          factura_url = respuesta.substring(start, end);
          factura_url.replace("\"", "");
          factura_url.trim();
          Serial.println("🧾 Factura: " + factura_url);
        }
      }
      
      abrirBarreraTemporizada(5000);
    }
    else if (respuesta.indexOf("SALDO_INSUFICIENTE_SALIDA") >= 0) {
      Serial.println("❌ SALDO INSUFICIENTE PARA SALIR");
      
      // Extraer información adicional
      String monto_requerido = "";
      int idx_monto_req = respuesta.indexOf("\"monto_requerido\"");
      if (idx_monto_req >= 0) {
        int start = respuesta.indexOf(":", idx_monto_req) + 1;
        int end = respuesta.indexOf(",", start);
        if (end == -1) end = respuesta.indexOf("}", start);
        if (end > start) {
          monto_requerido = respuesta.substring(start, end);
          monto_requerido.replace("\"", "");
          monto_requerido.trim();
          Serial.println("💰 Monto requerido: $" + monto_requerido);
        }
      }
    }
    else {
      Serial.println("❌ No se pudo procesar la salida");
    }
  } else {
    Serial.println("❌ Error de comunicación con el servidor");
  }
}

// ---------- SETUP ----------
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n🚗 ESP32 - Sistema de Parqueadero Inteligente");
  Serial.println("📍 Versión 7.0 - Control de espacios mejorado");

  pinMode(SENSOR_1, INPUT_PULLUP);
  pinMode(SENSOR_2, INPUT_PULLUP);
  pinMode(SENSOR_3, INPUT_PULLUP);

  servoBarrera.attach(SERVO_PIN);
  cerrarBarrera();

  SPI.begin();
  rfid_entrada.PCD_Init();
  rfid_salida.PCD_Init();

  WiFi.begin(ssid, password);
  Serial.print("📶 Conectando a WiFi");
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 20000) {
    delay(500);
    Serial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n✅ WiFi conectado, IP: " + WiFi.localIP().toString());
    Serial.println("📍 Servidor: " + serverURL);
  } else {
    Serial.println("\n❌ WiFi NO conectado");
  }
  
  Serial.println("\n✅ Sistema listo - Esperando tarjetas RFID...");
  Serial.println("🎫 Entrada: RFID superior");
  Serial.println("🎫 Salida: RFID inferior");
  Serial.println("=====================================");
}

// ---------- LOOP principal ----------
void loop() {
  // RFID ENTRADA
  if (rfid_entrada.PICC_IsNewCardPresent() && rfid_entrada.PICC_ReadCardSerial()) {
    String uid = leerUID(rfid_entrada);
    if (uid != "" && (millis() - ultimaLecturaEntrada > debounce_ms) && uid != lastUIDEntrada) {
      ultimaLecturaEntrada = millis();
      lastUIDEntrada = uid;
      Serial.println("\n🎫 TARJETA ENTRADA DETECTADA: " + uid);
      procesarEntrada(uid);
    }
    rfid_entrada.PICC_HaltA();
    rfid_entrada.PCD_StopCrypto1();
  }

  // RFID SALIDA
  if (rfid_salida.PICC_IsNewCardPresent() && rfid_salida.PICC_ReadCardSerial()) {
    String uid = leerUID(rfid_salida);
    if (uid != "" && (millis() - ultimaLecturaSalida > debounce_ms) && uid != lastUIDSalida) {
      ultimaLecturaSalida = millis();
      lastUIDSalida = uid;
      Serial.println("\n🎫 TARJETA SALIDA DETECTADA: " + uid);
      procesarSalida(uid);
    }
    rfid_salida.PICC_HaltA();
    rfid_salida.PCD_StopCrypto1();
  }

  // LEER SENSORES CADA 2 SEGUNDOS (SILENCIOSO)
  if (millis() - lastSensorUpdate > sensorInterval) {
    lastSensorUpdate = millis();
    leerSensores();
  }

  delay(100);
}