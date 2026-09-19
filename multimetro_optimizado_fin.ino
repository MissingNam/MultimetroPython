// ---------------------------------------------------------
// Prototipo de multimetro portatil - ESP32-S3
// Version con auto-rango: resistencia y capacitancia ya no
// requieren que el usuario elija sub-rango manualmente.
//
// Modos:
// 0  = Voltaje
// 1  = Corriente
// 2  = Resistencia (auto-rango: 100 / 1k / 10k / 100k / 505k)
// 3  = Capacitancia (auto-rango: mismos 5 canales)
// 4  = Continuidad
// 5  = Frecuencia
// ---------------------------------------------------------

#include <Wire.h>
#include <Adafruit_INA219.h>
#include "BLEDevice.h"
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include "driver/gpio.h"

#define SERVICE_UUID        "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
#define CHARACTERISTIC_UUID_RX "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
#define CHARACTERISTIC_UUID_TX "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

BLEServer *pServer;
BLECharacteristic *pTxCharacteristic;
BLECharacteristic *pRxCharacteristic;
bool deviceConnected = false;

Adafruit_INA219 ina219;


// =========================================================
// Pines de entrada analogica
// =========================================================

const int PIN_RESISTENCIA = 2;  // Pin directo al COM del MUX
const int PIN_FRECUENCIA = 10;  // PIN de interrupcion para Frecuencia
const int PIN_SDA = 8;
const int PIN_SCL = 9;
const int PIN_CON_MUX = 11;     // Pin que conecta el INA con el MUX
const int PIN_GND = 15;         // Transistor que lleva caiman negro a GND
const int PIN_INA = 17;         // Transistor que lleva caiman negro a V- del INA219

// Unido con un cable directo al nodo de PIN_EXCITACION, para medir
// el VCC real que esta saliendo de ese GPIO bajo carga (compensa la
// caida IR interna del driver del pin).
const int PIN_VCC_MONITOR = 4;

// =========================================================
// Pines de control del mux CD4051
// =========================================================

const int MUX_A = 7;
const int MUX_B = 6;
const int MUX_C = 5;


// =========================================================
// Pin de excitacion
// LOW  -> descarga capacitor
// HIGH -> alimenta circuito de resistencia/capacitancia
// =========================================================

const int PIN_EXCITACION = 12;


// =========================================================
// ADC
// =========================================================
const float ADC_MAX = 4095.0; // Valor maximo del ADC del ESP32

// VCC ya no es una constante fija: se mide en tiempo real desde
// PIN_VCC_MONITOR justo antes/durante cada lectura.
const float VCC_NOMINAL = 3.2;


// =========================================================
// Valores de referencia para resistencia y capacitancia
//
// El indice de este arreglo = canal fisico del mux.
// Indice 0 -> 1k    (canal mux 0)
// Indice 1 -> 10k   (canal mux 1)
// Indice 2 -> 100k  (canal mux 2)
// Indice 3 -> 100   (canal mux 3)
// Indice 4 -> 505k  (canal mux 4, NUEVO)
// =========================================================

const int NUM_RREF = 5;

const float RREF_VALOR[NUM_RREF] = {
  1470.0,    // canal 0 -> 1k
  10470.0,   // canal 1 -> 10k
  101200.0,  // canal 2 -> 100k
  245.0,     // canal 3 -> 100
  505000.0   // canal 4 -> 505k (TODO: calibrar con multimetro real)
};

// Orden de canales del mas chico al mas grande, usado por el
// auto-rango (aqui SI importa el orden por magnitud, no por
// numero de canal).
const int ORDEN_RANGO[NUM_RREF] = {3, 0, 1, 2, 4}; // 100, 1k, 10k, 100k, 505k

// Para mostrar mejor la frecuencia
const char* unidades[] = {"Hz", "kHz", "MHz"};


// =========================================================
// Continuidad
// =========================================================
const float UMBRAL_CONTINUIDAD = 10.0; // Si la resistencia es menor, es continuo

