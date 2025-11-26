import os  
from flask import Flask, jsonify, request, send_file, render_template_string
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from datetime import datetime
import hashlib
import qrcode
from io import BytesIO
import socket
from flask import Flask, jsonify, request, send_file, render_template_string, redirect
app = Flask(__name__)

# ✅ CONFIGURACIÓN SQLite
basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(basedir, 'parqueadero.db')

if os.path.exists(db_path):
    try:
        app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{db_path}"
    except:
        os.remove(db_path)
        app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{db_path}"
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{db_path}"

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# MODELOS
class Usuario(db.Model):
    __tablename__ = "USUARIO"
    ID = db.Column(db.Integer, primary_key=True)
    NOMBRE = db.Column(db.String, nullable=False)
    CEDULA = db.Column(db.String(20), unique=True, nullable=False)
    SALDO = db.Column(db.Numeric(10,2), default=0.0)
    TELEFONO = db.Column(db.String(15))
    EMAIL = db.Column(db.String(100))
    FECHA_REGISTRO = db.Column(db.DateTime, default=datetime.utcnow)
    TARJETA_RFID = db.Column(db.String(20), unique=True)

    vehiculos = db.relationship("Vehiculo", back_populates="usuario", lazy=True)
    transacciones = db.relationship("Transaccion", back_populates="usuario", lazy=True)
    entradas = db.relationship("Entrada", back_populates="usuario", lazy=True)

class Vehiculo(db.Model):
    __tablename__ = "VEHICULO"
    ID = db.Column(db.Integer, primary_key=True)
    PLACA = db.Column(db.String(10), unique=True, nullable=False)
    TIPO = db.Column(db.String(20), default="CARRO")
    ID_USUARIO = db.Column(db.Integer, db.ForeignKey('USUARIO.ID'), nullable=False)
    COLOR = db.Column(db.String(20))
    MARCA = db.Column(db.String(30))

    usuario = db.relationship("Usuario", back_populates="vehiculos", lazy=True)

class Transaccion(db.Model):
    __tablename__ = "TRANSACCION"
    ID = db.Column(db.Integer, primary_key=True)
    ID_USUARIO = db.Column(db.Integer, db.ForeignKey('USUARIO.ID'), nullable=True)
    TIPO = db.Column(db.String(20), nullable=False)
    MONTO = db.Column(db.Numeric(10,2), default=0.0)
    ESTADO = db.Column(db.String(20), default="PENDIENTE")
    FECHA = db.Column(db.DateTime, default=datetime.utcnow)
    TOKEN = db.Column(db.String(50), unique=True)
    TARJETA_RFID = db.Column(db.String(20))

    usuario = db.relationship("Usuario", back_populates="transacciones", lazy=True)

class Tarifa(db.Model):
    __tablename__ = "TARIFA"
    ID = db.Column(db.Integer, primary_key=True)
    TIPO_VEHICULO = db.Column(db.String(20), nullable=False)
    TARIFA_HORA = db.Column(db.Numeric(10,2), nullable=False)
    TARIFA_MINIMA = db.Column(db.Numeric(10,2), default=0.0)
    ACTIVA = db.Column(db.Boolean, default=True)

# 🆕 AGREGAR ESTOS CAMPOS AL MODELO ESPACIO
class Espacio(db.Model):
    __tablename__ = "ESPACIO"
    ID = db.Column(db.Integer, primary_key=True)
    NUMERO = db.Column(db.String(10), unique=True, nullable=False)
    TIPO_VEHICULO = db.Column(db.String(20), default="CARRO")
    ESTADO = db.Column(db.String(20), default="DISPONIBLE")  # DISPONIBLE, OCUPADO, MANTENIMIENTO
    ID_ENTRADA_ACTUAL = db.Column(db.Integer, db.ForeignKey('ENTRADA.ID'), nullable=True)
    SENSOR_PIN = db.Column(db.Integer, nullable=False)  # 🆕 PIN del sensor (1, 2, 3)
    ULTIMA_DETECCION = db.Column(db.DateTime, nullable=True)  # 🆕 Última vez que el sensor detectó algo

# 🆕 AGREGAR MÁS CAMPOS A ENTRADA PARA FACTURACIÓN
class Entrada(db.Model):
    __tablename__ = "ENTRADA"
    ID = db.Column(db.Integer, primary_key=True)
    ID_USUARIO = db.Column(db.Integer, db.ForeignKey('USUARIO.ID'), nullable=False)
    ID_VEHICULO = db.Column(db.Integer, db.ForeignKey('VEHICULO.ID'), nullable=False)
    ID_ESPACIO = db.Column(db.Integer, db.ForeignKey('ESPACIO.ID'), nullable=True)
    FECHA_ENTRADA = db.Column(db.DateTime, default=datetime.utcnow)
    FECHA_SALIDA = db.Column(db.DateTime, nullable=True)
    ESTADO = db.Column(db.String(20), default="ACTIVA")
    MONTO_COBRADO = db.Column(db.Numeric(10,2), nullable=True)
    TIEMPO_ESTACIONADO = db.Column(db.String(20), nullable=True)  # 🆕 Para factura
    FACTURA_GENERADA = db.Column(db.Boolean, default=False)  # 🆕 Si ya se generó factura

    espacio = db.relationship("Espacio", foreign_keys=[ID_ESPACIO], backref="entradas_activas", lazy=True)
    usuario = db.relationship("Usuario", foreign_keys=[ID_USUARIO], back_populates="entradas", lazy=True)
    vehiculo = db.relationship("Vehiculo", foreign_keys=[ID_VEHICULO], backref="entradas", lazy=True)
# HELPER FUNCTIONS
def generar_token():
    return hashlib.md5(datetime.utcnow().isoformat().encode()).hexdigest()[:20]

def obtener_ip_servidor():
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        return local_ip
    except:
        return "192.168.1.3"

def obtener_tarifa_minima():
    tarifa = Tarifa.query.filter_by(TIPO_VEHICULO="CARRO", ACTIVA=True).first()
    return float(tarifa.TARIFA_MINIMA) if tarifa else 2000.0

# ENDPOINTS PRINCIPALES
@app.route("/")
def index():
    return jsonify({"mensaje": "Sistema de Parqueadero Inteligente", "version": "4.1"})

# 🆕 ENDPOINT MEJORADO PARA SALIDA CON FACTURA
@app.route("/api/salida/detectar", methods=["POST"])
def detectar_salida():
    """Procesa la salida de un vehículo y genera factura"""
    try:
        data = request.get_json() or {}
        tarjeta_rfid = data.get("tarjeta_rfid", "").strip().upper()
        
        if not tarjeta_rfid:
            return jsonify({"error": "Tarjeta RFID requerida"}), 400
        
        print(f"🚗 SALIDA detectada - Tarjeta RFID: {tarjeta_rfid}")
        
        # Buscar usuario
        usuario = Usuario.query.filter_by(TARJETA_RFID=tarjeta_rfid).first()
        if not usuario:
            return jsonify({"error": "Usuario no encontrado"}), 404
        
        # Buscar entrada activa
        entrada_activa = Entrada.query.filter_by(
            ID_USUARIO=usuario.ID, 
            ESTADO="ACTIVA"
        ).first()
        
        if not entrada_activa:
            return jsonify({"error": "No tiene entrada activa"}), 400
        
        # Calcular tiempo y monto
        tiempo_estacionado = datetime.utcnow() - entrada_activa.FECHA_ENTRADA
        horas = max(1, tiempo_estacionado.total_seconds() / 3600)
        
        vehiculo = Vehiculo.query.get(entrada_activa.ID_VEHICULO)
        tarifa = Tarifa.query.filter_by(TIPO_VEHICULO=vehiculo.TIPO, ACTIVA=True).first()
        
        if tarifa:
            monto_cobrar = float(tarifa.TARIFA_HORA) * horas
            monto_cobrar = max(monto_cobrar, float(tarifa.TARIFA_MINIMA))
        else:
            monto_cobrar = 2000.0
        
        # Verificar saldo suficiente
        if float(usuario.SALDO) < monto_cobrar:
            return jsonify({
                "accion": "SALDO_INSUFICIENTE_SALIDA",
                "mensaje": "Saldo insuficiente para pagar estacionamiento",
                "monto_requerido": monto_cobrar,
                "saldo_actual": float(usuario.SALDO),
                "comando": "MOSTRAR_ALERTA"
            }), 200
        
        # Cobrar y finalizar entrada
        usuario.SALDO = float(usuario.SALDO) - monto_cobrar
        entrada_activa.FECHA_SALIDA = datetime.utcnow()
        entrada_activa.ESTADO = "FINALIZADA"
        entrada_activa.MONTO_COBRADO = monto_cobrar
        entrada_activa.TIEMPO_ESTACIONADO = str(tiempo_estacionado).split('.')[0]
        
        # Liberar espacio
        if entrada_activa.espacio:
            entrada_activa.espacio.ESTADO = "DISPONIBLE"
            entrada_activa.espacio.ID_ENTRADA_ACTUAL = None
        
        db.session.commit()
        
        print(f"✅ SALIDA EXITOSA - Usuario: {usuario.NOMBRE}, Monto: {monto_cobrar}")
        
        factura_url = f"http://{obtener_ip_servidor()}:5000/api/factura/generar/{entrada_activa.ID}"
        
        return jsonify({
            "accion": "SALIDA_PERMITIDA",
            "mensaje": "Salida exitosa",
            "usuario": usuario.NOMBRE,
            "tiempo_estacionado": str(tiempo_estacionado),
            "monto_cobrado": monto_cobrar,
            "nuevo_saldo": float(usuario.SALDO),
            "factura_url": factura_url,  # 🆕 URL de la factura
            "comando": "ABRIR_BARRERA"
        }), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error en salida: {str(e)}")
        return jsonify({"error": f"Error en el servidor: {str(e)}"}), 500
