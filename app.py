import streamlit as st
import sqlite3
import pandas as pd
import os
import subprocess
import json
import hashlib
import hmac
import shutil
import requests
from datetime import datetime

# ==========================================
# 1. CONFIGURACIÓN Y CREDENCIALES
# ==========================================
SUPABASE_URL = "https://piadjbkvauzodufbhwea.supabase.co/rest/v1/licencias"
SUPABASE_KEY = "sb_publishable_DpklfHQzUWFWttV953VoEQ_oj0rDXrM"
LINK_PAGO = "https://mpago.la/1Y3w9Yb"
CLAVE_MAESTRA = "LavaGest_Secret_Key_2026_Secure"
PIN_TECNICO = "9999"

st.set_page_config(page_title="LavaGest - Sistema de Lavanderia", layout="wide")

# ==========================================
# 2. SEGURIDAD, HWID Y LICENCIA
# ==========================================
def obtener_hwid():
    try:
        cmd = 'powershell -command "(Get-CimInstance -Class Win32_ComputerSystemProduct).UUID"'
        uuid = subprocess.check_output(cmd, shell=True).decode().strip()
        if not uuid:
            uuid = subprocess.check_output('wmic csproduct get uuid', shell=True).decode().split('\n')[1].strip()
        return uuid
    except Exception:
        return "HWID-ERROR-INDETERMINADO"

def firmar_datos(texto):
    return hmac.new(CLAVE_MAESTRA.encode(), texto.encode(), hashlib.sha256).hexdigest()

def guardar_cache_licencia(hwid, fecha_venc, estado):
    datos = f"{hwid}|{fecha_venc}|{estado}"
    firma = firmar_datos(datos)
    with open("licencia.dat", "w") as f:
        json.dump({"data": datos, "firma": firma}, f)

def leer_cache_licencia():
    if not os.path.exists("licencia.dat"):
        return None, None, False
    try:
        with open("licencia.dat", "r") as f:
            contenido = json.load(f)
        datos = contenido["data"]
        if firmar_datos(datos) != contenido["firma"]:
            return None, None, False
        hwid, fecha_venc, estado = datos.split("|")
        return hwid, fecha_venc, (estado == "ACTIVO")
    except Exception:
        return None, None, False

def verificar_licencia():
    hwid = obtener_hwid()
    
    # 1. Verificación Online en Supabase
    try:
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        res = requests.get(f"{SUPABASE_URL}?hwid=eq.{hwid}", headers=headers, timeout=4)
        if res.status_code == 200 and len(res.json()) > 0:
            reg = res.json()[0]
            fecha_venc = reg["fecha_vencimiento"]
            estado = reg["estado"]
            
            guardar_cache_licencia(hwid, fecha_venc, estado)
            fecha_dt = datetime.strptime(fecha_venc, "%Y-%m-%d")
            
            if datetime.now() > fecha_dt or estado != "ACTIVO":
                return False, f"Suscripción vencida el {fecha_venc}.", hwid
            return True, f"Licencia Activa (En linea - Vence: {fecha_venc})", hwid
    except Exception:
        pass

    # 2. Verificación Offline (Caché local)
    hwid_c, fecha_c, estado_c = leer_cache_licencia()
    if not hwid_c or hwid_c != hwid:
        return False, "Requiere conexión a internet para la activación inicial.", hwid
    if not estado_c:
        return False, "Servicio suspendido.", hwid
        
    fecha_dt = datetime.strptime(fecha_c, "%Y-%m-%d")
    if datetime.now() > fecha_dt:
        return False, f"Servicio vencido el {fecha_c}. Conecta a internet tras realizar tu pago.", hwid
        
    return True, f"Modo Offline Activo (Vence: {fecha_c})", hwid

# ==========================================
# 3. MANTENIMIENTO INVISIBLE EN SEGUNDO PLANO
# ==========================================
def ejecucion_mantenimiento_invisible():
    try:
        if os.path.exists("lavanderia.db"):
            carpeta = "backups_sistema"
            if not os.path.exists(carpeta):
                os.makedirs(carpeta)
            hoy = datetime.now().strftime("%Y%m%d")
            dest = os.path.join(carpeta, f"backup_{hoy}.bak")
            if not os.path.exists(dest):
                shutil.copy("lavanderia.db", dest)
                
            conn = sqlite3.connect("lavanderia.db")
            conn.execute("PRAGMA optimize;")
            conn.execute("PRAGMA integrity_check;")
            conn.close()
    except Exception:
        pass