// =========================================================
// Frecuencia
// =========================================================
volatile unsigned long tiempoAnterior = 0;
volatile unsigned long periodoMedido = 0;
volatile bool nuevoDato = false;


// =========================================================
// Capacitancia
// =========================================================
const int UMBRAL_DESCARGA_COUNTS = 10;
const unsigned long TIMEOUT_US = 3000000UL; // 3 segundos

// Numero de lecturas consecutivas que deben cumplir el umbral
// antes de aceptarlo como cruce real (evita disparos falsos por ruido)
const int MUESTRAS_DEBOUNCE = 3;

// Tiempo minimo de carga para considerar la lectura confiable.
// Por debajo de esto, un tiempo de carga corto probablemente sea
// piso de ruido/parasitos, no una medicion real -> se descarta y
// el auto-rango prueba el siguiente canal (Rref mas grande).
// AJUSTAR: medir con puntas al aire en el canal mas chico (100)
// y poner este valor un poco arriba de lo que se observe ahi.
const unsigned long TIEMPO_MINIMO_VALIDO_US = 55;


// =========================================================
// Oversampling / promediado de ADC
// =========================================================
const int MUESTRAS_ADC = 64;          // muestras por lectura
const int RETARDO_ENTRE_MUESTRAS_US = 100;

// Tiempo de asentamiento tras cambiar canal de mux / excitacion
const int RETARDO_ASENTAMIENTO_MS = 3;


// =========================================================
// Filtro EMA (media movil exponencial)
// =========================================================
const float ALPHA_RESISTENCIA   = 0.25;
const float ALPHA_CAPACITANCIA  = 0.30;
const float ALPHA_VOLTAJE       = 0.20;
const float ALPHA_CORRIENTE     = 0.20;

float filtroResistencia[NUM_RREF]  = { -1, -1, -1, -1, -1 };
float filtroCapacitancia[NUM_RREF] = { -1, -1, -1, -1, -1 };
float filtroVoltaje = -1;
float filtroCorriente = -1;

int modoAnterior = -1;


// =========================================================
// Modo actual
// =========================================================

int modo = 0;

// =========================================================
// INTERRUPCION DE MEDICION DE LA FRECUENCIA
// =========================================================
void IRAM_ATTR isrFrecuencia() {
  unsigned long ahora = micros();
  periodoMedido = ahora - tiempoAnterior;
  tiempoAnterior = ahora;
  nuevoDato = true;
}

// =========================================================
// CALLBACK DE DESCONEXION/RECONEXION
// =========================================================
class MisCallbacksServidor: public BLEServerCallbacks {
  void onConnect(BLEServer* pServer) {
    deviceConnected = true;
  }
  void onDisconnect(BLEServer* pServer) {
    deviceConnected = false;
    delay(500);
    pServer->getAdvertising()->start();
  }
};

// =========================================================
// Envio por medio de bluetooth
// =========================================================
void enviarBLE(String mensaje) {
  if (deviceConnected) {
    pTxCharacteristic->setValue(mensaje.c_str());
    pTxCharacteristic->notify();
  }
}

// =========================================================
// Activa o desactiva la interrupcion de frecuencia segun el modo
// =========================================================
void actualizarInterrupcionFrecuencia(int nuevoModo) {
  if (nuevoModo == 5) {
    attachInterrupt(digitalPinToInterrupt(PIN_FRECUENCIA), isrFrecuencia, RISING);
  } else {
    detachInterrupt(digitalPinToInterrupt(PIN_FRECUENCIA));
  }
}

// =========================================================
// Callback de escritura BLE: recibe los comandos "MOD:xxx"
//
// Ya no hay comandos por sub-categoria (R1k, C100k, etc.) --
// resistencia y capacitancia ahora auto-detectan el rango.
// =========================================================
class MisCallbacksRX: public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *pCharacteristic) {
    String dato = String(pCharacteristic->getValue().c_str());
    dato.trim();

