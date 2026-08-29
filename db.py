"""
db.py
Capa de acceso a datos para el CRM de seguros.
Usa PostgreSQL a través de Supabase: una base de datos permanente en
la nube (a diferencia del SQLite local anterior, estos datos NO se
borran cuando el servidor de Streamlit se reinicia).
"""

import os
from datetime import date, datetime, timedelta

import psycopg2
import psycopg2.extras


def get_connection():
    host = os.environ.get("SUPABASE_HOST")
    port = os.environ.get("SUPABASE_PORT", "5432")
    dbname = os.environ.get("SUPABASE_DB", "postgres")
    user = os.environ.get("SUPABASE_USER")
    password = os.environ.get("SUPABASE_PASSWORD")

    if not all([host, user, password]):
        raise RuntimeError(
            "Faltan datos de conexión a Supabase. Configurá en el archivo .env "
            "(o en 'Secrets' en Streamlit Cloud): SUPABASE_HOST, SUPABASE_PORT, "
            "SUPABASE_DB, SUPABASE_USER y SUPABASE_PASSWORD."
        )

    conn = psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
        cursor_factory=psycopg2.extras.RealDictCursor,
        connect_timeout=10,
    )
    return conn


def init_db():
    """Crea las tablas si no existen. Se llama una vez al arrancar la app."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS clientes (
            id SERIAL PRIMARY KEY,
            tipo_persona TEXT CHECK(tipo_persona IN ('Fisica','Juridica')) DEFAULT 'Fisica',
            nombre_razon_social TEXT NOT NULL,
            cuit_dni TEXT UNIQUE NOT NULL,
            telefono TEXT,
            email TEXT,
            direccion TEXT,
            forma_pago TEXT CHECK(forma_pago IN ('Debito Automatico','CBU','Tarjeta de Credito','Cuponera','Mercado Pago')),
            banco_emisor TEXT,
            marca_tarjeta TEXT,
            ultimos_4_digitos TEXT,
            vencimiento_tarjeta TEXT,
            cbu_cvu TEXT,
            fecha_alta TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS polizas (
            id SERIAL PRIMARY KEY,
            cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
            compania_aseguradora TEXT,
            numero_poliza TEXT,
            ramo TEXT,
            riesgo_patente TEXT,
            vigencia_desde TEXT,
            vigencia_hasta TEXT,
            importe_total REAL,
            cantidad_cuotas INTEGER DEFAULT 1,
            estado TEXT CHECK(estado IN ('Activa','Vencida','Anulada','Renovada')) DEFAULT 'Activa',
            pdf_path TEXT,
            fecha_carga TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS cuotas (
            id SERIAL PRIMARY KEY,
            poliza_id INTEGER NOT NULL REFERENCES polizas(id) ON DELETE CASCADE,
            numero_cuota INTEGER,
            monto REAL,
            fecha_vencimiento TEXT,
            fecha_pago TEXT,
            estado TEXT CHECK(estado IN ('Pendiente','Pagada','Vencida')) DEFAULT 'Pendiente'
        );

        CREATE TABLE IF NOT EXISTS alertas (
            id SERIAL PRIMARY KEY,
            poliza_id INTEGER NOT NULL REFERENCES polizas(id) ON DELETE CASCADE,
            tipo TEXT CHECK(tipo IN ('Vencimiento_Poliza','Vencimiento_Cuota')),
            dias_anticipacion INTEGER,
            fecha_alerta TEXT,
            enviada INTEGER DEFAULT 0,
            fecha_envio TEXT
        );
        """
    )
    conn.commit()
    cur.close()
    conn.close()


# ---------------------------------------------------------------------------
# CLIENTES
# ---------------------------------------------------------------------------

