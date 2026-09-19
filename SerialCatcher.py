import asyncio
import threading
import queue
from bleak import BleakClient, BleakScanner

# Deben coincidir con los UUID definidos en el firmware del ESP32 (copiar y pegar)
SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
CHARACTERISTIC_UUID_RX = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"  # escritura: PC -> ESP32
CHARACTERISTIC_UUID_TX = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"  # notificacion: ESP32 -> PC

# Pese a que se llama serialCatcher, ya no hace eso
# Mantuve nombres y metodos para no tener que cambiar mucho las cosas
# En la ventana principal
class serialCatcher:

    def __init__(self, puerto, baudrate=9600):
        # 'puerto' ahora es la direccion MAC del ESP32 
        self.direccion = puerto
        self.client = None
        self.buffer = queue.Queue()

        # BLE con bleak es asincrono; se corre un loop propio en un hilo
        # aparte para poder exponer metodos sincronos hacia afuera.
        self.loop = asyncio.new_event_loop()
        self.hilo = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.hilo.start()

    async def _escanear(self, timeout):
        dispositivos = await BleakScanner.discover(timeout=timeout)
        return [d.name for d in dispositivos if d.name]

    def listarDispositivosBLE(self, timeout=6.0):
        future = asyncio.run_coroutine_threadsafe(self._escanear(timeout), self.loop)
        return future.result(timeout=timeout + 5)

    def _callback_notificacion(self, sender, data):
        linea = data.decode('utf-8', errors='ignore').rstrip()
        self.buffer.put(linea)

    def _es_direccion_mac(self, texto):
        return texto.count(":") == 5

    async def _conectar(self):
        direccion_real = self.direccion

        if not self._es_direccion_mac(self.direccion):
            # Se asume que 'self.direccion' es un nombre, no una MAC
            dispositivos = await BleakScanner.discover(timeout=10.0)
            encontrado = None
            for d in dispositivos:
                if d.name == self.direccion:
                    encontrado = d
                    break
            if encontrado is None:
                raise RuntimeError(f"No se encontro el dispositivo BLE: {self.direccion}")
            direccion_real = encontrado.address

        self.client = BleakClient(direccion_real)
        await self.client.connect()
        await self.client.start_notify(CHARACTERISTIC_UUID_TX, self._callback_notificacion)

    def openConection(self):
        future = asyncio.run_coroutine_threadsafe(self._conectar(), self.loop)
        future.result(timeout=15)

    def catchSerial(self):
        if not self.buffer.empty():
            return self.buffer.get()
        return None

    async def _cerrar(self):
        if self.client and self.client.is_connected:
            await self.client.disconnect()

    def closeConection(self):
        future = asyncio.run_coroutine_threadsafe(self._cerrar(), self.loop)
        future.result(timeout=10)

    async def _enviar(self, data):
        await self.client.write_gatt_char(CHARACTERISTIC_UUID_RX, data.encode())

    def sendSignal(self, data):
        future = asyncio.run_coroutine_threadsafe(self._enviar(data), self.loop)
        future.result(timeout=5)

    def cleanBuffer(self):
        with self.buffer.mutex:
            self.buffer.queue.clear()