# ✅ ENDPOINT DE ENTRADA MEJORADO CON ESPACIOS
# ✅ ENDPOINT SIMPLIFICADO DE ENTRADA - SIEMPRE RESPONDE Y REGISTRA
# 🆕 MODIFICAR EL ENDPOINT DE ENTRADA PARA USAR PLACA
# ✅ CORREGIR ENDPOINT DE ENTRADA - VERIFICAR ESPACIOS ANTES DE ABRIR BARRERA
@app.route("/api/entrada/detectar", methods=["POST"])
def detectar_entrada():
    """Paso 1: Verifica estado y luego decide si abre barrera"""
    try:
        data = request.get_json() or {}
        tarjeta_rfid = data.get("tarjeta_rfid", "").strip().upper()
        
        if not tarjeta_rfid:
            return jsonify({"error": "Tarjeta RFID requerida"}), 400
        
        print(f"🚗 Vehículo detectado - Tarjeta RFID: {tarjeta_rfid}")
        
        # ✅ 1. BUSCAR USUARIO EN BASE DE DATOS
        usuario = Usuario.query.filter_by(TARJETA_RFID=tarjeta_rfid).first()
        
        if usuario:
            # Usuario existe - verificar saldo
            saldo_actual = float(usuario.SALDO) if usuario.SALDO else 0.0
            tarifa_minima = obtener_tarifa_minima()
            
            print(f"👤 Usuario: {usuario.NOMBRE}")
            print(f"💰 Saldo actual: {saldo_actual}")
            print(f"🎯 Mínimo requerido: {tarifa_minima}")
            
            # ✅ VERIFICAR SI YA TIENE ENTRADA ACTIVA
            entrada_activa = Entrada.query.filter_by(
                ID_USUARIO=usuario.ID, 
                ESTADO="ACTIVA"
            ).first()
            
            if entrada_activa:
                return jsonify({
                    "accion": "ENTRADA_DUPLICADA",
                    "mensaje": "Ya tiene una entrada activa",
                    "usuario": usuario.NOMBRE,
                    "placa": entrada_activa.vehiculo.PLACA,
                    "comando": "MOSTRAR_ALERTA"
                }), 200
            
            # ✅ VERIFICAR SALDO SUFICIENTE
            if saldo_actual < tarifa_minima:
                return jsonify({
                    "accion": "SALDO_INSUFICIENTE",
                    "mensaje": "Saldo insuficiente. Recargue para ingresar",
                    "usuario": usuario.NOMBRE,
                    "placa": usuario.vehiculos[0].PLACA if usuario.vehiculos else "SIN PLACA",
                    "saldo_actual": saldo_actual,
                    "saldo_minimo": tarifa_minima,
                    "comando": "MOSTRAR_ALERTA"
                }), 200
            
            # ✅ BUSCAR ESPACIO DISPONIBLE ANTES DE PERMITIR ENTRADA
            vehiculo = Vehiculo.query.filter_by(ID_USUARIO=usuario.ID).first()
            if not vehiculo:
                return jsonify({"error": "No tiene vehículo registrado"}), 400
            
            espacio_disponible = Espacio.query.filter_by(
                TIPO_VEHICULO=vehiculo.TIPO,
                ESTADO="DISPONIBLE"
            ).first()
            
            if not espacio_disponible:
                return jsonify({
                    "accion": "NO_HAY_ESPACIOS",
                    "mensaje": "No hay espacios disponibles",
                    "usuario": usuario.NOMBRE,
                    "placa": vehiculo.PLACA,
                    "comando": "MOSTRAR_ALERTA"
                }), 200
            
            # ✅ CREAR ENTRADA Y ASIGNAR ESPACIO (PARA PRIMERA VEZ Y SIGUIENTES)
            entrada = Entrada(
                ID_USUARIO=usuario.ID,
                ID_VEHICULO=vehiculo.ID,
                ID_ESPACIO=espacio_disponible.ID,
                ESTADO="ACTIVA"
            )
            db.session.add(entrada)
            db.session.flush()  # Para obtener el ID de la entrada
            
            # ✅ OCUPAR ESPACIO
            espacio_disponible.ESTADO = "OCUPADO"
            espacio_disponible.ID_ENTRADA_ACTUAL = entrada.ID
            
            db.session.commit()
            
            print(f"🎉 ENTRADA REGISTRADA - {usuario.NOMBRE} - {vehiculo.PLACA}")
            print(f"📍 Espacio asignado: {espacio_disponible.NUMERO}")
            
            return jsonify({
                "accion": "ENTRADA_PERMITIDA",
                "mensaje": f"Bienvenido, espacio {espacio_disponible.NUMERO} asignado",
                "usuario": usuario.NOMBRE,
                "placa": vehiculo.PLACA,
                "espacio": espacio_disponible.NUMERO,
                "saldo_actual": saldo_actual,
                "comando": "ABRIR_BARRERA"
            }), 200
        else:
            # ✅ USUARIO NUEVO - VERIFICAR SI HAY ESPACIOS ANTES DE GENERAR QR
            espacio_disponible = Espacio.query.filter_by(
                TIPO_VEHICULO="CARRO",  # Asumimos carro para usuario nuevo
                ESTADO="DISPONIBLE"
            ).first()
            
            if not espacio_disponible:
                return jsonify({
                    "accion": "NO_HAY_ESPACIOS_NUEVO",
                    "mensaje": "No hay espacios disponibles para registro",
                    "comando": "MOSTRAR_ALERTA"
                }), 200
            
            # ✅ HAY ESPACIO - GENERAR QR REGISTRO
            Transaccion.query.filter_by(TARJETA_RFID=tarjeta_rfid, TIPO="REGISTRO", ESTADO="PENDIENTE").delete()
            
            token_registro = generar_token()
            transaccion = Transaccion(
                TIPO="REGISTRO",
                ESTADO="PENDIENTE",
                TOKEN=token_registro,
                TARJETA_RFID=tarjeta_rfid
            )
            db.session.add(transaccion)
            db.session.commit()
            
            ip_servidor = obtener_ip_servidor()
            url_registro = f"http://{ip_servidor}:5000/registro/{token_registro}"
            
            print(f"👤 USUARIO NUEVO - Generando registro")
            print(f"📱 URL Registro: {url_registro}")
            
            return jsonify({
                "accion": "USUARIO_NUEVO", 
                "mensaje": "Usuario no registrado. Complete el registro",
                "tarjeta_rfid": tarjeta_rfid,
                "token_registro": token_registro,
                "url_registro": url_registro,
                "comando": "ABRIR_BARRERA"  # 🆕 PERMITE ENTRADA PARA REGISTRO
            }), 200
            
    except Exception as e:
        print(f"❌ Error en detección: {str(e)}")
        return jsonify({"error": f"Error en el servidor: {str(e)}"}), 500
import pandas as pd
from io import BytesIO
from datetime import datetime, date
from flask import send_file

# 🆕 ENDPOINT PARA GENERAR REPORTE DIARIO EN EXCEL
@app.route("/api/reportes/diario/excel")
def generar_reporte_diario_excel():
    """Genera un reporte Excel con la actividad del día"""
    try:
        # Obtener fecha actual
        hoy = date.today()
        fecha_str = hoy.strftime("%Y-%m-%d")
        nombre_archivo = f"reporte_parqueadero_{fecha_str}.xlsx"
        
        # Crear un escritor de Excel en memoria
        output = BytesIO()
        
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            # 🟢 HOJA 1: RESUMEN GENERAL
            resumen_data = generar_resumen_diario(hoy)
            df_resumen = pd.DataFrame([resumen_data])
            df_resumen.to_excel(writer, sheet_name='Resumen General', index=False)
            
            # 🟢 HOJA 2: ENTRADAS Y SALIDAS DEL DÍA
            entradas_data = generar_entradas_dia(hoy)
            if entradas_data:
                df_entradas = pd.DataFrame(entradas_data)
                df_entradas.to_excel(writer, sheet_name='Entradas y Salidas', index=False)
            else:
                pd.DataFrame([{"Mensaje": "No hay actividad hoy"}]).to_excel(
                    writer, sheet_name='Entradas y Salidas', index=False)
            
            # 🟢 HOJA 3: RECARGAS DEL DÍA
            recargas_data = generar_recargas_dia(hoy)
            if recargas_data:
                df_recargas = pd.DataFrame(recargas_data)
                df_recargas.to_excel(writer, sheet_name='Recargas', index=False)
            else:
                pd.DataFrame([{"Mensaje": "No hay recargas hoy"}]).to_excel(
                    writer, sheet_name='Recargas', index=False)
            
            # 🟢 HOJA 4: ESTADO ACTUAL DE ESPACIOS
            espacios_data = generar_estado_espacios()
            df_espacios = pd.DataFrame(espacios_data)
            df_espacios.to_excel(writer, sheet_name='Espacios Actuales', index=False)
            
            # 🟢 HOJA 5: FACTURACIÓN DEL DÍA
            facturas_data = generar_facturas_dia(hoy)
            if facturas_data:
                df_facturas = pd.DataFrame(facturas_data)
                df_facturas.to_excel(writer, sheet_name='Facturación', index=False)
            else:
                pd.DataFrame([{"Mensaje": "No hay facturas hoy"}]).to_excel(
                    writer, sheet_name='Facturación', index=False)
            
            # 🟢 HOJA 6: USUARIOS NUEVOS
            usuarios_nuevos_data = generar_usuarios_nuevos(hoy)
            if usuarios_nuevos_data:
                df_usuarios = pd.DataFrame(usuarios_nuevos_data)
                df_usuarios.to_excel(writer, sheet_name='Usuarios Nuevos', index=False)
            else:
                pd.DataFrame([{"Mensaje": "No hay usuarios nuevos hoy"}]).to_excel(
                    writer, sheet_name='Usuarios Nuevos', index=False)
        
        output.seek(0)
        
        print(f"📊 Reporte diario generado: {nombre_archivo}")
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=nombre_archivo
        )
        
    except Exception as e:
        print(f"❌ Error generando reporte Excel: {str(e)}")
        return jsonify({"error": f"Error generando reporte: {str(e)}"}), 500

# 🆕 FUNCIONES AUXILIARES PARA GENERAR DATOS
def generar_resumen_diario(fecha):
    """Genera datos de resumen del día"""
    # Entradas de hoy
    entradas_hoy = Entrada.query.filter(
        db.func.date(Entrada.FECHA_ENTRADA) == fecha
    ).count()
    
    # Salidas de hoy
    salidas_hoy = Entrada.query.filter(
        db.func.date(Entrada.FECHA_SALIDA) == fecha,
        Entrada.ESTADO == "FINALIZADA"
    ).count()
    
    # Recaudo de hoy
    recaudo_hoy = db.session.query(db.func.sum(Entrada.MONTO_COBRADO)).filter(
        db.func.date(Entrada.FECHA_SALIDA) == fecha,
        Entrada.ESTADO == "FINALIZADA"
    ).scalar() or 0
    
    # Recargas de hoy
    recargas_hoy = Transaccion.query.filter(
        db.func.date(Transaccion.FECHA) == fecha,
        Transaccion.TIPO == "RECARGA",
        Transaccion.ESTADO == "CONFIRMADA"
    ).count()
    
    # Monto recargas hoy
    monto_recargas_hoy = db.session.query(db.func.sum(Transaccion.MONTO)).filter(
        db.func.date(Transaccion.FECHA) == fecha,
        Transaccion.TIPO == "RECARGA",
        Transaccion.ESTADO == "CONFIRMADA"
    ).scalar() or 0
    
    # Usuarios nuevos hoy
    usuarios_nuevos_hoy = Usuario.query.filter(
        db.func.date(Usuario.FECHA_REGISTRO) == fecha
    ).count()
    
    # Espacios actuales
    espacios_ocupados = Espacio.query.filter_by(ESTADO="OCUPADO").count()
    espacios_disponibles = Espacio.query.filter_by(ESTADO="DISPONIBLE").count()
    
    return {
        "Fecha": fecha.strftime("%Y-%m-%d"),
        "Entradas Hoy": entradas_hoy,
        "Salidas Hoy": salidas_hoy,
        "Recaudo Hoy ($)": float(recaudo_hoy),
        "Recargas Hoy": recargas_hoy,
        "Monto Recargas Hoy ($)": float(monto_recargas_hoy),
        "Usuarios Nuevos Hoy": usuarios_nuevos_hoy,
        "Espacios Ocupados": espacios_ocupados,
        "Espacios Disponibles": espacios_disponibles,
        "Total Espacios": espacios_ocupados + espacios_disponibles,
        "Tasa Ocupación (%)": round((espacios_ocupados / (espacios_ocupados + espacios_disponibles)) * 100, 2) if (espacios_ocupados + espacios_disponibles) > 0 else 0
    }