    String command = dato.substring(4); // quita el "MOD:"

    if (command == "V") modo = 0;
    else if (command == "I") modo = 1;
    else if (command == "R1k") modo = 2;
    else if (command == "C1k") modo = 3;
    else if (command == "CON") modo = 4;
    else if (command == "FRE") modo = 5;

    if (modo != modoAnterior) {
      actualizarInterrupcionFrecuencia(modo);
    }
  }
};

// =========================================================
// SETUP
// =========================================================

void setup() {

  BLEDevice::init("ESP32_BLE_LEO");
  pServer = BLEDevice::createServer();
  BLEService *pService = pServer->createService(SERVICE_UUID);
  pTxCharacteristic = pService->createCharacteristic(
  CHARACTERISTIC_UUID_TX,
  BLECharacteristic::PROPERTY_NOTIFY);

  pRxCharacteristic = pService->createCharacteristic(
  CHARACTERISTIC_UUID_RX,
  BLECharacteristic::PROPERTY_WRITE);

  pRxCharacteristic->setCallbacks(new MisCallbacksRX());
  pServer->setCallbacks(new MisCallbacksServidor());
  pTxCharacteristic->addDescriptor(new BLE2902());
  pService->start();

  BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();
  pAdvertising->addServiceUUID(SERVICE_UUID);
  pAdvertising->start();

  // INA219 Setup
  Wire.begin(PIN_SDA, PIN_SCL);

  if (!ina219.begin()) {
    enviarBLE("No se detecto el INA219, revisa cableado");
  }

  ina219.setCalibration_32V_1A();

  // ADC de 12 bits
  analogReadResolution(12);

  // Configuracion de Pines
  pinMode(PIN_RESISTENCIA, INPUT);
  pinMode(PIN_GND, OUTPUT);
  pinMode(PIN_INA, OUTPUT);
  pinMode(PIN_CON_MUX, OUTPUT);
  pinMode(PIN_VCC_MONITOR, INPUT);

  // CD4051
  pinMode(MUX_A, OUTPUT);
  pinMode(MUX_B, OUTPUT);
  pinMode(MUX_C, OUTPUT);

  // Excitacion
  pinMode(PIN_EXCITACION, OUTPUT);

  // Aumenta la fuerza de manejo del pin de excitacion para reducir
  // su resistencia interna de salida y, con ello, la caida de voltaje
  // bajo carga (mejora complementaria a la medicion en tiempo real).
  gpio_set_drive_capability((gpio_num_t)PIN_EXCITACION, GPIO_DRIVE_CAP_3);

  // Estado inicial: default para voltaje
  digitalWrite(PIN_EXCITACION, LOW);
  digitalWrite(PIN_CON_MUX, LOW);
}


// =========================================================
// SELECCION DEL CANAL DEL CD4051
// =========================================================
void seleccionarCanalMux(int canal) {
  digitalWrite(MUX_A, canal & 0b001);
  digitalWrite(MUX_B, (canal >> 1) & 0b001);
  digitalWrite(MUX_C, (canal >> 2) & 0b001);
}


// =========================================================
// LECTURA DE VCC REAL (en volts), medida directo del nodo de
// excitacion via analogReadMilliVolts(), que usa la curva de
// calibracion de fabrica del ESP32.
// =========================================================
float leerVCCReal() {
  return analogReadMilliVolts(PIN_VCC_MONITOR) / 1000.0;
}


// =========================================================
// LECTURA DE ADC CON OVERSAMPLING (promedio de N muestras)
// Devuelve counts promedio (0-4095), no voltaje
// =========================================================
float leerADCPromediado(int pin, int muestras = MUESTRAS_ADC) {
  long suma = 0;
  for (int i = 0; i < muestras; i++) {
    suma += analogRead(pin);
    delayMicroseconds(RETARDO_ENTRE_MUESTRAS_US);
  }
  return suma / (float)muestras;
}


