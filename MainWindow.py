import SerialCatcher
import tkinter as tk
from tkinter import ttk
import threading
import time
import math

try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    MATPLOTLIB_DISPONIBLE = True
except ImportError:
    MATPLOTLIB_DISPONIBLE = False


#=================================================
#              Paleta / estilo global
#=================================================
COLOR_FONDO        = "#f2f4f8"   # fondo general de las pantallas
COLOR_TARJETA       = "#ffffff"   # fondo de "tarjetas" (lectura, log, etc.)
COLOR_BARRA         = "#1f2733"   # barra superior de navegacion
COLOR_BARRA_HOVER    = "#2b3644"
COLOR_ACENTO        = "#3b82f6"   # azul de acento (activo/seleccionado)
COLOR_ACENTO_OSCURO  = "#2563eb"
COLOR_TEXTO         = "#1f2937"
COLOR_TEXTO_SUAVE    = "#6b7280"
COLOR_BORDE         = "#e2e5eb"
COLOR_OK            = "#16a34a"
COLOR_ERROR         = "#dc2626"

FUENTE = "Segoe UI"


#=================================================
#              Ventana de conexion
#=================================================
class VentanaConexion():
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Conectar")
        self.root.geometry("320x260")
        self.root.configure(bg=COLOR_FONDO)
        self.root.resizable(False, False)
        self.puerto = None

        estilo = ttk.Style(self.root)
        try:
            estilo.theme_use("clam")
        except tk.TclError:
            pass
        estilo.configure(
            "Conexion.TCombobox",
            fieldbackground=COLOR_TARJETA,
            background=COLOR_TARJETA,
            padding=6,
        )

        tarjeta = tk.Frame(self.root, bg=COLOR_TARJETA, highlightbackground=COLOR_BORDE,
                            highlightthickness=1)
        tarjeta.place(relx=0.5, rely=0.5, anchor="center", width=270, height=190)

        icono = tk.Label(tarjeta, text="ᛒ", font=(FUENTE, 28), bg=COLOR_TARJETA,
                          fg=COLOR_ACENTO)
        icono.pack(pady=(18, 4))

        titulo = tk.Label(tarjeta, text="Conectar Multimetro", font=(FUENTE, 12, "bold"),
                           bg=COLOR_TARJETA, fg=COLOR_TEXTO)
        titulo.pack(pady=(0, 14))

        label = tk.Label(tarjeta, text="Puerto COM / BLE:", font=(FUENTE, 9),
                          bg=COLOR_TARJETA, fg=COLOR_TEXTO_SUAVE)
        label.pack()

        self.campo_com = ttk.Combobox(tarjeta, width=18, style="Conexion.TCombobox")
        comports = list()
        tempCatcher = SerialCatcher.serialCatcher("NULL")
        for comport in tempCatcher.listarDispositivosBLE() :
            comports.append(comport)
        self.campo_com['values'] = comports
        self.campo_com.pack()

        boton = tk.Button(
            tarjeta, text="Conectar", command=self.conectar,
            font=(FUENTE, 10, "bold"), bg=COLOR_ACENTO, fg="white",
            activebackground=COLOR_ACENTO_OSCURO, activeforeground="white",
            relief="flat", bd=0, padx=18, pady=8, cursor="hand2"
        )
        boton.pack()

    def conectar(self):
        self.puerto = self.campo_com.get()
        self.root.destroy()

    def iniciar(self):
        self.root.mainloop()
        return self.puerto