def buscar_cliente_por_cuit(cuit_dni: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM clientes WHERE cuit_dni = %s", (cuit_dni,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return dict(row) if row else None


def upsert_cliente(nombre, cuit_dni, telefono=None, email=None,
                    tipo_persona="Fisica", direccion=None,
                    forma_pago=None, banco_emisor=None, marca_tarjeta=None,
                    ultimos_4_digitos=None, vencimiento_tarjeta=None, cbu_cvu=None):
    """
    Vinculación automática por CUIT/DNI:
    - Si el cliente existe -> actualiza datos de contacto y medio de pago, devuelve su id.
    - Si no existe -> lo crea.
    Nota de seguridad: NUNCA se guarda el número completo de tarjeta ni el
    código de seguridad (CVV). Solo los últimos 4 dígitos, suficientes para
    identificarla en una gestión de cobranza.
    """
    existente = buscar_cliente_por_cuit(cuit_dni)
    conn = get_connection()
    cur = conn.cursor()

    if existente:
        cur.execute(
            """UPDATE clientes
               SET nombre_razon_social = COALESCE(%s, nombre_razon_social),
                   telefono = COALESCE(%s, telefono),
                   email = COALESCE(%s, email),
                   direccion = COALESCE(%s, direccion),
                   forma_pago = COALESCE(%s, forma_pago),
                   banco_emisor = COALESCE(%s, banco_emisor),
                   marca_tarjeta = COALESCE(%s, marca_tarjeta),
                   ultimos_4_digitos = COALESCE(%s, ultimos_4_digitos),
                   vencimiento_tarjeta = COALESCE(%s, vencimiento_tarjeta),
                   cbu_cvu = COALESCE(%s, cbu_cvu)
               WHERE cuit_dni = %s""",
            (nombre, telefono, email, direccion, forma_pago, banco_emisor,
             marca_tarjeta, ultimos_4_digitos, vencimiento_tarjeta, cbu_cvu, cuit_dni),
        )
        conn.commit()
        cliente_id = existente["id"]
    else:
        cur.execute(
            """INSERT INTO clientes
               (tipo_persona, nombre_razon_social, cuit_dni, telefono, email, direccion,
                forma_pago, banco_emisor, marca_tarjeta, ultimos_4_digitos,
                vencimiento_tarjeta, cbu_cvu)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (tipo_persona, nombre, cuit_dni, telefono, email, direccion,
             forma_pago, banco_emisor, marca_tarjeta, ultimos_4_digitos,
             vencimiento_tarjeta, cbu_cvu),
        )
        cliente_id = cur.fetchone()["id"]
        conn.commit()

    cur.close()
    conn.close()
    return cliente_id


def listar_clientes(filtro: str = ""):
    conn = get_connection()
    cur = conn.cursor()
    if filtro:
        cur.execute(
            """SELECT * FROM clientes
               WHERE nombre_razon_social ILIKE %s OR cuit_dni ILIKE %s
               ORDER BY nombre_razon_social""",
            (f"%{filtro}%", f"%{filtro}%"),
        )
    else:
        cur.execute("SELECT * FROM clientes ORDER BY nombre_razon_social")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


def historial_polizas_cliente(cliente_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM polizas WHERE cliente_id = %s ORDER BY vigencia_hasta DESC",
        (cliente_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# POLIZAS
# ---------------------------------------------------------------------------

def insertar_poliza(cliente_id, compania, numero_poliza, ramo, riesgo_patente,
                     vigencia_desde, vigencia_hasta, importe_total,
                     cantidad_cuotas, pdf_path=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO polizas
           (cliente_id, compania_aseguradora, numero_poliza, ramo, riesgo_patente,
            vigencia_desde, vigencia_hasta, importe_total, cantidad_cuotas, pdf_path)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (cliente_id, compania, numero_poliza, ramo, riesgo_patente,
         vigencia_desde, vigencia_hasta, importe_total, cantidad_cuotas, pdf_path),
    )
    poliza_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()

    generar_cuotas(poliza_id, importe_total, cantidad_cuotas, vigencia_desde)
    generar_alertas_poliza(poliza_id, vigencia_hasta)
    return poliza_id


def generar_cuotas(poliza_id, importe_total, cantidad_cuotas, vigencia_desde):
    """Genera cuotas mensuales iguales a partir de la fecha de inicio de vigencia."""
    if not importe_total or not cantidad_cuotas:
        return
    monto_cuota = round(importe_total / cantidad_cuotas, 2)
    try:
        fecha_inicio = datetime.strptime(vigencia_desde, "%Y-%m-%d")
    except (ValueError, TypeError):
        fecha_inicio = datetime.today()

    conn = get_connection()
    cur = conn.cursor()
    for i in range(cantidad_cuotas):
        # aproximación simple de mes calendario (+30 días por cuota)
        fecha_venc = fecha_inicio + timedelta(days=30 * (i + 1))
        cur.execute(
            """INSERT INTO cuotas (poliza_id, numero_cuota, monto, fecha_vencimiento, estado)
               VALUES (%s, %s, %s, %s, 'Pendiente')""",
            (poliza_id, i + 1, monto_cuota, fecha_venc.strftime("%Y-%m-%d")),
        )
    conn.commit()
    cur.close()
    conn.close()


def generar_alertas_poliza(poliza_id, vigencia_hasta):
    """Crea registros de alerta a 30, 15 y 7 días del vencimiento de la póliza."""
    try:
        fecha_venc = datetime.strptime(vigencia_hasta, "%Y-%m-%d")
    except (ValueError, TypeError):
        return

    conn = get_connection()
    cur = conn.cursor()
    for dias in (30, 15, 7):
        fecha_alerta = fecha_venc - timedelta(days=dias)
        cur.execute(
            """INSERT INTO alertas (poliza_id, tipo, dias_anticipacion, fecha_alerta)
               VALUES (%s, 'Vencimiento_Poliza', %s, %s)""",
            (poliza_id, dias, fecha_alerta.strftime("%Y-%m-%d")),
        )
    conn.commit()
    cur.close()
    conn.close()


def listar_polizas_dashboard():
    """
    Devuelve todas las pólizas con los días restantes hasta el vencimiento,
    para armar el tablero de colores (Verde / Amarillo / Rojo / Gris-vencida).
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT p.*, c.nombre_razon_social, c.cuit_dni, c.telefono, c.email
           FROM polizas p
           JOIN clientes c ON c.id = p.cliente_id
           ORDER BY p.vigencia_hasta ASC"""
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    resultado = []
    hoy = date.today()
    for r in rows:
        d = dict(r)
        try:
            venc = datetime.strptime(d["vigencia_hasta"], "%Y-%m-%d").date()
            dias_restantes = (venc - hoy).days
        except (ValueError, TypeError):
            dias_restantes = None
        d["dias_restantes"] = dias_restantes

        if dias_restantes is None:
            d["color"] = "gris"
        elif dias_restantes < 0:
            d["color"] = "gris"  # vencida
        elif dias_restantes <= 15:
            d["color"] = "rojo"
        elif dias_restantes <= 30:
            d["color"] = "amarillo"
        else:
            d["color"] = "verde"
        resultado.append(d)
    return resultado


def actualizar_estado_poliza(poliza_id, nuevo_estado):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE polizas SET estado = %s WHERE id = %s", (nuevo_estado, poliza_id))
    conn.commit()
    cur.close()
    conn.close()


def eliminar_poliza(poliza_id):
    """Elimina la póliza y, en cascada, sus cuotas y alertas asociadas."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM polizas WHERE id = %s", (poliza_id,))
    conn.commit()
    cur.close()
    conn.close()


def obtener_poliza_por_id(poliza_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM polizas WHERE id = %s", (poliza_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return dict(row) if row else None


def renovar_poliza(poliza_id, numero_poliza, vigencia_desde, vigencia_hasta,
                    importe_total, cantidad_cuotas):
    """
    Marca la póliza actual como 'Renovada' (se conserva en el historial) y
    crea una póliza nueva para el período siguiente, reutilizando los datos
    del cliente, compañía, ramo y riesgo/patente.
    """
    vieja = obtener_poliza_por_id(poliza_id)
    if not vieja:
        raise ValueError("No se encontró la póliza a renovar.")

    actualizar_estado_poliza(poliza_id, "Renovada")

    nueva_id = insertar_poliza(
        cliente_id=vieja["cliente_id"],
        compania=vieja["compania_aseguradora"],
        numero_poliza=numero_poliza,
        ramo=vieja["ramo"],
        riesgo_patente=vieja["riesgo_patente"],
        vigencia_desde=vigencia_desde,
        vigencia_hasta=vigencia_hasta,
        importe_total=importe_total,
        cantidad_cuotas=cantidad_cuotas,
        pdf_path=vieja["pdf_path"],
    )
    return nueva_id


# ---------------------------------------------------------------------------
# MÉTRICAS DEL DASHBOARD
# ---------------------------------------------------------------------------

def metricas_generales():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS total FROM clientes")
    total_clientes = cur.fetchone()["total"]

    cur.execute(
        """SELECT COUNT(*) AS cantidad,
                  COALESCE(SUM(importe_total), 0) AS suma,
                  COALESCE(AVG(importe_total), 0) AS promedio
           FROM polizas WHERE estado = 'Activa'"""
    )
    row = cur.fetchone()
    cur.close()
    conn.close()

    return {
        "total_clientes": total_clientes,
        "polizas_vigentes": row["cantidad"],
        "prima_total": float(row["suma"]),
        "prima_promedio": float(row["promedio"]),
    }


def distribucion_por_ramo():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT COALESCE(NULLIF(ramo, ''), 'Sin especificar') AS ramo, COUNT(*) AS cantidad
           FROM polizas WHERE estado = 'Activa'
           GROUP BY ramo ORDER BY cantidad DESC"""
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


def distribucion_por_aseguradora():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT COALESCE(NULLIF(compania_aseguradora, ''), 'Sin especificar') AS compania_aseguradora,
                  COUNT(*) AS cantidad
           FROM polizas WHERE estado = 'Activa'
           GROUP BY compania_aseguradora ORDER BY cantidad DESC"""
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# BACKUP / EXPORTACIÓN
# ---------------------------------------------------------------------------

def obtener_todos_los_clientes():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM clientes ORDER BY nombre_razon_social")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


def obtener_todas_las_polizas():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT p.*, c.nombre_razon_social, c.cuit_dni
           FROM polizas p
           JOIN clientes c ON c.id = p.cliente_id
           ORDER BY p.vigencia_hasta"""
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


def obtener_todas_las_cuotas():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT cu.*, p.numero_poliza, c.nombre_razon_social
           FROM cuotas cu
           JOIN polizas p ON p.id = cu.poliza_id
           JOIN clientes c ON c.id = p.cliente_id
           ORDER BY cu.fecha_vencimiento"""
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# COBRANZAS (CUOTAS)
# ---------------------------------------------------------------------------

def listar_cuotas_pendientes():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT cu.*, p.numero_poliza, p.compania_aseguradora, c.nombre_razon_social, c.telefono
           FROM cuotas cu
           JOIN polizas p ON p.id = cu.poliza_id
           JOIN clientes c ON c.id = p.cliente_id
           WHERE cu.estado != 'Pagada'
           ORDER BY cu.fecha_vencimiento ASC"""
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    hoy = date.today()
    resultado = []
    for r in rows:
        d = dict(r)
        try:
            venc = datetime.strptime(d["fecha_vencimiento"], "%Y-%m-%d").date()
            if venc < hoy and d["estado"] == "Pendiente":
                d["estado"] = "Vencida"
        except (ValueError, TypeError):
            pass
        resultado.append(d)
    return resultado


def marcar_cuota_pagada(cuota_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE cuotas SET estado = 'Pagada', fecha_pago = %s WHERE id = %s",
        (date.today().strftime("%Y-%m-%d"), cuota_id),
    )
    conn.commit()
    cur.close()
    conn.close()