// =========================================================
// LECTURA DE VOLTAJE DE NODO VIA INA219 (promediada)
// =========================================================
float leerVoltajeINA219Promediado(int muestras) {
  float suma = 0;
  for (int i = 0; i < muestras; i++) {
    suma += ina219.getBusVoltage_V();
    delay(1);
  }
  return suma / muestras;
}


// =========================================================
// OFFSET DE CALIBRACION (Ohms) por canal de resistencia
// =========================================================
float OFFSET_RESISTENCIA[NUM_RREF] = {0.0, 0.0, 0.0, 0.0, 0.0};


// =========================================================
// CALCULO DE RESISTENCIA (Divisor de Voltaje)
//
// Vnodo = VCC * Rx / (Rref + Rx)
// Rx = Rref * Vnodo / (VCC - Vnodo)
// =========================================================
float calcularResistencia(float vNodo, float rRef, float vcc) {
  if (vNodo >= vcc) {
    return -1;
  }
  if (vNodo <= 0.0) {
    return 0.0;
  }
  float voltaje = (analogRead(PIN_RESISTENCIA) / 4095.0) * 3.3;
  return (rRef * vNodo) / (vcc - vNodo);
}


// =========================================================
// AUTO-RANGO DE RESISTENCIA
//
// Prueba los canales del mas chico al mas grande (ORDEN_RANGO).
// Si el nodo esta casi saturado (cerca de VCC), esa Rref es
// demasiado chica para lo conectado -> se prueba la siguiente,
// mas grande. Devuelve -1 solo si NINGUN rango dio una lectura
// valida (circuito realmente abierto).
// =========================================================
float medirResistenciaAutoRango(int &canalUsado) {
  for (int i = 1; i < NUM_RREF; i++) {
    int canal = ORDEN_RANGO[i];
    float rRef = RREF_VALOR[canal];

    seleccionarCanalMux(canal);
    digitalWrite(PIN_EXCITACION, HIGH);
    delay(RETARDO_ASENTAMIENTO_MS);

    float vccReal = leerVCCReal();
    float vNodo = leerVoltajeINA219Promediado(8);

    // Nodo casi saturado: esta Rref es muy chica para lo conectado
    float voltaje = (analogRead(PIN_RESISTENCIA) / 4095.0) * 3.3;
    enviarBLE(String(vNodo) + "|" + String(voltaje));
    delay(500);
    if (voltaje >= 2.05 || voltaje <= 0.5) {
      continue;
    }
    
    float resistencia = calcularResistencia(voltaje, rRef, vccReal) - OFFSET_RESISTENCIA[canal];

    if (resistencia > 0) {
      canalUsado = canal;
      return resistencia;
    }
  }
  canalUsado = -1;
  return -1; // ningun rango dio lectura valida: circuito abierto real
}


// =========================================================
// Aplica filtro EMA
// =========================================================
float aplicarFiltroEMA(float &estadoFiltro, float valorNuevo, float alpha) {
  if (estadoFiltro < 0) {
    estadoFiltro = valorNuevo;
  } else {
    estadoFiltro = alpha * valorNuevo + (1.0 - alpha) * estadoFiltro;
  }
  return estadoFiltro;
}


// =========================================================
// Resetea todos los filtros
// =========================================================
void resetearFiltros() {
  for (int i = 0; i < NUM_RREF; i++) {
    filtroResistencia[i] = -1;
    filtroCapacitancia[i] = -1;
  }
  filtroVoltaje = -1;
  filtroCorriente = -1;
}