ejecucion_mantenimiento_invisible()

# ==========================================
# 4. CONTROL DE ACCESO (PANTALLA DE BLOQUEO)
# ==========================================
valida, msg_lic, hwid_equipo = verificar_licencia()

if not valida:
    st.error("ACCESO RESTRINGIDO - LAVAGEST")
    st.warning(f"Estado del servicio: {msg_lic}")
    st.markdown(f"**Para reactivar tu servicio, realiza tu pago aqui:** [Pagar Mensualidad en Mercado Pago]({LINK_PAGO})")
    st.divider()
    st.info("Proporciona este ID de Hardware al soporte técnico si requieres activación manual:")
    st.code(hwid_equipo, language="text")
    st.stop()

# ==========================================
# 5. INICIALIZACIÓN BASE DE DATOS LOCAL
# ==========================================
def obtener_conexion():
    conn = sqlite3.connect("lavanderia.db")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pedidos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente TEXT NOT NULL,
            servicio TEXT NOT NULL,
            monto REAL NOT NULL,
            estado TEXT DEFAULT 'Pendiente',
            fecha TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS caja (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL,
            concepto TEXT NOT NULL,
            monto REAL NOT NULL,
            fecha TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn

obtener_conexion().close()

# ==========================================
# 6. INTERFAZ PRINCIPAL DE LAVAGEST
# ==========================================
st.sidebar.title("LavaGest")
st.sidebar.caption(msg_lic)

opcion = st.sidebar.radio("Navegacion", ["Recepcion y Tickets", "Entregas y Operacion", "Caja de Turno", "Mantenimiento Tecnico"])

# --- RECEPCIÓN Y TICKETS ---
if opcion == "Recepcion y Tickets":
    st.header("Captura de Nuevo Pedido y Generación de Ticket")
    
    col_form, col_ticket = st.columns([1, 1])
    
    with col_form:
        with st.form("form_pedido", clear_on_submit=False):
            cliente = st.text_input("Nombre del Cliente")
            servicio = st.selectbox("Servicio", ["Encargo por KG", "Edredon / Cobertores", "Planchado", "Servicio Especial"])
            monto = st.number_input("Total a Cobrar ($)", min_value=0.0, step=10.0)
            guardar = st.form_submit_button("Guardar Pedido y Generar Ticket")
            
            if guardar:
                if cliente and monto > 0:
                    conn = obtener_conexion()
                    cursor = conn.cursor()
                    fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    cursor.execute("INSERT INTO pedidos (cliente, servicio, monto, estado, fecha) VALUES (?, ?, ?, 'Pendiente', ?)",
                                   (cliente, servicio, monto, fecha_actual))
                    nuevo_id = cursor.lastrowid
                    conn.commit()
                    conn.close()
                    
                    st.session_state['ultimo_ticket'] = {
                        'id': nuevo_id,
                        'cliente': cliente,
                        'servicio': servicio,
                        'monto': monto,
                        'fecha': fecha_actual
                    }
                    st.success(f"Pedido #{nuevo_id} registrado correctamente.")
                else:
                    st.error("Ingresa un nombre de cliente y un monto valido.")

    with col_ticket:
        st.subheader("Vista Previa del Ticket")
        if 'ultimo_ticket' in st.session_state:
            t = st.session_state['ultimo_ticket']
            ticket_texto = f"""
========================================
            LAVAGEST - TICKET
========================================
Folio: #{t['id']}
Fecha: {t['fecha']}
Cliente: {t['cliente']}
Servicio: {t['servicio']}
Total: ${t['monto']:.2f} MXN
Estado: Pendiente
========================================
    Conserve este ticket para entregar
          su ropa. ¡Gracias!
========================================
"""
            st.code(ticket_texto, language="text")
        else:
            st.info("Registra un pedido para visualizar el ticket digital aqui.")

# --- ENTREGAS Y OPERACIÓN ---
elif opcion == "Entregas y Operacion":
    st.header("Gestion de Entregas y Pedidos Activos")
    conn = obtener_conexion()
    df_pedidos = pd.read_sql_query("SELECT id AS Folio, cliente AS Cliente, servicio AS Servicio, monto AS Monto, estado AS Estado, fecha AS Fecha FROM pedidos WHERE estado != 'Entregado' ORDER BY id DESC", conn)
    
    if not df_pedidos.empty:
        st.dataframe(df_pedidos, use_container_width=True)
        
        col_id, col_btn = st.columns([1, 2])
        pedido_id = col_id.number_input("Folio del Pedido a Entregar", min_value=1, step=1)
        
        if col_btn.button("Cobrar y Marcar como Entregado"):
            cursor = conn.cursor()
            cursor.execute("SELECT monto, cliente FROM pedidos WHERE id = ?", (pedido_id,))
            res = cursor.fetchone()
            if res:
                monto_ped, nom_cli = res
                fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute("UPDATE pedidos SET estado = 'Entregado' WHERE id = ?", (pedido_id,))
                cursor.execute("INSERT INTO caja (tipo, concepto, monto, fecha) VALUES ('INGRESO', ?, ?, ?)",
                               (f"Cobro Pedido #{pedido_id} - {nom_cli}", monto_ped, fecha_actual))
                conn.commit()
                st.success(f"Pedido #{pedido_id} entregado y cobrado en caja.")
                st.rerun()
            else:
                st.error("Folio no encontrado.")
    else:
        st.info("No hay pedidos pendientes por entregar en este momento.")
    conn.close()

# --- CAJA DE TURNO ---
elif opcion == "Caja de Turno":
    st.header("Caja de Turno y Control de Gastos")
    conn = obtener_conexion()
    df_caja = pd.read_sql_query("SELECT id AS ID, tipo AS Tipo, concepto AS Concepto, monto AS Monto, fecha AS Fecha FROM caja ORDER BY id DESC", conn)
    
    total_ingresos = df_caja[df_caja['Tipo'] == 'INGRESO']['Monto'].sum() if not df_caja.empty else 0.0
    total_egresos = df_caja[df_caja['Tipo'] == 'EGRESO']['Monto'].sum() if not df_caja.empty else 0.0
    balance = total_ingresos - total_egresos
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Ingresos Totales", f"${total_ingresos:.2f} MXN")
    c2.metric("Gastos / Egresos", f"${total_egresos:.2f} MXN")
    c3.metric("Efectivo en Caja", f"${balance:.2f} MXN")
    
    st.divider()
    st.subheader("Registrar Gasto del Local")
    with st.form("form_gasto", clear_on_submit=True):
        concepto = st.text_input("Concepto del Gasto (ej. Jabon, Insumos, Renta)")
        monto_gasto = st.number_input("Monto del Gasto ($)", min_value=0.0, step=5.0)
        if st.form_submit_button("Registrar Gasto"):
            if concepto and monto_gasto > 0:
                fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                conn.execute("INSERT INTO caja (tipo, concepto, monto, fecha) VALUES ('EGRESO', ?, ?, ?)",
                             (concepto, monto_gasto, fecha_actual))
                conn.commit()
                st.success("Gasto registrado correctamente.")
                st.rerun()
    
    st.subheader("Historial de Movimientos de Caja")
    st.dataframe(df_caja, use_container_width=True)
    conn.close()

# --- MANTENIMIENTO TÉCNICO ---
elif opcion == "Mantenimiento Tecnico":
    st.header("Panel de Diagnostico y Soporte Tecnico")
    pin = st.text_input("Ingresa el PIN Tecnico", type="password")
    
    if pin == PIN_TECNICO:
        st.success("Acceso Tecnico Concedido")
        st.subheader("Identificacion de Hardware")
        st.code(hwid_equipo, language="text")
        
        st.divider()
        st.subheader("Mantenimiento de Base de Datos")
        if os.path.exists("lavanderia.db"):
            tam_mb = os.path.getsize("lavanderia.db") / (1024 * 1024)
            st.metric("Tamaño de lavanderia.db", f"{tam_mb:.2f} MB")
            
            c_act1, c_act2 = st.columns(2)
            if c_act1.button("Crear Respaldo Manual (.bak)"):
                hoy = datetime.now().strftime("%Y%m%d_%H%M%S")
                shutil.copy("lavanderia.db", f"manual_backup_{hoy}.bak")
                st.success("Respaldo manual creado con exito.")
                
            if c_act2.button("Depurar y Compactar (VACUUM)"):
                conn = obtener_conexion()
                conn.execute("VACUUM;")
                conn.close()
                st.success("Base de datos optimizada.")
                st.rerun()