def generar_entradas_dia(fecha):
    """Genera datos de entradas y salidas del día"""
    entradas = Entrada.query.filter(
        db.func.date(Entrada.FECHA_ENTRADA) == fecha
    ).order_by(Entrada.FECHA_ENTRADA.desc()).all()
    
    datos = []
    for entrada in entradas:
        datos.append({
            "ID Entrada": entrada.ID,
            "Usuario": entrada.usuario.NOMBRE,
            "Cédula": entrada.usuario.CEDULA,
            "Vehículo": entrada.vehiculo.PLACA,
            "Tipo Vehículo": entrada.vehiculo.TIPO,
            "Espacio": entrada.espacio.NUMERO if entrada.espacio else "N/A",
            "Hora Entrada": entrada.FECHA_ENTRADA.strftime("%H:%M:%S"),
            "Hora Salida": entrada.FECHA_SALIDA.strftime("%H:%M:%S") if entrada.FECHA_SALIDA else "ACTIVA",
            "Estado": entrada.ESTADO,
            "Tiempo Estacionado": entrada.TIEMPO_ESTACIONADO or "N/A",
            "Monto Cobrado ($)": float(entrada.MONTO_COBRADO) if entrada.MONTO_COBRADO else 0
        })
    
    return datos

def generar_recargas_dia(fecha):
    """Genera datos de recargas del día"""
    recargas = Transaccion.query.filter(
        db.func.date(Transaccion.FECHA) == fecha,
        Transaccion.TIPO == "RECARGA",
        Transaccion.ESTADO == "CONFIRMADA"
    ).order_by(Transaccion.FECHA.desc()).all()
    
    datos = []
    for recarga in recargas:
        usuario = Usuario.query.get(recarga.ID_USUARIO)
        datos.append({
            "ID Transacción": recarga.ID,
            "Usuario": usuario.NOMBRE if usuario else "N/A",
            "Cédula": usuario.CEDULA if usuario else "N/A",
            "Monto ($)": float(recarga.MONTO),
            "Hora Recarga": recarga.FECHA.strftime("%H:%M:%S"),
            "Método": "QR"
        })
    
    return datos

def generar_estado_espacios():
    """Genera estado actual de espacios"""
    espacios = Espacio.query.all()
    
    datos = []
    for espacio in espacios:
        entrada_actual = None
        if espacio.ID_ENTRADA_ACTUAL:
            entrada_actual = Entrada.query.get(espacio.ID_ENTRADA_ACTUAL)
        
        datos.append({
            "Número": espacio.NUMERO,
            "Tipo": espacio.TIPO_VEHICULO,
            "Estado": espacio.ESTADO,
            "Vehículo": entrada_actual.vehiculo.PLACA if entrada_actual and entrada_actual.vehiculo else "N/A",
            "Usuario": entrada_actual.usuario.NOMBRE if entrada_actual and entrada_actual.usuario else "N/A",
            "Hora Entrada": entrada_actual.FECHA_ENTRADA.strftime("%H:%M:%S") if entrada_actual else "N/A",
            "Sensor Pin": espacio.SENSOR_PIN,
            "Última Detección": espacio.ULTIMA_DETECCION.strftime("%H:%M:%S") if espacio.ULTIMA_DETECCION else "N/A"
        })
    
    return datos

def generar_facturas_dia(fecha):
    """Genera datos de facturación del día"""
    facturas = Entrada.query.filter(
        db.func.date(Entrada.FECHA_SALIDA) == fecha,
        Entrada.ESTADO == "FINALIZADA",
        Entrada.MONTO_COBRADO.isnot(None)
    ).order_by(Entrada.FECHA_SALIDA.desc()).all()
    
    datos = []
    for factura in facturas:
        datos.append({
            "ID Factura": factura.ID,
            "Usuario": factura.usuario.NOMBRE,
            "Cédula": factura.usuario.CEDULA,
            "Vehículo": factura.vehiculo.PLACA,
            "Espacio": factura.espacio.NUMERO if factura.espacio else "N/A",
            "Entrada": factura.FECHA_ENTRADA.strftime("%H:%M"),
            "Salida": factura.FECHA_SALIDA.strftime("%H:%M"),
            "Tiempo": factura.TIEMPO_ESTACIONADO or "N/A",
            "Monto ($)": float(factura.MONTO_COBRADO),
            "URL Factura": f"http://{obtener_ip_servidor()}:5000/api/factura/generar/{factura.ID}"
        })
    
    return datos

def generar_usuarios_nuevos(fecha):
    """Genera datos de usuarios nuevos del día"""
    usuarios = Usuario.query.filter(
        db.func.date(Usuario.FECHA_REGISTRO) == fecha
    ).order_by(Usuario.FECHA_REGISTRO.desc()).all()
    
    datos = []
    for usuario in usuarios:
        vehiculo = Vehiculo.query.filter_by(ID_USUARIO=usuario.ID).first()
        datos.append({
            "ID Usuario": usuario.ID,
            "Nombre": usuario.NOMBRE,
            "Cédula": usuario.CEDULA,
            "Teléfono": usuario.TELEFONO or "N/A",
            "Email": usuario.EMAIL or "N/A",
            "Tarjeta RFID": usuario.TARJETA_RFID or "N/A",
            "Vehículo": vehiculo.PLACA if vehiculo else "N/A",
            "Hora Registro": usuario.FECHA_REGISTRO.strftime("%H:%M:%S"),
            "Saldo Inicial ($)": float(usuario.SALDO)
        })
    
    return datos

# 🆕 ENDPOINT PARA REPORTE POR RANGO DE FECHAS
@app.route("/api/reportes/rango-fechas/excel")
def generar_reporte_rango_fechas():
    """Genera reporte Excel por rango de fechas"""
    try:
        fecha_inicio = request.args.get('inicio', date.today().strftime("%Y-%m-%d"))
        fecha_fin = request.args.get('fin', date.today().strftime("%Y-%m-%d"))
        
        # Convertir strings a fechas
        inicio = datetime.strptime(fecha_inicio, "%Y-%m-%d").date()
        fin = datetime.strptime(fecha_fin, "%Y-%m-%d").date()
        
        nombre_archivo = f"reporte_{fecha_inicio}_a_{fecha_fin}.xlsx"
        
        # Similar al reporte diario pero con filtro por rango
        # (Implementación similar a la función anterior pero con filtro de fechas)
        
        return jsonify({"mensaje": "Reporte por rango en desarrollo", "fechas": f"{fecha_inicio} a {fecha_fin}"})
        
    except Exception as e:
        return jsonify({"error": f"Error en rango de fechas: {str(e)}"}), 500