// =========================================================
// MEDICION DE CAPACITANCIA (con debounce anti-ruido)
//
// El umbral de carga (63.2% de VCC) se calcula con el VCC real
// medido justo despues de conmutar a HIGH. Si el tiempo de carga
// resulta menor a TIEMPO_MINIMO_VALIDO_US, se descarta como
// piso de ruido (Rref demasiado chica para este capacitor).
//
// V(t) = VCC * (1 - e^(-t/RC))
// =========================================================
float medirCapacitancia(int canal, float rRef) {

  seleccionarCanalMux(canal);
  delay(RETARDO_ASENTAMIENTO_MS);

  // -------------------------------------------------------
  // 1. Descargar capacitor (debounce: N lecturas seguidas bajo umbral)
  // -------------------------------------------------------
  digitalWrite(PIN_EXCITACION, LOW);
  unsigned long inicioDescarga = micros();
  int consecutivas = 0;
  while (consecutivas < MUESTRAS_DEBOUNCE) {
    if (analogRead(PIN_RESISTENCIA) <= UMBRAL_DESCARGA_COUNTS) {
      consecutivas++;
    } else {
      consecutivas = 0;
    }
    yield();
    if (micros() - inicioDescarga > TIMEOUT_US) {
      return -1;
    }
  }

  // -------------------------------------------------------
  // 2. Iniciar carga, y medir VCC real justo despues de que
  //    el pin ya este en HIGH
  // -------------------------------------------------------
  digitalWrite(PIN_EXCITACION, HIGH);

  //float vccReal = leerVCCReal();
  int umbralCargaCounts = (int)((0.6 * 3.2 / 3.3) * ADC_MAX);

  unsigned long inicioCarga = micros();

  consecutivas = 0;
  unsigned long tiempoCruce = 0;
  while (consecutivas < MUESTRAS_DEBOUNCE) {
    if (analogRead(PIN_RESISTENCIA) >= umbralCargaCounts) {
      if (consecutivas == 0) {
        tiempoCruce = micros();
      }
      consecutivas++;
    } else {
      consecutivas = 0;
    }
    yield();
    if (micros() - inicioCarga > TIMEOUT_US) {
      return -1;
    }
  }

  unsigned long tiempoCarga = tiempoCruce - inicioCarga;

  if (tiempoCarga < TIEMPO_MINIMO_VALIDO_US) {
    return -1; // demasiado rapido para esta Rref, no confiable
  }

  float capacitanciaUF = (float)tiempoCarga / rRef;
  return capacitanciaUF;
}


// =========================================================
// AUTO-RANGO DE CAPACITANCIA
//
// Prueba los canales del mas chico al mas grande. -1 puede
// significar "demasiado rapido" o timeout; en ambos casos se
// prueba el siguiente rango. Si ninguno funciona, se asume
// circuito abierto o sin capacitor conectado.
// =========================================================
float medirCapacitanciaAutoRango(int &canalUsado) {
  for (int i = 0; i < NUM_RREF; i++) {
    int canal = ORDEN_RANGO[i];
    float valor = medirCapacitancia(canal, RREF_VALOR[canal]);
    if (valor > 0) {
      canalUsado = canal;
      return valor;
    }
  }
  canalUsado = -1;
  return -1;
}


// =========================================================
// LOOP
// =========================================================