#=================================================
#              Ventana principal
#=================================================
class MainWindow:
    

    # Orden en el que aparecen los botones arriba
    PANTALLAS = ["Voltaje", "Corriente", "Resistencia",
                 "Capacitancia", "Continuidad", "Frecuencia"]

    # Pantallas simples: lectura grande + log a la derecha
    PANTALLAS_SIMPLES = {
        "Voltaje": "V",
        "Corriente": "I",
    }

    # Pantallas con selector de rang
    PANTALLAS_RANGO = {
        "Resistencia": {"0 - 1k": "R1k", "1k - 10k": "R10k", "10k - 100k": "R100k",
                         "0 - 100": "R100"},
        "Capacitancia": {"0 - 1k": "C1k", "1k - 10k": "C10k", "10k - 100k": "C100k",
                          "0 - 100": "C100"},
    }

    # Iconos decorativos por pantalla 
    ICONOS = {
        "Voltaje": "⚡", "Corriente": "🔌", "Resistencia": "Ω",
        "Capacitancia": "=", "Continuidad": "---", "Frecuencia": "∿",
    }

    def __init__(self, puerto):
        self.root = tk.Tk()
        self.root.title("Monitor Multimetro")
        self.root.geometry("980x640")
        self.root.configure(bg=COLOR_FONDO)
        self.root.minsize(760, 520)

        self.estilo = ttk.Style(self.root)
        try:
            self.estilo.theme_use("clam")
        except tk.TclError:
            pass

        # --- Datos de conexion (el puerto se abre en segundo plano) ---
        self.puerto = puerto
        self.sc = None

        # --- Estado interno ---
        self.pantalla_actual = None
        self.rango_seleccionado = {}   # {"Resistencia": "0 - 1k", ...}

        # Widgets que se actualizan en vivo, guardados por nombre de pantalla
        self.lecturas = {}       # {"Voltaje": Label, ...}
        self.logs = {}           # {"Voltaje": Listbox, ...}
        self.botones_rango = {}  # {"Resistencia": {"0 - 1k": Button, ...}, ...}
        self.botones_nav = {}    # {"Voltaje": Button, ...} botones de la barra superior
        self.frames = {}

        self.detener_evento = threading.Event()
        self.root.protocol("WM_DELETE_WINDOW", self.cerrar)

        # --- Pantalla de carga mientras se conecta el dispositivo (BLE/Serial) ---
        self._mostrar_pantalla_carga()

        # La apertura del puerto (lo que tarda los 5-7 segundos) se hace en un
        # hilo aparte para que la ventana no se congele mientras conecta.
        self.hilo_conexion = threading.Thread(target=self._conectar_dispositivo, daemon=True)
        self.hilo_conexion.start()

    # -------------------------------------------------
    #   Pantalla de carga 
    # -------------------------------------------------
    def _mostrar_pantalla_carga(self):
        self.carga_frame = tk.Frame(self.root, bg=COLOR_FONDO)
        self.carga_frame.pack(fill="both", expand=True)

        tarjeta = self._tarjeta(self.carga_frame)
        tarjeta.place(relx=0.5, rely=0.5, anchor="center", width=340, height=210)

        tk.Label(tarjeta, text="ᛒ", font=(FUENTE, 30), bg=COLOR_TARJETA,
                 fg=COLOR_ACENTO).pack(pady=(30, 6))
        tk.Label(tarjeta, text="Conectando con el dispositivo...",
                 font=(FUENTE, 12, "bold"), bg=COLOR_TARJETA, fg=COLOR_TEXTO).pack(pady=(0, 4))
        tk.Label(tarjeta, text="Esto puede tardar unos segundos (Bluetooth)",
                 font=(FUENTE, 9), bg=COLOR_TARJETA, fg=COLOR_TEXTO_SUAVE).pack(pady=(0, 18))

        self.barra_progreso = ttk.Progressbar(tarjeta, mode="indeterminate", length=230)
        self.barra_progreso.pack()
        self.barra_progreso.start(12)

        # Ademas de la animacion, el cursor tambien indica "cargando"
        self.root.config(cursor="watch")

    def _ocultar_pantalla_carga(self):
        self.barra_progreso.stop()
        self.carga_frame.destroy()
        self.root.config(cursor="")

    # -------------------------------------------------
    #   Conexion en segundo plano
    # -------------------------------------------------
    def _conectar_dispositivo(self):
        error = None
        sc = None
        try:
            sc = SerialCatcher.serialCatcher(self.puerto, 9600)
            sc.openConection()
        except Exception as e:
            error = e

        # Volver al hilo principal de Tkinter para continuar con seguridad
        self.root.after(0, lambda: self._al_conectar(sc, error))

    def _al_conectar(self, sc, error):
        self._ocultar_pantalla_carga()

        if error is not None:
            print(f"Error conectando con el dispositivo: {error}")
            self._mostrar_error_conexion(error)
            return

        self.sc = sc
        self._construir_interfaz()

    def _mostrar_error_conexion(self, error):
        # Pantalla simple de erro con opcion de reintentar
        self.error_frame = tk.Frame(self.root, bg=COLOR_FONDO)
        self.error_frame.pack(fill="both", expand=True)

        tarjeta = self._tarjeta(self.error_frame)
        tarjeta.place(relx=0.5, rely=0.5, anchor="center", width=380, height=220)

        tk.Label(tarjeta, text="⚠", font=(FUENTE, 30), bg=COLOR_TARJETA,
                 fg=COLOR_ERROR).pack(pady=(30, 6))
        tk.Label(tarjeta, text="No se pudo conectar", font=(FUENTE, 12, "bold"),
                 bg=COLOR_TARJETA, fg=COLOR_TEXTO).pack(pady=(0, 4))
        tk.Label(tarjeta, text=str(error), font=(FUENTE, 9), bg=COLOR_TARJETA,
                 fg=COLOR_TEXTO_SUAVE, wraplength=320, justify="center").pack(pady=(0, 16))

        btn = tk.Button(
            tarjeta, text="Reintentar", font=(FUENTE, 10, "bold"),
            bg=COLOR_ACENTO, fg="white", activebackground=COLOR_ACENTO_OSCURO,
            activeforeground="white", relief="flat", bd=0, padx=16, pady=7,
            cursor="hand2", command=self._reintentar_conexion
        )
        btn.pack()

    def _reintentar_conexion(self):
        self.error_frame.destroy()
        self._mostrar_pantalla_carga()
        self.hilo_conexion = threading.Thread(target=self._conectar_dispositivo, daemon=True)
        self.hilo_conexion.start()

    # -------------------------------------------------
    #   Construccion de la interfaz principal
    # -------------------------------------------------
    def _construir_interfaz(self):
        # Barra de botones
        self.barra = tk.Frame(self.root, bg=COLOR_BARRA, height=56)
        self.barra.pack(side="top", fill="x")
        self.barra.pack_propagate(False)

        marca = tk.Label(self.barra, text="Monitor Multimetro", bg=COLOR_BARRA,
                          fg="white", font=(FUENTE, 11, "bold"))
        marca.pack(side="left", padx=16)

        self.contenedor_botones = tk.Frame(self.barra, bg=COLOR_BARRA)
        self.contenedor_botones.pack(side="left", padx=10)

        # Indicador de estado de conexion 
        self.indicador_estado = tk.Label(self.barra, text="Conectado", bg=COLOR_BARRA,
                                          fg=COLOR_OK, font=(FUENTE, 9, "bold"))
        self.indicador_estado.pack(side="right", padx=16)

        # Contenedor donde se apilan las pantallas
        self.contenedor = tk.Frame(self.root, bg=COLOR_FONDO)
        self.contenedor.pack(side="top", fill="both", expand=True)
        self.contenedor.grid_rowconfigure(0, weight=1)
        self.contenedor.grid_columnconfigure(0, weight=1)

        self._crear_botones()
        self._crear_pantallas()

        self.mostrar_pantalla("Voltaje")

        # Loop de lectura periodica del puerto serie
        # self.root.after(200, self._actualizar_serial)
        # daemon=True: si por alguna razon el hilo se queda atorado en una lectura
        # bloqueante, Python lo cierra de todos modos al terminar el programa.
        self.hilo = threading.Thread(target=self._actualizar_serial, daemon=True)
        self.hilo.start()

    # -------------------------------------------------
    #   Construccion de la barra superior
    # -------------------------------------------------
    def _crear_botones(self):
        for nombre in self.PANTALLAS:
            icono = self.ICONOS.get(nombre, "")
            btn = tk.Button(
                self.contenedor_botones,
                text=f"{icono}  {nombre}",
                relief="flat",
                bd=0,
                bg=COLOR_BARRA,
                fg="#c7ccd6",
                font=(FUENTE, 10),
                activebackground=COLOR_BARRA_HOVER,
                activeforeground="white",
                padx=14, pady=8,
                cursor="hand2",
                command=lambda n=nombre: self.mostrar_pantalla(n)
            )
            btn.pack(side="left", padx=3, pady=9)
            self.botones_nav[nombre] = btn

    def _resaltar_boton_nav(self, nombre):
        # Marca el boton de navegacion activo
        for n, btn in self.botones_nav.items():
            icono = self.ICONOS.get(n, "")
            if n == nombre:
                btn.config(bg=COLOR_ACENTO, fg="white", font=(FUENTE, 10, "bold"))
            else:
                btn.config(bg=COLOR_BARRA, fg="#c7ccd6", font=(FUENTE, 10))

    # -------------------------------------------------
    #   Construccion de pantallas
    # -------------------------------------------------
    def _crear_pantallas(self):
        for nombre in self.PANTALLAS:
            if nombre in self.PANTALLAS_SIMPLES:
                frame = self._crear_pantalla_simple(nombre)
            elif nombre in self.PANTALLAS_RANGO:
                frame = self._crear_pantalla_rango(nombre)
            elif nombre == "Continuidad":
                frame = self._crear_pantalla_continuidad()
            elif nombre == "Frecuencia":
                frame = self._crear_pantalla_frecuencia()
            else:
                frame = tk.Frame(self.contenedor, bg=COLOR_FONDO)

            frame.grid(row=0, column=0, sticky="nsew")
            self.frames[nombre] = frame

    def _tarjeta(self, parent):
        # Helper puramente visual: crea un frame tipo "tarjeta" con borde suave
        return tk.Frame(parent, bg=COLOR_TARJETA, highlightbackground=COLOR_BORDE,
                         highlightthickness=1)

    def _crear_pantalla_simple(self, nombre):
        #Lectura grande a la izquierda, log de mediciones a la derecha.
        frame = tk.Frame(self.contenedor, bg=COLOR_FONDO, padx=18, pady=18)
        frame.grid_columnconfigure(0, weight=3)
        frame.grid_columnconfigure(1, weight=1)
        frame.grid_rowconfigure(0, weight=1)

        tarjeta_lectura = self._tarjeta(frame)
        tarjeta_lectura.grid(row=0, column=0, sticky="nsew", padx=(0, 18))

        unidad = self.PANTALLAS_SIMPLES[nombre]
        tk.Label(tarjeta_lectura, text=f"{self.ICONOS.get(nombre,'')}  {nombre}",
                 font=(FUENTE, 13, "bold"), bg=COLOR_TARJETA, fg=COLOR_TEXTO_SUAVE
                 ).pack(anchor="nw", padx=24, pady=(20, 0))

        lectura = tk.Label(tarjeta_lectura, text="--", font=(FUENTE, 64, "bold"),
                            bg=COLOR_TARJETA, fg=COLOR_ACENTO)
        lectura.pack(expand=True)
        self.lecturas[nombre] = lectura

        tarjeta_log = self._tarjeta(frame)
        tarjeta_log.grid(row=0, column=1, sticky="nsew")
        tk.Label(tarjeta_log, text="Historial", font=(FUENTE, 10, "bold"),
                 bg=COLOR_TARJETA, fg=COLOR_TEXTO_SUAVE).pack(anchor="w", padx=12, pady=(10, 4))
        log_frame, log_listbox = self._crear_log(tarjeta_log)
        log_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.logs[nombre] = log_listbox

        return frame

    def _crear_pantalla_rango(self, nombre):
       #Botones de rango arriba izquierda, lectura grande centrada,
        #log de mediciones abajo izquierda.
        frame = tk.Frame(self.contenedor, bg=COLOR_FONDO, padx=18, pady=18)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_columnconfigure(1, weight=3)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        # Botones de rango
        tarjeta_rango = self._tarjeta(frame)
        tarjeta_rango.grid(row=0, column=0, sticky="nsew", padx=(0, 18), pady=(0, 18))
        tk.Label(tarjeta_rango, text="Rango", font=(FUENTE, 10, "bold"),
                 bg=COLOR_TARJETA, fg=COLOR_TEXTO_SUAVE).pack(anchor="w", padx=14, pady=(12, 6))

        self.botones_rango[nombre] = {}
        for etiqueta in self.PANTALLAS_RANGO[nombre]:
            btn = tk.Button(
                tarjeta_rango, text=etiqueta,
                font=(FUENTE, 10), relief="flat", bd=0, cursor="hand2",
                bg=COLOR_FONDO, fg=COLOR_TEXTO, activebackground=COLOR_BORDE,
                pady=8,
                command=lambda n=nombre, e=etiqueta: self._seleccionar_rango(n, e)
            )
            btn.pack(fill="x", padx=14, pady=4)
            self.botones_rango[nombre][etiqueta] = btn

        # Lectura grande 
        tarjeta_lectura = self._tarjeta(frame)
        tarjeta_lectura.grid(row=0, column=1, rowspan=2, sticky="nsew")
        tk.Label(tarjeta_lectura, text=f"{self.ICONOS.get(nombre,'')}  {nombre}",
                 font=(FUENTE, 13, "bold"), bg=COLOR_TARJETA, fg=COLOR_TEXTO_SUAVE
                 ).pack(anchor="nw", padx=24, pady=(20, 0))
        lectura = tk.Label(tarjeta_lectura, text="--", font=(FUENTE, 64, "bold"),
                            bg=COLOR_TARJETA, fg=COLOR_ACENTO)
        lectura.pack(expand=True)
        self.lecturas[nombre] = lectura

        # Log 
        tarjeta_log = self._tarjeta(frame)
        tarjeta_log.grid(row=1, column=0, sticky="nsew")
        tk.Label(tarjeta_log, text="Historial", font=(FUENTE, 10, "bold"),
                 bg=COLOR_TARJETA, fg=COLOR_TEXTO_SUAVE).pack(anchor="w", padx=12, pady=(10, 4))
        log_frame, log_listbox = self._crear_log(tarjeta_log)
        log_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.logs[nombre] = log_listbox

        return frame

    def _crear_pantalla_continuidad(self):
        #Solo un SI/NO gigante
        frame = tk.Frame(self.contenedor, bg=COLOR_FONDO, padx=18, pady=18)
        tarjeta = self._tarjeta(frame)
        tarjeta.pack(fill="both", expand=True)
        tk.Label(tarjeta, text=f"{self.ICONOS.get('Continuidad','')}  Continuidad",
                 font=(FUENTE, 13, "bold"), bg=COLOR_TARJETA, fg=COLOR_TEXTO_SUAVE
                 ).pack(anchor="n", pady=(20, 0))
        lectura = tk.Label(tarjeta, text="--", font=(FUENTE, 140, "bold"), bg=COLOR_TARJETA,
                            fg=COLOR_TEXTO_SUAVE)
        lectura.pack(expand=True)
        self.lecturas["Continuidad"] = lectura
        return frame

    def _crear_pantalla_frecuencia(self):
        frame = tk.Frame(self.contenedor, bg=COLOR_FONDO, padx=18, pady=18)
        frame.grid_rowconfigure(0, weight=3)
        frame.grid_rowconfigure(1, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        tarjeta_grafico = self._tarjeta(frame)
        tarjeta_grafico.grid(row=0, column=0, sticky="nsew", pady=(0, 18))
        tarjeta_grafico.grid_rowconfigure(0, weight=1)
        tarjeta_grafico.grid_columnconfigure(0, weight=1)

        if MATPLOTLIB_DISPONIBLE:
            # --- Onda simulada (no muestreada), basada en tiempo real ---
            # La ventana de tiempo mostrada es FIJA (como la base de tiempo de
            # un osciloscopio). Conforme la frecuencia real sube, entran mas
            # ciclos completos dentro de esa misma ventana -- no hay que
            # decirle "cuantos ciclos mostrar", sale solo de la frecuencia.
            # La forma es cuadrada, con la MISMA amplitud/centro que midio el
            # Arduino (pico a pico / 2 y punto medio). Es pura matematica, no
            # una muestra real, por eso siempre sale limpia sin importar que
            # tan alta sea la frecuencia.
            self.VENTANA_TIEMPO_S = 0.02   # ventana de tiempo mostrada (20 ms)

            self.RESOLUCION_MIN = 50
            self.RESOLUCION_MAX = 4000
            self.RESOLUCION_PASO = 50
            self.RESOLUCION = 500          # puntos totales dibujados en la ventana

            self._frecuencia_hz_actual = 0.0
            self._intensidad_actual = 0.0
            self._centro_actual = 0.0

            tarjeta_grafico.grid_rowconfigure(1, weight=0)

            fig = Figure(figsize=(5, 3), dpi=100, facecolor=COLOR_TARJETA)
            ax = fig.add_subplot(111)
            ax.set_facecolor(COLOR_TARJETA)
            ax.set_title("Onda cuadrada (simulada)", color=COLOR_TEXTO)

            # Solo se muestra la forma de la señal, sin numeros en los ejes
            ax.set_xticks([])
            ax.set_yticks([])
            for spine in ax.spines.values():
                spine.set_color(COLOR_BORDE)

            x_inicial, y_inicial = self._generar_onda(0.0, 0.0, 0.0)
            (self.linea_intensidad,) = ax.plot(
                x_inicial, y_inicial, color=COLOR_ACENTO, linewidth=2
            )
            ax.set_xlim(0, self.VENTANA_TIEMPO_S)
            ax.set_ylim(-1, 1)

            self.ax_frecuencia = ax
            self.fig_frecuencia = fig

            canvas = FigureCanvasTkAgg(fig, master=tarjeta_grafico)
            canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew", padx=14, pady=14)
            self.canvas_frecuencia = canvas

            # --- Controles para ajustar la resolucion (puntos en la ventana) ---
            controles = tk.Frame(tarjeta_grafico, bg=COLOR_TARJETA)
            controles.grid(row=1, column=0, pady=(0, 10))

            self.btn_puntos_menos = tk.Button(
                controles, text="-", font=(FUENTE, 12, "bold"), width=3,
                bg=COLOR_FONDO, fg=COLOR_TEXTO, relief="flat", bd=0, cursor="hand2",
                activebackground=COLOR_BORDE,
                command=lambda: self._cambiar_resolucion_grafica(-self.RESOLUCION_PASO)
            )
            self.btn_puntos_menos.pack(side="left", padx=4)

            self.label_puntos = tk.Label(
                controles, text=f"Resolución: {self.RESOLUCION}", width=14,
                font=(FUENTE, 9), bg=COLOR_TARJETA, fg=COLOR_TEXTO_SUAVE
            )
            self.label_puntos.pack(side="left", padx=4)

            self.btn_puntos_mas = tk.Button(
                controles, text="+", font=(FUENTE, 12, "bold"), width=3,
                bg=COLOR_FONDO, fg=COLOR_TEXTO, relief="flat", bd=0, cursor="hand2",
                activebackground=COLOR_BORDE,
                command=lambda: self._cambiar_resolucion_grafica(self.RESOLUCION_PASO)
            )
            self.btn_puntos_mas.pack(side="left", padx=4)
        else:
            tk.Label(tarjeta_grafico, text="matplotlib no disponible",
                     font=(FUENTE, 16), bg=COLOR_TARJETA, fg=COLOR_TEXTO_SUAVE
                     ).grid(row=0, column=0, sticky="nsew")

        info_frame = self._tarjeta(frame)
        info_frame.grid(row=1, column=0, sticky="nsew")
        info_frame.grid_columnconfigure((0, 1, 2), weight=1)

        self.label_frecuencia = tk.Label(info_frame, text="Frecuencia: -- Hz",
                                          font=(FUENTE, 15, "bold"), bg=COLOR_TARJETA,
                                          fg=COLOR_ACENTO)
        self.label_frecuencia.grid(row=0, column=0, pady=18)

        self.label_periodo = tk.Label(info_frame, text="Periodo: -- s",
                                       font=(FUENTE, 15, "bold"), bg=COLOR_TARJETA,
                                       fg=COLOR_ACENTO)
        self.label_periodo.grid(row=0, column=1, pady=18)

        self.label_rms = tk.Label(info_frame, text="RMS: -- V",
                                   font=(FUENTE, 15, "bold"), bg=COLOR_TARJETA,
                                   fg=COLOR_ACENTO)
        self.label_rms.grid(row=0, column=2, pady=18)

        return frame

    def _crear_log(self, parent):
        #Crea un Listbox con scrollbar para mostrar mediciones pasadas"
        log_frame = tk.Frame(parent, bg=COLOR_TARJETA)
        scrollbar = tk.Scrollbar(log_frame)
        scrollbar.pack(side="right", fill="y")

        listbox = tk.Listbox(
            log_frame, yscrollcommand=scrollbar.set,
            font=(FUENTE, 10), bd=0, highlightthickness=0,
            bg=COLOR_TARJETA, fg=COLOR_TEXTO,
            selectbackground=COLOR_ACENTO, selectforeground="white",
            activestyle="none",
        )
        listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=listbox.yview)

        return log_frame, listbox

    # ================================================
    #   Cambio de pantalla / rango
    # =================================================
    def mostrar_pantalla(self, nombre):
        self.sc.cleanBuffer()
        self.pantalla_actual = nombre
        self.frames[nombre].tkraise()
        self._resaltar_boton_nav(nombre)

        if nombre in self.PANTALLAS_SIMPLES:
            self._enviar_comando(self.PANTALLAS_SIMPLES[nombre])

        elif nombre in self.PANTALLAS_RANGO:
            # Si ya se habia elegido un rango antes, se mantiene; si no, se usa el primero
            rango_actual = self.rango_seleccionado.get(
                nombre, list(self.PANTALLAS_RANGO[nombre].keys())[0]
            )
            self._seleccionar_rango(nombre, rango_actual)

        elif nombre == "Continuidad":
            self._enviar_comando("CON")

        elif nombre == "Frecuencia":
            self._enviar_comando("FRE")
            pass

    def _seleccionar_rango(self, nombre, etiqueta):
        self.rango_seleccionado[nombre] = etiqueta
        comando = self.PANTALLAS_RANGO[nombre][etiqueta]
        self._enviar_comando(comando)

        # Resaltar visualmente el boton de rango activo
        for e, btn in self.botones_rango[nombre].items():
            if e == etiqueta:
                btn.config(bg=COLOR_ACENTO, fg="white", font=(FUENTE, 10, "bold"))
            else:
                btn.config(bg=COLOR_FONDO, fg=COLOR_TEXTO, font=(FUENTE, 10))

    def _enviar_comando(self, codigo):
        try:
            self.sc.sendSignal(f"MOD:{codigo}")
        except Exception as e:
            print(f"Error enviando comando MOD:{codigo} -> {e}")

    #=================================================
    #   Lectura periodica del puerto serie
    #=================================================
    def _actualizar_serial(self):
        while not self.detener_evento.is_set():
            try:
                dato = self.sc.catchSerial()
            except Exception as e:
                dato = None
                print(f"Error leyendo puerto serie: {e}")
    
            if dato is not None and self.pantalla_actual:
                self._procesar_dato(self.pantalla_actual, dato)
                
    
            #time.sleep(100)

    def _generar_onda(self, frecuencia_hz, amplitud, centro=0.0):
        # Genera (x, y) de una onda CUADRADA ideal dentro de una ventana de
        # TIEMPO fija (self.VENTANA_TIEMPO_S) -- como la base de tiempo de un
        # osciloscopio. A mas frecuencia real, mas ciclos completos entran en
        # esa misma ventana, sin necesidad de decirselo a mano. La resolucion
        # (self.RESOLUCION) es cuantos puntos se usan para dibujar esa ventana:
        # mas puntos = flancos mas nitidos, sobre todo con muchos ciclos
        # apretados (frecuencias altas). Es pura matematica, no una muestra
        # real, por eso siempre sale limpia sin importar la frecuencia real.
        total_puntos = max(self.RESOLUCION, 2)
        paso = self.VENTANA_TIEMPO_S / (total_puntos - 1)
        x = [i * paso for i in range(total_puntos)]

        if frecuencia_hz > 0:
            y = [
                centro + (amplitud if math.sin(2 * math.pi * frecuencia_hz * xi) >= 0 else -amplitud)
                for xi in x
            ]
        else:
            y = [centro] * total_puntos  # sin frecuencia valida: linea plana en el centro

        return x, y

    def _dibujar_onda(self):
        x, y = self._generar_onda(self._frecuencia_hz_actual, self._intensidad_actual, self._centro_actual)

        self.linea_intensidad.set_xdata(x)
        self.linea_intensidad.set_ydata(y)
        self.ax_frecuencia.set_xlim(0, self.VENTANA_TIEMPO_S)

        amplitud_abs = abs(self._intensidad_actual)
        margen = amplitud_abs * 0.15 if amplitud_abs > 0 else 1
        self.ax_frecuencia.set_ylim(
            self._centro_actual - amplitud_abs - margen,
            self._centro_actual + amplitud_abs + margen
        )

        self.canvas_frecuencia.draw_idle()

    def _actualizar_grafica_intensidad(self, amplitud, centro=0.0):
        # Ya no se grafica la muestra cruda: solo se guarda la amplitud y el
        # centro (pico a pico / 2 y punto medio, medidos en el Arduino) y se
        # redibuja la onda simulada (la frecuencia se actualiza aparte, ver
        # el bloque de "Frecuencia" en _procesar_dato).
        self._intensidad_actual = amplitud
        self._centro_actual = centro
        self._dibujar_onda()

    def _cambiar_resolucion_grafica(self, delta):
        # Cambia cuantos puntos se usan para dibujar la ventana de tiempo.
        # Mas resolucion = flancos mas limpios, especialmente util cuando la
        # frecuencia sube y entran muchos ciclos en la misma ventana.
        nuevo = self.RESOLUCION + delta
        nuevo = max(self.RESOLUCION_MIN, min(self.RESOLUCION_MAX, nuevo))
        if nuevo == self.RESOLUCION:
            return  # ya esta en el limite

        self.RESOLUCION = nuevo
        self.label_puntos.config(text=f"Resolución: {nuevo}")
        self.btn_puntos_menos.config(state="normal" if nuevo > self.RESOLUCION_MIN else "disabled")
        self.btn_puntos_mas.config(state="normal" if nuevo < self.RESOLUCION_MAX else "disabled")

        self._dibujar_onda()

    def _procesar_dato(self, pantalla, dato):
        texto = str(dato)
        
        if pantalla == "Continuidad":
            
            es_continuo = texto.strip().upper() in ("1", "SI", "OK", "TRUE")
            self.lecturas["Continuidad"].config(
                text="SI" if es_continuo else "NO",
                fg=COLOR_OK if es_continuo else COLOR_ERROR
            )
            return

        if pantalla == "Frecuencia":
            # Formato esperado: "1234.56 Hz, 1234.0, 2048.0"
            #                    frecuencia , amplitud (pico a pico / 2) , centro
            partes = texto.split(",")

            # --- Frecuencia ---
            FACTORES_UNIDAD = {"Hz": 1, "kHz": 1_000, "MHz": 1_000_000}
            try:
                texto_frecuencia = partes[0].strip()
                self.label_frecuencia.config(text=f"Frecuencia: {texto_frecuencia}")

                valor_str, unidad = texto_frecuencia.split()
                factor = FACTORES_UNIDAD.get(unidad, 1)  # unidad desconocida -> asume Hz
                frecuencia_hz = float(valor_str) * factor

                if MATPLOTLIB_DISPONIBLE:
                    self._frecuencia_hz_actual = frecuencia_hz  # usado por la onda simulada

                if frecuencia_hz > 0:
                    periodo = 1.0 / frecuencia_hz
                    self.label_periodo.config(text=f"Periodo: {periodo*1000:.3f} ms")
                else:
                    self.label_periodo.config(text="Periodo: -- s")
            except (ValueError, IndexError):
                pass  # linea con formato inesperado, se ignora sin tronar

            # --- Amplitud (pico a pico / 2) y centro de la onda ---
            if len(partes) > 1 and MATPLOTLIB_DISPONIBLE:
                try:
                    amplitud = float(partes[1])
                    centro = float(partes[2]) if len(partes) > 2 else 0.0
                    self._actualizar_grafica_intensidad(amplitud, centro)
                except ValueError:
                    pass

            return

        # Voltaje, Corriente, Resistencia, Capacitancia
        if pantalla in self.lecturas:
            self.lecturas[pantalla].config(text=texto)

        if pantalla in self.logs:
            self.logs[pantalla].insert(0, f"{texto}")
            # Limitar el log a las ultimas 50 entradas
            if self.logs[pantalla].size() > 50:
                self.logs[pantalla].delete(50, tk.END)

    # =================================================
    #   Cierre
    # =================================================
    def cerrar(self):
        # Avisa al hilo de lectura que debe parar y le da un momento para salir
        self.detener_evento.set()
        if hasattr(self, "hilo") and self.hilo.is_alive():
            self.hilo.join(timeout=1.0)
        try:
            if self.sc is not None:
                self.sc.closeConection()
        except Exception as e:
            print(f"Error cerrando puerto: {e}")
        self.root.destroy()
        

    def iniciar(self):
        self.root.mainloop()


#===================================================
#                   Principal
#===================================================
if __name__ == "__main__":
    config = VentanaConexion()
    compuerta = config.iniciar()

    if compuerta:
        app = MainWindow(compuerta)
        app.iniciar()