# 🆕 ENDPOINT PARA DASHBOARD CON DATOS DEL REPORTE
@app.route("/api/reportes/diario/resumen")
def resumen_diario():
    """Retorna resumen del día en formato JSON para dashboards"""
    try:
        hoy = date.today()
        resumen = generar_resumen_diario(hoy)
        
        return jsonify({
            "fecha": hoy.strftime("%Y-%m-%d"),
            "resumen": resumen,
            "url_excel": f"http://{obtener_ip_servidor()}:5000/api/reportes/diario/excel"
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
# 🆕 FUNCIONES DE VALIDACIÓN
def validar_cedula(cedula):
    """Valida que la cédula tenga entre 7 y 10 dígitos numéricos"""
    if not cedula:
        return False, "La cédula es requerida"
    
    # Solo números
    if not cedula.isdigit():
        return False, "La cédula debe contener solo números"
    
    # Longitud entre 7 y 10 dígitos
    if len(cedula) < 7 or len(cedula) > 10:
        return False, "La cédula debe tener entre 7 y 10 dígitos"
    
    return True, ""

def validar_telefono(telefono):
    """Valida que el teléfono tenga 10 dígitos y empiece con 3"""
    if not telefono:
        return False, "El teléfono es requerido"
    
    # Eliminar espacios y caracteres especiales
    telefono_limpio = ''.join(filter(str.isdigit, telefono))
    
    if len(telefono_limpio) != 10:
        return False, f"Debe tener 10 dígitos (tiene {len(telefono_limpio)})"
    
    if not telefono_limpio.startswith('3'):
        return False, "Debe empezar con 3 (ej: 3123456789)"
    
    return True, ""
def validar_placa(placa):
    """Valida formato de placa colombiana (ABC123 o ABC12D)"""
    if not placa:
        return False, "La placa es requerida"
    
    placa = placa.upper().strip()
    
    # Formato antiguo: 3 letras + 3 números (ABC123)
    formato_antiguo = len(placa) == 6 and placa[:3].isalpha() and placa[3:].isdigit()
    
    # Formato nuevo: 3 letras + 2 números + 1 letra (ABC12D)  
    formato_nuevo = len(placa) == 6 and placa[:3].isalpha() and placa[3:5].isdigit() and placa[5:].isalpha()
    
    # Formato motos: 3 letras + 2 números + 1 letra (similar)
    formato_moto = len(placa) == 6 and placa[:3].isalpha() and placa[3:5].isdigit() and placa[5:].isalpha()
    
    if not (formato_antiguo or formato_nuevo or formato_moto):
        return False, "Formato de placa inválido. Use: ABC123 o ABC12D"
    
    return True, ""

def validar_email(email):
    """Valida formato básico de email"""
    if not email:
        return False, "El email es requerido"
    
    email_limpio = email.lower().strip()
    
    # Verificar formato básico
    if '@' not in email_limpio:
        return False, "Debe contener @"
    
    if '.' not in email_limpio:
        return False, "Debe contener un dominio (ej: .com)"
    
    partes = email_limpio.split('@')
    if len(partes) != 2:
        return False, "Formato inválido"
    
    usuario, dominio = partes
    if len(usuario) == 0:
        return False, "Falta el nombre de usuario antes del @"
    
    if len(dominio) == 0:
        return False, "Falta el dominio después del @"
    
    if '.' not in dominio:
        return False, "El dominio debe contener un punto (ej: gmail.com)"
    
    return True, ""

def validar_nombre(nombre):
    """Valida que el nombre tenga al menos 2 palabras y solo letras y espacios"""
    if not nombre:
        return False, "El nombre es requerido"
    
    # Solo letras y espacios
    if not all(c.isalpha() or c.isspace() for c in nombre):
        return False, "El nombre solo puede contener letras y espacios"
    
    # Al menos 2 palabras
    palabras = nombre.split()
    if len(palabras) < 2:
        return False, "Debe ingresar al menos nombre y apellido"
    
    # Cada palabra al menos 2 caracteres
    for palabra in palabras:
        if len(palabra) < 2:
            return False, "Cada nombre/apellido debe tener al menos 2 letras"
    
    # Longitud máxima razonable
    if len(nombre) > 50:
        return False, "El nombre es demasiado largo (máximo 50 caracteres)"
    
    return True, ""

def validar_marca_vehiculo(marca):
    """Valida la marca del vehículo"""
    if not marca:
        return False, "La marca del vehículo es requerida"
    
    if len(marca) < 2:
        return False, "La marca debe tener al menos 2 caracteres"
    
    if len(marca) > 20:
        return False, "La marca es demasiado larga (máximo 20 caracteres)"
    
    return True, ""

def validar_color_vehiculo(color):
    """Valida el color del vehículo"""
    if not color:
        return False, "El color del vehículo es requerida"
    
    if len(color) < 3:
        return False, "El color debe tener al menos 3 caracteres"
    
    if len(color) > 15:
        return False, "El color es demasiado largo (máximo 15 caracteres)"
    
    return True, ""

# 🆕 ENDPOINT DE REGISTRO CON VALIDACIONES MEJORADO
# 🆕 ENDPOINT DE REGISTRO CON MENSAJES MEJORADOS
# 🆕 ENDPOINT DE REGISTRO CON MEJOR DEBUGGING
@app.route("/api/registro/completar", methods=["POST"])
def completar_registro():
    """Completa el registro del usuario con validaciones mejoradas"""
    try:
        data = request.get_json()
        print(f"📨 Datos recibidos: {data}")  # 🆕 DEBUG
        
        token = data.get('token')
        
        # Validar token
        transaccion = Transaccion.query.filter_by(TOKEN=token, TIPO="REGISTRO", ESTADO="PENDIENTE").first()
        if not transaccion:
            return jsonify({"error": "Token inválido o expirado"}), 400
        
        # 🆕 VALIDAR CAMPOS CON MÁS DETALLES
        campos = {
            'nombre': data.get('nombre', '').strip(),
            'cedula': data.get('cedula', '').strip(),
            'telefono': data.get('telefono', '').strip(), 
            'email': data.get('email', '').strip(),
            'placa': data.get('placa', '').strip(),
            'marca': data.get('marca', '').strip(),
            'color': data.get('color', '').strip()
        }
        
        print(f"🔍 Campos después de limpiar: {campos}")  # 🆕 DEBUG
        
        # Verificar campos vacíos
        campos_vacios = []
        for campo, valor in campos.items():
            if not valor:
                nombre_campo = {
                    'nombre': 'Nombre completo',
                    'cedula': 'Cédula', 
                    'telefono': 'Teléfono',
                    'email': 'Email',
                    'placa': 'Placa del vehículo',
                    'marca': 'Marca del vehículo',
                    'color': 'Color del vehículo'
                }[campo]
                campos_vacios.append(f"❌ {nombre_campo} es obligatorio")
        
        if campos_vacios:
            print(f"🚫 Campos vacíos: {campos_vacios}")  # 🆕 DEBUG
            return jsonify({
                "error": "Faltan campos obligatorios",
                "detalles": campos_vacios
            }), 400
        
        # Validaciones específicas
        errores = []
        
        # Nombre
        valido, mensaje = validar_nombre(campos['nombre'])
        print(f"🔍 Validación nombre: {valido} - {mensaje}")  # 🆕 DEBUG
        if not valido:
            errores.append(f"❌ Nombre: {mensaje}")
        
        # Cédula
        valido, mensaje = validar_cedula(campos['cedula'])
        print(f"🔍 Validación cédula: {valido} - {mensaje}")  # 🆕 DEBUG
        if not valido:
            errores.append(f"❌ Cédula: {mensaje}")
        else:
            cedula_existente = Usuario.query.filter_by(CEDULA=campos['cedula']).first()
            if cedula_existente:
                errores.append("❌ Cédula: Ya está registrada en el sistema")
        
        # Teléfono
        valido, mensaje = validar_telefono(campos['telefono'])
        print(f"🔍 Validación teléfono: {valido} - {mensaje}")  # 🆕 DEBUG
        if not valido:
            errores.append(f"❌ Teléfono: {mensaje}")
        
        # Email
        valido, mensaje = validar_email(campos['email'])
        print(f"🔍 Validación email: {valido} - {mensaje}")  # 🆕 DEBUG
        if not valido:
            errores.append(f"❌ Email: {mensaje}")
        else:
            email_existente = Usuario.query.filter_by(EMAIL=campos['email']).first()
            if email_existente:
                errores.append("❌ Email: Ya está registrado en el sistema")
        
        # Placa
        valido, mensaje = validar_placa(campos['placa'])
        print(f"🔍 Validación placa: {valido} - {mensaje}")  # 🆕 DEBUG
        if not valido:
            errores.append(f"❌ Placa: {mensaje}")
        else:
            placa_existente = Vehiculo.query.filter_by(PLACA=campos['placa'].upper()).first()
            if placa_existente:
                errores.append("❌ Placa: Ya está registrada en el sistema")
        
        # Marca
        valido, mensaje = validar_marca_vehiculo(campos['marca'])
        print(f"🔍 Validación marca: {valido} - {mensaje}")  # 🆕 DEBUG
        if not valido:
            errores.append(f"❌ Marca: {mensaje}")
        
        # Color
        valido, mensaje = validar_color_vehiculo(campos['color'])
        print(f"🔍 Validación color: {valido} - {mensaje}")  # 🆕 DEBUG
        if not valido:
            errores.append(f"❌ Color: {mensaje}")
        
        print(f"🔍 Errores encontrados: {errores}")  # 🆕 DEBUG
        
        if errores:
            return jsonify({
                "error": "Se encontraron errores en los datos",
                "detalles": errores
            }), 400
        
        # VERIFICAR ESPACIOS DISPONIBLES
        tipo_vehiculo = data.get('tipo_vehiculo', 'CARRO')
        espacio_disponible = Espacio.query.filter_by(
            TIPO_VEHICULO=tipo_vehiculo,
            ESTADO="DISPONIBLE"
        ).first()
        
        if not espacio_disponible:
            return jsonify({"error": "Ya no hay espacios disponibles. Intente más tarde"}), 400
        
        # 🆕 CREAR USUARIO Y VEHÍCULO
        try:
            usuario = Usuario(
                NOMBRE=campos['nombre'].title(),
                CEDULA=campos['cedula'],
                TELEFONO=campos['telefono'],
                EMAIL=campos['email'].lower(),
                SALDO=0.0,
                TARJETA_RFID=transaccion.TARJETA_RFID
            )
            db.session.add(usuario)
            db.session.flush()
            print(f"✅ Usuario creado: {usuario.NOMBRE} (ID: {usuario.ID})")
            
            vehiculo = Vehiculo(
                PLACA=campos['placa'].upper(),
                TIPO=tipo_vehiculo,
                ID_USUARIO=usuario.ID,
                MARCA=campos['marca'].title(),
                COLOR=campos['color'].title()
            )
            db.session.add(vehiculo)
            db.session.flush()
            print(f"✅ Vehículo creado: {vehiculo.PLACA} (ID: {vehiculo.ID})")
            
            entrada = Entrada(
                ID_USUARIO=usuario.ID,
                ID_VEHICULO=vehiculo.ID,
                ID_ESPACIO=espacio_disponible.ID,
                ESTADO="ACTIVA"
            )
            db.session.add(entrada)
            db.session.flush()
            print(f"✅ Entrada creada: ID {entrada.ID}")
            
            # OCUPAR ESPACIO
            espacio_disponible.ESTADO = "OCUPADO"
            espacio_disponible.ID_ENTRADA_ACTUAL = entrada.ID
            
            # GENERAR RECARGA
            tarifa_minima = 5000
            token_recarga = generar_token()
            transaccion_recarga = Transaccion(
                ID_USUARIO=usuario.ID,
                TIPO="RECARGA",
                MONTO=tarifa_minima * 2,
                ESTADO="PENDIENTE",
                TOKEN=token_recarga
            )
            db.session.add(transaccion_recarga)
            
            # Actualizar transacción de registro
            transaccion.ID_USUARIO = usuario.ID
            transaccion.ESTADO = "CONFIRMADA"
            
            db.session.commit()
            
            ip_servidor = obtener_ip_servidor()
            url_recarga = f"http://{ip_servidor}:5000/recarga/{token_recarga}"
            
            print(f"🎉 REGISTRO EXITOSO - Usuario: {usuario.NOMBRE}")
            
            return jsonify({
                "success": True,
                "mensaje": f"✅ Registro exitoso! Espacio {espacio_disponible.NUMERO} asignado",
                "usuario_id": usuario.ID,
                "vehiculo_id": vehiculo.ID,
                "espacio_asignado": espacio_disponible.NUMERO,
                "token_recarga": token_recarga,
                "url_recarga": url_recarga
            }), 200
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Error en base de datos: {str(e)}")
            return jsonify({"error": f"Error al guardar en base de datos: {str(e)}"}), 500
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error general en registro: {str(e)}")
        return jsonify({"error": f"Error en registro: {str(e)}"}), 500
@app.route("/debug/usuario/<tarjeta_rfid>")
def debug_usuario(tarjeta_rfid):
    """Debug temporal para verificar estado de usuario"""
    usuario = Usuario.query.filter_by(TARJETA_RFID=tarjeta_rfid.upper()).first()
    if usuario:
        entrada_activa = Entrada.query.filter_by(ID_USUARIO=usuario.ID, ESTADO="ACTIVA").first()
        return jsonify({
            "encontrado": True,
            "nombre": usuario.NOMBRE,
            "saldo": float(usuario.SALDO) if usuario.SALDO else 0.0,
            "tarjeta_rfid": usuario.TARJETA_RFID,
            "vehiculo": usuario.vehiculos[0].PLACA if usuario.vehiculos else "No tiene",
            "entrada_activa": entrada_activa is not None
        })
    else:
        return jsonify({"encontrado": False})

# 🆕 ENDPOINT PARA ESTADO DE ESPACIOS

@app.route("/registro/<token>")
def pagina_registro(token):
    """Página web para registro de nuevo usuario"""
    transaccion = Transaccion.query.filter_by(TOKEN=token, TIPO="REGISTRO", ESTADO="PENDIENTE").first()
    if not transaccion:
        return "Enlace inválido o expirado"
    
    ip_servidor = obtener_ip_servidor()
    url_registro = f"http://{ip_servidor}:5000/registro/{token}"
    
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Registro - Parqueadero Inteligente</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { font-family: Arial, sans-serif; max-width: 500px; margin: 0 auto; padding: 20px; }
            .container { background: #f5f5f5; padding: 20px; border-radius: 10px; }
            h1 { color: #333; text-align: center; }
            input, select, button { width: 100%; padding: 10px; margin: 8px 0; border: 1px solid #ddd; border-radius: 5px; }
            button { background: #007bff; color: white; border: none; cursor: pointer; }
            button:hover { background: #0056b3; }
            button:disabled { 
                background: #6c757d; 
                cursor: not-allowed; 
            }
            .success { color: green; font-weight: bold; }
            .error { color: red; font-weight: bold; }
            .qr-section { text-align: center; margin: 20px 0; }
            .url-link { background: #e7f3ff; padding: 10px; border-radius: 5px; word-break: break-all; }
            .loading { 
                text-align: center; 
                color: #007bff; 
                font-weight: bold; 
            }
            .info-box { 
                background: #d4edda; 
                border: 1px solid #c3e6cb; 
                padding: 15px; 
                border-radius: 5px; 
                margin: 10px 0;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚗 Registro de Usuario</h1>
            <p>Complete sus datos para registrar su tarjeta RFID</p>
            
            <!-- 🆕 SECCIÓN QR -->
            <div class="qr-section">
                <h3>📱 Escanee este código QR</h3>
                <img src="/qr/registro/{{ token }}" alt="QR Code" style="max-width: 200px;">
                <p>O copie este enlace:</p>
                <div class="url-link">
                    <strong>{{ url_registro }}</strong>
                </div>
            </div>
            
            <form id="formRegistro">
                <h3>👤 Datos Personales</h3>
                <input type="text" id="nombre" placeholder="Nombre completo" required>
                <input type="text" id="cedula" placeholder="Cédula" required>
                <input type="tel" id="telefono" placeholder="Teléfono" required>
                <input type="email" id="email" placeholder="Email" required>
                
                <h3>🚗 Datos del Vehículo</h3>
                <input type="text" id="placa" placeholder="Placa del vehículo" required>
                <select id="tipoVehiculo">
                    <option value="CARRO">Carro</option>
                    <option value="MOTO">Moto</option>
                </select>
                <input type="text" id="marca" placeholder="Marca del vehículo">
                <input type="text" id="color" placeholder="Color del vehículo">
                
                <button type="submit" id="btnRegistro">📝 Registrar Usuario</button>
            </form>
            
            <div id="resultado"></div>
        </div>

        <script>
        document.getElementById('formRegistro').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const btnRegistro = document.getElementById('btnRegistro');
            
            // Deshabilitar botón durante el registro
            btnRegistro.disabled = true;
            btnRegistro.innerHTML = '⏳ Registrando...';
            
            document.getElementById('resultado').innerHTML = 
                '<div class="loading">' +
                '   <p>📝 Procesando registro...</p>' +
                '   <p>⏳ Por favor espere</p>' +
                '</div>';
            
            const datos = {
                token: '{{ token }}',
                nombre: document.getElementById('nombre').value,
                cedula: document.getElementById('cedula').value,
                telefono: document.getElementById('telefono').value,
                email: document.getElementById('email').value,
                placa: document.getElementById('placa').value,
                tipo_vehiculo: document.getElementById('tipoVehiculo').value,
                marca: document.getElementById('marca').value,
                color: document.getElementById('color').value
            };
            
            try {
                const response = await fetch('/api/registro/completar', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(datos)
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    let mensajeHTML = 
                        '<div class="info-box">' +
                        '   <p class="success">✅ ' + data.mensaje + '</p>' +
                        '</div>' +
                        '<div style="background: #e7f3ff; padding: 15px; border-radius: 10px; margin: 15px 0;">' +
                        '   <p><strong>👤 Usuario:</strong> ' + datos.nombre + '</p>' +
                        '   <p><strong>🚗 Vehículo:</strong> ' + datos.placa + '</p>' +
                        '   <p><strong>📧 Email:</strong> ' + datos.email + '</p>' +
                        '</div>' +
                        '<div style="background: #fff3cd; padding: 15px; border-radius: 10px; margin: 15px 0;">' +
                        '   <p><strong>💰 Siguiente paso:</strong></p>' +
                        '   <p>Será redirigido automáticamente a la página de recarga</p>' +
                        '</div>';
                    
                    document.getElementById('resultado').innerHTML = mensajeHTML;
                    
                    // 🆕 REDIRIGIR AUTOMÁTICAMENTE A RECARGA DESPUÉS DE 3 SEGUNDOS
                    setTimeout(() => {
                        if (data.url_recarga) {
                            window.location.href = data.url_recarga;
                        }
                    }, 3000);
                    
                } else {
                    document.getElementById('resultado').innerHTML = 
                        '<div class="error">' +
                        '   <p>❌ ' + data.error + '</p>' +
                        '</div>';
                    
                    // Re-habilitar botón en caso de error
                    btnRegistro.disabled = false;
                    btnRegistro.innerHTML = '📝 Registrar Usuario';
                }
            } catch (error) {
                document.getElementById('resultado').innerHTML = 
                    '<div class="error">' +
                    '   <p>❌ Error de conexión</p>' +
                    '   <p>Verifique su conexión a internet e intente nuevamente</p>' +
                    '</div>';
                
                // Re-habilitar botón en caso de error
                btnRegistro.disabled = false;
                btnRegistro.innerHTML = '📝 Registrar Usuario';
            }
        });
        </script>
    </body>
    </html>
    ''', token=token, url_registro=url_registro)

# ✅ 5. COMPLETAR REGISTRO - MEJORADO

@app.route("/qr/recarga/<token>")
def generar_qr_recarga(token):
    """Genera QR para recarga de saldo"""
    try:
        ip_servidor = obtener_ip_servidor()
        url_recarga = f"http://{ip_servidor}:5000/recarga/{token}"
        
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(url_recarga)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="green", back_color="white")
        buf = BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        
        return send_file(buf, mimetype='image/png')
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 🆕 AGREGAR ESTE ENDPOINT QUE FALTA
@app.route("/qr/registro/<token>")
def generar_qr_registro(token):
    """Genera QR para registro de nuevo usuario"""
    try:
        # Verificar que el token existe
        transaccion = Transaccion.query.filter_by(TOKEN=token, TIPO="REGISTRO", ESTADO="PENDIENTE").first()
        if not transaccion:
            return "Token inválido o expirado", 404
        
        ip_servidor = obtener_ip_servidor()
        url_registro = f"http://{ip_servidor}:5000/registro/{token}"
        
        print(f"📱 Generando QR para registro: {url_registro}")
        
        # Generar QR
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(url_registro)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="blue", back_color="white")
        buf = BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        
        print(f"✅ QR generado exitosamente")
        return send_file(buf, mimetype='image/png')
        
    except Exception as e:
        print(f"❌ Error generando QR: {str(e)}")
        return jsonify({"error": f"Error generando QR: {str(e)}"}), 500
@app.route("/recarga/<token>")
def pagina_recarga(token):
    """Página web para recarga de saldo con montos actualizados"""
    transaccion = Transaccion.query.filter_by(TOKEN=token, TIPO="RECARGA", ESTADO="PENDIENTE").first()
    if not transaccion:
        return "Enlace inválido o expirado"
    
    usuario = Usuario.query.get(transaccion.ID_USUARIO)
    monto_minimo = 5000  # 🆕 CAMBIADO A 5000
    ip_servidor = obtener_ip_servidor()
    url_recarga = f"http://{ip_servidor}:5000/recarga/{token}"
    
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Recarga - Parqueadero Inteligente</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { font-family: Arial, sans-serif; max-width: 500px; margin: 0 auto; padding: 20px; }
            .container { background: #f5f5f5; padding: 20px; border-radius: 10px; }
            h1 { color: #333; text-align: center; }
            .user-info { background: #e7f3ff; padding: 15px; border-radius: 5px; margin: 10px 0; }
            .monto-btn { 
                background: white; 
                border: 2px solid #007bff; 
                padding: 15px; 
                margin: 5px; 
                border-radius: 5px; 
                cursor: pointer;
                text-align: center;
            }
            .monto-btn.selected { background: #007bff; color: white; }
            button { width: 100%; padding: 15px; background: #28a745; color: white; border: none; border-radius: 5px; cursor: pointer; }
            button:hover { background: #218838; }
            .success { color: green; }
            .error { color: red; }
            .qr-section { text-align: center; margin: 20px 0; }
            .url-link { background: #e7f3ff; padding: 10px; border-radius: 5px; word-break: break-all; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>💰 Recarga de Saldo</h1>
            
            <div class="qr-section">
                <h3>📱 Escanee este código QR</h3>
                <img src="/qr/recarga/{{ token }}" alt="QR Code" style="max-width: 200px;">
                <p>O copie este enlace:</p>
                <div class="url-link">
                    <strong>{{ url_recarga }}</strong>
                </div>
            </div>
            
            <div class="user-info">
                <p><strong>Usuario:</strong> {{ usuario.NOMBRE }}</p>
                <p><strong>Saldo actual:</strong> ${{ "%.0f"|format(usuario.SALDO|float) }}</p>
                <p><strong>Mínimo para entrada:</strong> ${{ monto_minimo }}</p>
                <p><strong>💡 Nota:</strong> El monto mínimo para ingresar es ahora de $5,000</p>
            </div>
            
            <h3>Seleccione el monto a recargar:</h3>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                <!-- 🆕 MONTOS ACTUALIZADOS -->
                <div class="monto-btn" data-monto="10000">$10.000</div>
                <div class="monto-btn" data-monto="15000">$15.000</div>
                <div class="monto-btn" data-monto="20000">$20.000</div>
                <div class="monto-btn" data-monto="50000">$50.000</div>
                <div class="monto-btn" data-monto="100000">$100.000</div>
                <div class="monto-btn" data-monto="200000">$200.000</div>
            </div>
            
            <input type="hidden" id="montoSeleccionado" value="10000">
            
            <button onclick="procesarPago()">💳 Proceder al Pago</button>
            
            <div id="resultado" style="margin-top: 20px;"></div>
        </div>

        <script>
        // Seleccionar monto
        document.querySelectorAll('.monto-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                document.querySelectorAll('.monto-btn').forEach(b => b.classList.remove('selected'));
                this.classList.add('selected');
                document.getElementById('montoSeleccionado').value = this.dataset.monto;
            });
        });
        
        // Seleccionar primer monto por defecto
        document.querySelector('.monto-btn').classList.add('selected');
        
        async function procesarPago() {
            const monto = document.getElementById('montoSeleccionado').value;
            const token = '{{ token }}';
            
            document.getElementById('resultado').innerHTML = '<p>⏳ Procesando pago...</p>';
            
            try {
                const response = await fetch('/api/recarga/procesar', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({token: token, monto: parseFloat(monto)})
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    document.getElementById('resultado').innerHTML = 
                        '<p class="success">✅ ' + data.mensaje + '</p>' +
                        '<p><strong>Nuevo saldo:</strong> $' + data.nuevo_saldo + '</p>' +
                        '<p><strong>Ya puede ingresar al parqueadero!</strong></p>' +
                        '<p>Pase su tarjeta RFID nuevamente en la entrada</p>';
                } else {
                    document.getElementById('resultado').innerHTML = 
                        '<p class="error">❌ ' + data.error + '</p>';
                }
            } catch (error) {
                document.getElementById('resultado').innerHTML = 
                    '<p class="error">❌ Error de conexión</p>';
            }
        }
        </script>
    </body>
    </html>
    ''', usuario=usuario, monto_minimo=monto_minimo, token=token, url_recarga=url_recarga)
@app.route("/api/recarga/procesar", methods=["POST"])
def procesar_recarga():
    """Procesa la recarga de saldo y abre barrera automáticamente si hay espacio"""
    try:
        data = request.get_json()
        token = data.get('token')
        monto = float(data.get('monto', 0))
        
        transaccion = Transaccion.query.filter_by(TOKEN=token, TIPO="RECARGA", ESTADO="PENDIENTE").first()
        if not transaccion:
            return jsonify({"error": "Token inválido o expirado"}), 400
        
        usuario = Usuario.query.get(transaccion.ID_USUARIO)
        if not usuario:
            return jsonify({"error": "Usuario no encontrado"}), 404
        
        # ACTUALIZAR SALDO
        saldo_anterior = float(usuario.SALDO) if usuario.SALDO else 0.0
        nuevo_saldo = saldo_anterior + monto
        usuario.SALDO = nuevo_saldo
        
        # Confirmar transacción
        transaccion.MONTO = monto
        transaccion.ESTADO = "CONFIRMADA"
        
        db.session.commit()
        
        print(f"💰 RECARGA EXITOSA - Usuario: {usuario.NOMBRE}, Saldo: {nuevo_saldo}")
        
        # 🆕 VERIFICAR SI HAY ESPACIO DISPONIBLE Y CREAR ENTRADA AUTOMÁTICAMENTE
        vehiculo = Vehiculo.query.filter_by(ID_USUARIO=usuario.ID).first()
        espacio_asignado = None
        entrada_creada = False
        
        if vehiculo:
            # Verificar si ya tiene entrada activa
            entrada_activa = Entrada.query.filter_by(ID_USUARIO=usuario.ID, ESTADO="ACTIVA").first()
            
            if not entrada_activa:
                # 🆕 BUSCAR ESPACIO DISPONIBLE SEGÚN SENSORES
                espacio_disponible = Espacio.query.filter_by(
                    TIPO_VEHICULO=vehiculo.TIPO,
                    ESTADO="DISPONIBLE"
                ).first()
                
                if espacio_disponible:
                    # 🆕 CREAR ENTRADA AUTOMÁTICAMENTE
                    entrada = Entrada(
                        ID_USUARIO=usuario.ID,
                        ID_VEHICULO=vehiculo.ID,
                        ID_ESPACIO=espacio_disponible.ID,
                        ESTADO="ACTIVA"
                    )
                    db.session.add(entrada)
                    db.session.flush()
                    
                    # OCUPAR ESPACIO
                    espacio_disponible.ESTADO = "OCUPADO"
                    espacio_disponible.ID_ENTRADA_ACTUAL = entrada.ID
                    
                    db.session.commit()
                    entrada_creada = True
                    espacio_asignado = espacio_disponible.NUMERO
                    
                    print(f"🎉 ENTRADA AUTOMÁTICA CREADA - Usuario: {usuario.NOMBRE}, Espacio: {espacio_asignado}")
                    
                    # 🆕 IMPORTANTE: Enviar comando de apertura automática
                    # En un sistema real, aquí enviarías una señal a Arduino via WebSocket o HTTP
                else:
                    print(f"⚠️ Recarga exitosa pero no hay espacios disponibles para {usuario.NOMBRE}")
            else:
                print(f"⚠️ Usuario {usuario.NOMBRE} ya tiene entrada activa")
        
        # 🆕 PREPARAR RESPUESTA CON INFORMACIÓN DE ENTRADA
        respuesta = {
            "success": True,
            "mensaje": "Recarga exitosa",
            "saldo_anterior": saldo_anterior,
            "nuevo_saldo": nuevo_saldo,
            "monto_recargado": monto
        }
        
        # 🆕 AGREGAR INFORMACIÓN DE ENTRADA SI SE CREÓ
        if entrada_creada and espacio_asignado:
            respuesta.update({
                "entrada_automatica": True,
                "mensaje_entrada": f"¡Entrada registrada exitosamente!",
                "espacio_asignado": espacio_asignado,
                "vehiculo": vehiculo.PLACA,
                "comando": "ABRIR_BARRERA"  # 🆕 COMANDO PARA ARDUINO
            })
            
            # 🆕 ENVIAR SEÑAL DE APERTURA A ARDUINO
            # En un sistema real, implementarías WebSockets o un endpoint especial
            print(f"🚦 ENVIANDO COMANDO DE APERTURA AUTOMÁTICA PARA {usuario.NOMBRE}")
            
        else:
            respuesta.update({
                "entrada_automatica": False,
                "mensaje_entrada": "Recarga exitosa. Pase su tarjeta en la entrada para verificar disponibilidad."
            })
        
        return jsonify(respuesta), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error en recarga: {str(e)}")
        return jsonify({"error": f"Error en recarga: {str(e)}"}), 500
# 🆕 ENDPOINT PARA CONTROL MANUAL DE BARRERA
# 🆕 ENDPOINT PARA ACTUALIZAR ESTADO DE SENSORES
@app.route("/api/sensores/actualizar", methods=["POST"])
def actualizar_sensores():
    """Actualiza el estado de los espacios basado en los sensores"""
    try:
        data = request.get_json() or {}
        print(f"📡 Datos de sensores recibidos: {data}")
        
        # Ejemplo de data esperada: {"sensor_1": true, "sensor_2": false, "sensor_3": true}
        
        for sensor_key, detectado in data.items():
            if sensor_key.startswith("sensor_"):
                numero_sensor = int(sensor_key.split("_")[1])
                
                # Buscar espacio con este sensor
                espacio = Espacio.query.filter_by(SENSOR_PIN=numero_sensor).first()
                if espacio:
                    if detectado:
                        # Sensor detecta vehículo
                        if espacio.ESTADO == "DISPONIBLE":
                            espacio.ESTADO = "OCUPADO"
                            print(f"🅿️ Sensor {numero_sensor}: Espacio {espacio.NUMERO} ahora OCUPADO")
                    else:
                        # Sensor no detecta vehículo
                        if espacio.ESTADO == "OCUPADO":
                            # Verificar si hay entrada activa
                            entrada_activa = Entrada.query.filter_by(
                                ID_ESPACIO=espacio.ID, 
                                ESTADO="ACTIVA"
                            ).first()
                            
                            if not entrada_activa:
                                espacio.ESTADO = "DISPONIBLE"
                                print(f"🅿️ Sensor {numero_sensor}: Espacio {espacio.NUMERO} ahora DISPONIBLE")
                    
                    espacio.ULTIMA_DETECCION = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({"success": True, "mensaje": "Sensores actualizados"}), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error actualizando sensores: {str(e)}")
        return jsonify({"error": f"Error en sensores: {str(e)}"}), 500

# 🆕 ENDPOINT PARA OBTENER ESPACIOS DISPONIBLES (CONSIDERA SENSORES)
@app.route("/api/espacios/disponibles")
def espacios_disponibles():
    """Retorna solo los espacios que están disponibles según los sensores"""
    try:
        espacios = Espacio.query.filter_by(ESTADO="DISPONIBLE").all()
        resultado = []
        
        for espacio in espacios:
            resultado.append({
                "numero": espacio.NUMERO,
                "tipo": espacio.TIPO_VEHICULO,
                "sensor_pin": espacio.SENSOR_PIN
            })
        
        return jsonify({"espacios_disponibles": resultado})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
from flask import Flask, jsonify, request, send_file, render_template_string, redirect  # 🆕 AGREGAR redirect


# 🆕 ENDPOINT CORREGIDO PARA GENERAR FACTURA POR ID DE ENTRADA
@app.route("/api/factura/generar/<int:entrada_id>")
def generar_factura_id(entrada_id):
    """Genera factura en formato HTML usando el ID de entrada"""
    try:
        # Buscar entrada por ID
        entrada = Entrada.query.get(entrada_id)
        if not entrada:
            return jsonify({"error": "Entrada no encontrada"}), 404
        
        if not entrada.FECHA_SALIDA:
            return jsonify({"error": "El vehículo aún no ha salido"}), 400
        
        # Calcular tiempo estacionado
        tiempo_estacionado = entrada.FECHA_SALIDA - entrada.FECHA_ENTRADA
        horas = tiempo_estacionado.total_seconds() / 3600
        horas_redondeadas = max(1, round(horas * 2) / 2)
        
        usuario = entrada.usuario
        vehiculo = entrada.vehiculo
        espacio = entrada.espacio
        
        # Obtener tarifa
        tarifa = Tarifa.query.filter_by(TIPO_VEHICULO=vehiculo.TIPO, ACTIVA=True).first()
        tarifa_hora = float(tarifa.TARIFA_HORA) if tarifa else 5000.0
        
        factura_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Factura - Parqueadero Inteligente</title>
            <meta charset="UTF-8">
            <style>
                body {{ 
                    font-family: 'Arial', sans-serif; 
                    max-width: 800px; 
                    margin: 0 auto; 
                    padding: 20px;
                    background-color: #f8f9fa;
                }}
                .container {{ 
                    background: white; 
                    padding: 30px; 
                    border-radius: 15px;
                    box-shadow: 0 0 20px rgba(0,0,0,0.1);
                    border: 2px solid #007bff;
                }}
                .header {{ 
                    text-align: center; 
                    border-bottom: 3px solid #007bff; 
                    padding-bottom: 20px;
                    margin-bottom: 30px;
                }}
                .logo {{ 
                    font-size: 32px; 
                    font-weight: bold;
                    color: #007bff;
                    margin-bottom: 10px;
                }}
                .factura-id {{ 
                    background: #007bff; 
                    color: white; 
                    padding: 8px 15px; 
                    border-radius: 20px;
                    display: inline-block;
                    font-weight: bold;
                }}
                .info-section {{ 
                    margin: 25px 0; 
                    padding: 20px;
                    background: #f8f9fa;
                    border-radius: 10px;
                    border-left: 4px solid #007bff;
                }}
                .info-section h3 {{
                    color: #007bff;
                    margin-top: 0;
                    border-bottom: 1px solid #dee2e6;
                    padding-bottom: 10px;
                }}
                .total-section {{ 
                    background: linear-gradient(135deg, #007bff, #0056b3); 
                    color: white; 
                    padding: 25px; 
                    border-radius: 10px; 
                    font-weight: bold;
                    text-align: center;
                    margin: 30px 0;
                }}
                .footer {{ 
                    text-align: center; 
                    margin-top: 40px; 
                    color: #6c757d;
                    font-size: 14px;
                    border-top: 1px solid #dee2e6;
                    padding-top: 20px;
                }}
                .row {{
                    display: flex;
                    justify-content: space-between;
                    margin-bottom: 10px;
                }}
                .label {{ font-weight: bold; color: #495057; }}
                .value {{ color: #212529; }}
                .total-amount {{
                    font-size: 36px;
                    font-weight: bold;
                    margin: 15px 0;
                }}
                .badge {{
                    background: #28a745;
                    color: white;
                    padding: 5px 10px;
                    border-radius: 15px;
                    font-size: 12px;
                    font-weight: bold;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="logo">🚗 PARQUEADERO INTELIGENTE</div>
                    <h1>FACTURA DE ESTACIONAMIENTO</h1>
                    <div class="factura-id">FACTURA #{entrada.ID:06d}</div>
                    <p>Sistema Automatizado de Gestión Vehicular</p>
                </div>
                
                <div class="row">
                    <div style="flex: 1;">
                        <div class="info-section">
                            <h3>👤 INFORMACIÓN DEL CLIENTE</h3>
                            <div class="row"><span class="label">Nombre:</span><span class="value">{usuario.NOMBRE}</span></div>
                            <div class="row"><span class="label">Cédula:</span><span class="value">{usuario.CEDULA}</span></div>
                            <div class="row"><span class="label">Teléfono:</span><span class="value">{usuario.TELEFONO or 'N/A'}</span></div>
                            <div class="row"><span class="label">Email:</span><span class="value">{usuario.EMAIL or 'N/A'}</span></div>
                        </div>
                    </div>
                </div>
                
                <div class="row">
                    <div style="flex: 1; margin-right: 15px;">
                        <div class="info-section">
                            <h3>🚗 INFORMACIÓN DEL VEHÍCULO</h3>
                            <div class="row"><span class="label">Placa:</span><span class="value">{vehiculo.PLACA}</span></div>
                            <div class="row"><span class="label">Tipo:</span><span class="value">{vehiculo.TIPO}</span></div>
                            <div class="row"><span class="label">Marca:</span><span class="value">{vehiculo.MARCA or 'N/A'}</span></div>
                            <div class="row"><span class="label">Color:</span><span class="value">{vehiculo.COLOR or 'N/A'}</span></div>
                        </div>
                    </div>
                    
                    <div style="flex: 1; margin-left: 15px;">
                        <div class="info-section">
                            <h3>📅 DETALLES DEL SERVICIO</h3>
                            <div class="row"><span class="label">Espacio:</span><span class="value">{espacio.NUMERO if espacio else 'N/A'}</span></div>
                            <div class="row"><span class="label">Fecha entrada:</span><span class="value">{entrada.FECHA_ENTRADA.strftime('%Y-%m-%d %H:%M:%S')}</span></div>
                            <div class="row"><span class="label">Fecha salida:</span><span class="value">{entrada.FECHA_SALIDA.strftime('%Y-%m-%d %H:%M:%S')}</span></div>
                            <div class="row"><span class="label">Tiempo total:</span><span class="value">{entrada.TIEMPO_ESTACIONADO or str(tiempo_estacionado).split('.')[0]}</span></div>
                            <div class="row"><span class="label">Tarifa/hora:</span><span class="value">${tarifa_hora:,.0f}</span></div>
                        </div>
                    </div>
                </div>
                
                <div class="total-section">
                    <h3>💰 TOTAL PAGADO</h3>
                    <div class="total-amount">${float(entrada.MONTO_COBRADO):,.0f}</div>
                    <div class="row" style="justify-content: center;">
                        <span class="label" style="color: white;">Saldo restante:</span>
                        <span class="value" style="color: white; margin-left: 15px;">${float(usuario.SALDO):,.0f}</span>
                    </div>
                    <div style="margin-top: 15px;">
                        <span class="badge">PAGADO ✓</span>
                    </div>
                </div>
                
                <div class="footer">
                    <p><strong>¡Gracias por preferir nuestro parqueadero!</strong></p>
                    <p>Factura generada el: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                    <p>Para consultas: contacto@parqueaderointeligente.com</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return render_template_string(factura_html)
        
    except Exception as e:
        return jsonify({"error": f"Error generando factura: {str(e)}"}), 500

# 🆕 ENDPOINT CORREGIDO PARA FACTURA POR PLACA
@app.route("/api/factura/placa/<placa>")
def factura_por_placa(placa):
    """Genera factura de la última salida por placa"""
    try:
        # Buscar vehículo por placa
        vehiculo = Vehiculo.query.filter_by(PLACA=placa.upper()).first()
        if not vehiculo:
            return jsonify({"error": "Vehículo no encontrado"}), 404
        
        # Buscar la última entrada finalizada del vehículo
        entrada = Entrada.query.filter_by(
            ID_VEHICULO=vehiculo.ID, 
            ESTADO="FINALIZADA"
        ).order_by(Entrada.FECHA_SALIDA.desc()).first()
        
        if not entrada:
            return jsonify({"error": "No hay historial de estacionamiento para este vehículo"}), 404
        
        # Redirigir al endpoint de factura por ID
        return redirect(f"/api/factura/generar/{entrada.ID}")
        
    except Exception as e:
        return jsonify({"error": f"Error buscando factura: {str(e)}"}), 500
@app.route("/api/barrera/abrir-automatica", methods=["POST"])
def abrir_barrera_automatica():
    """Endpoint para que Arduino consulte si debe abrir la barrera automáticamente"""
    try:
        data = request.get_json() or {}
        tarjeta_rfid = data.get("tarjeta_rfid", "").strip().upper()
        
        if not tarjeta_rfid:
            return jsonify({"error": "Tarjeta RFID requerida"}), 400
        
        print(f"🔍 Consulta apertura automática - Tarjeta: {tarjeta_rfid}")
        
        # Buscar usuario
        usuario = Usuario.query.filter_by(TARJETA_RFID=tarjeta_rfid).first()
        if not usuario:
            return jsonify({"abrir_barrera": False, "razon": "Usuario no encontrado"}), 200
        
        # Verificar si tiene entrada activa recién creada
        entrada_activa = Entrada.query.filter_by(ID_USUARIO=usuario.ID, ESTADO="ACTIVA").first()
        
        if entrada_activa:
            # Verificar si la entrada fue creada hace menos de 30 segundos (recién registrado)
            tiempo_desde_entrada = datetime.utcnow() - entrada_activa.FECHA_ENTRADA
            if tiempo_desde_entrada.total_seconds() < 30:  # 30 segundos de margen
                print(f"🚦 APERTURA AUTOMÁTICA AUTORIZADA para {usuario.NOMBRE}")
                return jsonify({
                    "abrir_barrera": True,
                    "mensaje": "Bienvenido, entrada automática permitida",
                    "usuario": usuario.NOMBRE,
                    "vehiculo": entrada_activa.vehiculo.PLACA if entrada_activa.vehiculo else "N/A",
                    "espacio": entrada_activa.espacio.NUMERO if entrada_activa.espacio else "N/A"
                }), 200
        
        return jsonify({
            "abrir_barrera": False, 
            "razon": "No tiene entrada activa reciente"
        }), 200
        
    except Exception as e:
        print(f"❌ Error en apertura automática: {str(e)}")
        return jsonify({"error": str(e)}), 500
@app.route("/api/barrera/abrir", methods=["POST"])
def abrir_barrera():
    """Endpoint para abrir la barrera manualmente"""
    try:
        print("🚦 COMANDO RECIBIDO: Abrir barrera desde recarga")
        
        # 🆕 Aquí podrías enviar un comando a Arduino via WebSocket, HTTP, etc.
        # Por ahora solo logueamos, pero puedes expandir esta funcionalidad
        
        return jsonify({
            "success": True,
            "mensaje": "Comando de apertura enviado",
            "comando": "ABRIR_BARRERA"
        }), 200
        
    except Exception as e:
        print(f"❌ Error en apertura manual: {str(e)}")
        return jsonify({"error": str(e)}), 500
@app.route("/api/estado-sistema")
def estado_sistema():
    """Estado general del sistema"""
    try:
        total_usuarios = Usuario.query.count()
        total_vehiculos = Vehiculo.query.count()
        entradas_activas = Entrada.query.filter_by(ESTADO="ACTIVA").count()
        espacios_ocupados = Espacio.query.filter_by(ESTADO="OCUPADO").count()
        espacios_disponibles = Espacio.query.filter_by(ESTADO="DISPONIBLE").count()
        
        return jsonify({
            "sistema": "Parqueadero Inteligente",
            "version": "1.0",
            "estado": "OPERATIVO",
            "estadisticas": {
                "total_usuarios": total_usuarios,
                "total_vehiculos": total_vehiculos,
                "entradas_activas": entradas_activas,
                "espacios_ocupados": espacios_ocupados,
                "espacios_disponibles": espacios_disponibles,
                "total_espacios": 3
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route("/api/espacios/estado")
def estado_espacios():
    """Retorna el estado actual de todos los espacios"""
    try:
        espacios = Espacio.query.all()
        resultado = []
        
        for espacio in espacios:
            # Información de la entrada activa si existe
            entrada_info = None
            if espacio.ID_ENTRADA_ACTUAL:
                entrada = Entrada.query.get(espacio.ID_ENTRADA_ACTUAL)
                if entrada:
                    entrada_info = {
                        "usuario": entrada.usuario.NOMBRE,
                        "placa": entrada.vehiculo.PLACA,
                        "hora_entrada": entrada.FECHA_ENTRADA.strftime('%H:%M:%S')
                    }
            
            resultado.append({
                "numero": espacio.NUMERO,
                "tipo": espacio.TIPO_VEHICULO,
                "estado": espacio.ESTADO,
                "sensor_pin": espacio.SENSOR_PIN,
                "ultima_deteccion": espacio.ULTIMA_DETECCION.strftime('%H:%M:%S') if espacio.ULTIMA_DETECCION else None,
                "entrada_actual": entrada_info
            })
        
        return jsonify({"espacios": resultado})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route("/api/historial/entradas")
def historial_entradas():
    """Historial completo de entradas y salidas"""
    try:
        # Parámetros opcionales
        limite = request.args.get('limite', 50, type=int)
        placa = request.args.get('placa', '').upper()
        
        query = Entrada.query
        
        if placa:
            vehiculo = Vehiculo.query.filter_by(PLACA=placa).first()
            if vehiculo:
                query = query.filter_by(ID_VEHICULO=vehiculo.ID)
        
        entradas = query.order_by(Entrada.FECHA_ENTRADA.desc()).limit(limite).all()
        
        resultado = []
        for entrada in entradas:
            resultado.append({
                "id": entrada.ID,
                "usuario": entrada.usuario.NOMBRE,
                "placa": entrada.vehiculo.PLACA,
                "espacio": entrada.espacio.NUMERO if entrada.espacio else "N/A",
                "fecha_entrada": entrada.FECHA_ENTRADA.strftime('%Y-%m-%d %H:%M:%S'),
                "fecha_salida": entrada.FECHA_SALIDA.strftime('%Y-%m-%d %H:%M:%S') if entrada.FECHA_SALIDA else None,
                "estado": entrada.ESTADO,
                "monto_cobrado": float(entrada.MONTO_COBRADO) if entrada.MONTO_COBRADO else None,
                "tiempo_estacionado": entrada.TIEMPO_ESTACIONADO
            })
        
        return jsonify({
            "total": len(resultado),
            "entradas": resultado
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route("/api/historial/recargas")
def historial_recargas():
    """Historial de recargas de saldo"""
    try:
        limite = request.args.get('limite', 50, type=int)
        usuario_id = request.args.get('usuario_id', type=int)
        
        query = Transaccion.query.filter_by(TIPO="RECARGA", ESTADO="CONFIRMADA")
        
        if usuario_id:
            query = query.filter_by(ID_USUARIO=usuario_id)
        
        recargas = query.order_by(Transaccion.FECHA.desc()).limit(limite).all()
        
        resultado = []
        for recarga in recargas:
            usuario = Usuario.query.get(recarga.ID_USUARIO)
            resultado.append({
                "id": recarga.ID,
                "usuario": usuario.NOMBRE if usuario else "N/A",
                "cedula": usuario.CEDULA if usuario else "N/A",
                "monto": float(recarga.MONTO),
                "fecha": recarga.FECHA.strftime('%Y-%m-%d %H:%M:%S'),
                "metodo": "QR"  # Por ahora solo QR
            })
        
        return jsonify({
            "total": len(resultado),
            "recargas": resultado
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route("/api/usuario/placa/<placa>")
def usuario_por_placa(placa):
    """Obtiene información de usuario por placa de vehículo"""
    try:
        vehiculo = Vehiculo.query.filter_by(PLACA=placa.upper()).first()
        if not vehiculo:
            return jsonify({"error": "Vehículo no encontrado"}), 404
        
        usuario = vehiculo.usuario
        entrada_activa = Entrada.query.filter_by(ID_USUARIO=usuario.ID, ESTADO="ACTIVA").first()
        
        return jsonify({
            "usuario": {
                "id": usuario.ID,
                "nombre": usuario.NOMBRE,
                "cedula": usuario.CEDULA,
                "telefono": usuario.TELEFONO,
                "email": usuario.EMAIL,
                "saldo": float(usuario.SALDO),
                "tarjeta_rfid": usuario.TARJETA_RFID
            },
            "vehiculo": {
                "placa": vehiculo.PLACA,
                "tipo": vehiculo.TIPO,
                "marca": vehiculo.MARCA,
                "color": vehiculo.COLOR
            },
            "entrada_activa": {
                "existe": entrada_activa is not None,
                "espacio": entrada_activa.espacio.NUMERO if entrada_activa and entrada_activa.espacio else None,
                "hora_entrada": entrada_activa.FECHA_ENTRADA.strftime('%H:%M:%S') if entrada_activa else None
            } if entrada_activa else None
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route("/api/estadisticas/diarias")
def estadisticas_diarias():
    """Estadísticas de uso del día actual"""
    try:
        hoy = datetime.now().date()
        
        # Entradas de hoy
        entradas_hoy = Entrada.query.filter(
            db.func.date(Entrada.FECHA_ENTRADA) == hoy
        ).count()
        
        # Salidas de hoy
        salidas_hoy = Entrada.query.filter(
            db.func.date(Entrada.FECHA_SALIDA) == hoy,
            Entrada.ESTADO == "FINALIZADA"
        ).count()
        
        # Recaudo de hoy
        recaudo_hoy = db.session.query(db.func.sum(Entrada.MONTO_COBRADO)).filter(
            db.func.date(Entrada.FECHA_SALIDA) == hoy,
            Entrada.ESTADO == "FINALIZADA"
        ).scalar() or 0
        
        # Recargas de hoy
        recargas_hoy = Transaccion.query.filter(
            db.func.date(Transaccion.FECHA) == hoy,
            Transaccion.TIPO == "RECARGA",
            Transaccion.ESTADO == "CONFIRMADA"
        ).count()
        
        return jsonify({
            "fecha": hoy.strftime('%Y-%m-%d'),
            "estadisticas": {
                "entradas_hoy": entradas_hoy,
                "salidas_hoy": salidas_hoy,
                "recaudo_hoy": float(recaudo_hoy),
                "recargas_hoy": recargas_hoy,
                "ocupacion_actual": Espacio.query.filter_by(ESTADO="OCUPADO").count()
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
# 🆕 ENDPOINT PARA GENERAR RECARGA PARA USUARIO EXISTENTE
# 🆕 ENDPOINT PARA GENERAR RECARGA PARA USUARIO EXISTENTE POR PLACA
@app.route("/api/recarga/generar/<placa>")
def generar_recarga_existente(placa):
    """Genera nueva recarga para usuario ya registrado usando placa"""
    try:
        usuario = Usuario.query.filter_by(PLACA=placa).first()
        if not usuario:
            return jsonify({"error": "Usuario no encontrado"}), 404
        
        # Generar token de recarga
        token_recarga = generar_token()
        transaccion_recarga = Transaccion(
            ID_USUARIO=usuario.ID,
            TIPO="RECARGA",
            MONTO=0,  # El usuario elegirá el monto
            ESTADO="PENDIENTE",
            TOKEN=token_recarga
        )
        db.session.add(transaccion_recarga)
        db.session.commit()
        
        # Usando la IP del servidor que muestras
        url_recarga = f"http://10.161.108.244:5000/recarga/{token_recarga}"
        
        return jsonify({
            "success": True,
            "mensaje": "QR de recarga generado",
            "url_recarga": url_recarga,
            "qr_url": f"http://10.161.108.244:5000/qr/recarga/{token_recarga}",
            "usuario": usuario.NOMBRE,
            "placa": usuario.PLACA,
            "saldo_actual": float(usuario.SALDO)
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
# 🆕 ACTUALIZAR LA FUNCIÓN DE INICIALIZACIÓN DE TARIFAS
def inicializar_datos():
    """Inicializa datos básicos del sistema con nuevas tarifas"""
    try:
        db.create_all()
         # 🆕 LIMPIAR DATOS EXISTENTES
        db.drop_all()  # Esto borra todas las tablas
        db.create_all()  # Esto las crea vacías
        
        # Verificar si ya hay datos para no duplicar
        if Tarifa.query.count() == 0:
            # 🆕 TARIFAS ACTUALIZADAS
            tarifas = [
                Tarifa(TIPO_VEHICULO="CARRO", TARIFA_HORA=5000, TARIFA_MINIMA=5000),  # 🆕 CAMBIADO A 5000
                Tarifa(TIPO_VEHICULO="MOTO", TARIFA_HORA=3000, TARIFA_MINIMA=3000),   # 🆕 ACTUALIZADO
            ]
            for tarifa in tarifas:
                db.session.add(tarifa)
        
        if Espacio.query.count() == 0:
            espacios = [
                Espacio(NUMERO="A1", TIPO_VEHICULO="CARRO", ESTADO="DISPONIBLE", SENSOR_PIN=1),
                Espacio(NUMERO="A2", TIPO_VEHICULO="CARRO", ESTADO="DISPONIBLE", SENSOR_PIN=2),
                Espacio(NUMERO="A3", TIPO_VEHICULO="CARRO", ESTADO="DISPONIBLE", SENSOR_PIN=3),
            ]
            for espacio in espacios:
                db.session.add(espacio)
        
        db.session.commit()
        print("✅ Base de datos inicializada correctamente")
        print("✅ 3 espacios para carros creados")
        print("💰 Tarifa mínima actualizada: $5,000")
        
    except Exception as e:
        print(f"⚠️ Error inicializando datos: {e}")
        db.session.rollback()

# 🆕 ACTUALIZAR LA FUNCIÓN QUE OBTIENE LA TARIFA MÍNIMA
def obtener_tarifa_minima():
    """Retorna la tarifa mínima actualizada"""
    tarifa = Tarifa.query.filter_by(TIPO_VEHICULO="CARRO", ACTIVA=True).first()
    return float(tarifa.TARIFA_MINIMA) if tarifa else 5000.0  # 🆕 DEFAULT 5000
if __name__ == "__main__":
    with app.app_context():
        inicializar_datos()
    
    print("🚀 Sistema de Parqueadero Inteligente Iniciado")
    print("📍 Versión 4.1 - Con relaciones SQLAlchemy corregidas")
    print("📍 Endpoints principales:")
    print("   POST /api/entrada/detectar - Detectar vehículo y tarjeta")
    print("   POST /api/salida/detectar  - Procesar salida de vehículo") 
    print("   GET  /api/espacios/estado  - Estado de espacios")
    print("   GET  /registro/<token>     - Página de registro con QR")
    print("   GET  /recarga/<token>      - Página de recarga con QR")
    
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)