void loop() {
  if (modo != modoAnterior) {
    resetearFiltros();
    modoAnterior = modo;
  }

  switch (modo) {

    // =====================================================
    // VOLTAJE
    // =====================================================
    case 0: {
      seleccionarCanalMux(7);
      digitalWrite(PIN_GND, HIGH);
      digitalWrite(PIN_INA, LOW);
      digitalWrite(PIN_EXCITACION, LOW);
      digitalWrite(PIN_CON_MUX, LOW);

      float voltajeCrudo = ina219.getBusVoltage_V();
      float voltaje = aplicarFiltroEMA(filtroVoltaje, voltajeCrudo, ALPHA_VOLTAJE);
      voltaje -= 0.02;

      enviarBLE(String(voltaje) + " V");
      break;
    }

    // =====================================================
    // CORRIENTE
    // =====================================================
    case 1: {
      seleccionarCanalMux(7);
      digitalWrite(PIN_CON_MUX, LOW);

      double corrienteCruda = ina219.getCurrent_mA();
      float corriente = aplicarFiltroEMA(filtroCorriente, corrienteCruda, ALPHA_CORRIENTE);

      enviarBLE(String(corriente) + " mA");
      break;
    }

    // =====================================================
    // RESISTENCIA (auto-rango)
    // =====================================================
    case 2: {
      digitalWrite(PIN_GND, HIGH);
      digitalWrite(PIN_INA, LOW);
      digitalWrite(PIN_CON_MUX, HIGH);

      int canalUsado;
      float resistenciaCruda = medirResistenciaAutoRango(canalUsado);

      if (resistenciaCruda <= 0) {
        enviarBLE("Circuito Abierto");
      } else {
        float resistencia = aplicarFiltroEMA(filtroResistencia[canalUsado], resistenciaCruda, ALPHA_RESISTENCIA);
        enviarBLE(String(resistencia) + " Ohms");
      }
      break;
    }

    // =====================================================
    // CAPACITANCIA (auto-rango)
    // =====================================================
    case 3: {
      digitalWrite(PIN_CON_MUX, HIGH);

      int canalUsado;
      float capacitanciaCruda = medirCapacitanciaAutoRango(canalUsado);

      if (capacitanciaCruda <= 0) {
        enviarBLE("Abierto o Fuera de Rango");
      } else {
        float capacitancia = aplicarFiltroEMA(filtroCapacitancia[canalUsado], capacitanciaCruda, ALPHA_CAPACITANCIA);
        enviarBLE(String(capacitancia, 3) + " uF");
      }
      break;
    }

    // =====================================================
    // CONTINUIDAD
    // =====================================================
    case 4: {
      digitalWrite(PIN_GND, HIGH);
      digitalWrite(PIN_INA, LOW);
      seleccionarCanalMux(7);
      digitalWrite(PIN_CON_MUX, HIGH);
      digitalWrite(PIN_EXCITACION, HIGH);

      delay(RETARDO_ASENTAMIENTO_MS);

      float vccReal = leerVCCReal();
      float vNodo = leerVoltajeINA219Promediado(3);

      float resistencia = calcularResistencia(vNodo, RREF_VALOR[0], vccReal) - OFFSET_RESISTENCIA[0];

      if (resistencia >= 0 && resistencia < UMBRAL_CONTINUIDAD) {
        enviarBLE("SI");
      } else {
        enviarBLE("NO");
      }
      break;
    }

    // =====================================================
    // FRECUENCIA
    // =====================================================
    case 5: {
      digitalWrite(PIN_CON_MUX, HIGH);
      if (nuevoDato && periodoMedido > 0) {

        float frecuencia = (1000000.0 / periodoMedido);
        int unidad = 0;
        while (frecuencia >= 1000.0 && unidad < 2) {
          frecuencia /= 1000.0;
          unidad++;
        }
        String frecuenciaTexto = String(frecuencia, 1) + " " + unidades[unidad];

        const unsigned long VENTANA_MAX_US = 10000UL;
        unsigned long duracionVentana = min((unsigned long)periodoMedido, VENTANA_MAX_US);

        int minADC = 4095;
        int maxADC = 0;
        unsigned long finVentana = micros() + duracionVentana;
        while (micros() < finVentana) {
          int muestra = analogRead(PIN_RESISTENCIA);
          if (muestra < minADC) minADC = muestra;
          if (muestra > maxADC) maxADC = muestra;
        }

        float amplitud   = (maxADC - minADC) / 2.0;
        float puntoMedio = (maxADC + minADC) / 2.0;

        enviarBLE(frecuenciaTexto + "," + String(amplitud, 1) + "," + String(puntoMedio, 1));
        nuevoDato = false;
      }
      break;
    }

    default: {
      break;
    }
  }
  delay(50);
}
