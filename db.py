"""
db.py
Capa de acceso a datos para el CRM de seguros.
Usa PostgreSQL a través de Supabase: una base de datos permanente en
la nube (a diferencia del SQLite local anterior, estos datos NO se
borran cuando el servidor de Streamlit se reinicia).
"""

import os
import unicodedata
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

        CREATE TABLE IF NOT EXISTS siniestros (
            id SERIAL PRIMARY KEY,
            cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
            poliza_id INTEGER REFERENCES polizas(id) ON DELETE SET NULL,
            tipo_siniestro TEXT,
            fecha_siniestro TEXT,
            descripcion TEXT,
            numero_denuncia TEXT,
            estado TEXT CHECK(estado IN ('Denunciado','En revision','Pendiente liquidacion','Cerrado','Rechazado')) DEFAULT 'Denunciado',
            fecha_carga TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS interacciones (
            id SERIAL PRIMARY KEY,
            cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
            tipo_evento TEXT CHECK(tipo_evento IN ('Reunion','Llamada/WhatsApp','Cotizacion enviada','Nota interna')),
            ramo_producto TEXT,
            monto_cotizado REAL,
            resultado TEXT CHECK(resultado IN ('Aceptada','Rechazada por precio','Pendiente de decision','Sin respuesta') OR resultado IS NULL),
            detalle TEXT,
            fecha TEXT,
            fecha_carga TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS tareas (
            id SERIAL PRIMARY KEY,
            cliente_id INTEGER REFERENCES clientes(id) ON DELETE SET NULL,
            titulo TEXT NOT NULL,
            fecha_limite TEXT,
            prioridad TEXT CHECK(prioridad IN ('Alta','Media','Baja')) DEFAULT 'Media',
            estado TEXT CHECK(estado IN ('Pendiente','En proceso','Completada')) DEFAULT 'Pendiente',
            fecha_carga TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS oportunidades (
            id SERIAL PRIMARY KEY,
            nombre_prospecto TEXT NOT NULL,
            telefono TEXT,
            email TEXT,
            origen TEXT CHECK(origen IN ('Referido','Redes sociales','Web','Cartera fria','Otro')),
            ramo_interes TEXT,
            monto_estimado REAL,
            etapa TEXT CHECK(etapa IN ('Lead','Contactado','Cotizacion enviada','Negociacion','Cerrado','Perdido')) DEFAULT 'Lead',
            motivo_perdida TEXT,
            notas TEXT,
            cliente_id INTEGER REFERENCES clientes(id) ON DELETE SET NULL,
            fecha_carga TIMESTAMP DEFAULT NOW(),
            fecha_actualizacion TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS notas_ramo (
            id SERIAL PRIMARY KEY,
            ramo TEXT NOT NULL,
            contenido TEXT NOT NULL,
            fecha_carga TIMESTAMP DEFAULT NOW()
        );
        """
    )
    # Migración: agrega columnas nuevas a tablas que ya existían de versiones anteriores
    cur.execute("ALTER TABLE siniestros ADD COLUMN IF NOT EXISTS numero_denuncia TEXT;")
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
               SET nombre_razon_social = COALESCE(NULLIF(%s, ''), nombre_razon_social),
                   telefono = COALESCE(NULLIF(%s, ''), telefono),
                   email = COALESCE(NULLIF(%s, ''), email),
                   direccion = COALESCE(NULLIF(%s, ''), direccion),
                   forma_pago = COALESCE(NULLIF(%s, ''), forma_pago),
                   banco_emisor = COALESCE(NULLIF(%s, ''), banco_emisor),
                   marca_tarjeta = COALESCE(NULLIF(%s, ''), marca_tarjeta),
                   ultimos_4_digitos = COALESCE(NULLIF(%s, ''), ultimos_4_digitos),
                   vencimiento_tarjeta = COALESCE(NULLIF(%s, ''), vencimiento_tarjeta),
                   cbu_cvu = COALESCE(NULLIF(%s, ''), cbu_cvu)
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


def actualizar_datos_cliente(cliente_id, nombre, cuit_dni, telefono, email, direccion,
                              tipo_persona, forma_pago, banco_emisor, marca_tarjeta,
                              ultimos_4_digitos, vencimiento_tarjeta, cbu_cvu):
    """
    Edita directamente los datos de un cliente ya existente (a diferencia de
    upsert_cliente, que solo actualiza campos vacíos al cargar una póliza,
    esta función permite corregir cualquier dato en cualquier momento,
    incluyendo el CUIT/DNI — útil para reemplazar el CUIT temporal que se
    genera al convertir un lead del Pipeline en cliente).
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """UPDATE clientes
           SET nombre_razon_social = %s, cuit_dni = %s, telefono = %s, email = %s,
               direccion = %s, tipo_persona = %s, forma_pago = %s, banco_emisor = %s,
               marca_tarjeta = %s, ultimos_4_digitos = %s, vencimiento_tarjeta = %s,
               cbu_cvu = %s
           WHERE id = %s""",
        (nombre, cuit_dni, telefono or None, email or None, direccion or None,
         tipo_persona, forma_pago or None, banco_emisor or None, marca_tarjeta or None,
         ultimos_4_digitos or None, vencimiento_tarjeta or None, cbu_cvu or None, cliente_id),
    )
    conn.commit()
    cur.close()
    conn.close()


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


def actualizar_poliza(poliza_id, compania, numero_poliza, ramo, riesgo_patente,
                       vigencia_desde, vigencia_hasta, importe_total,
                       cantidad_cuotas, estado):
    """
    Edita los datos de una póliza ya cargada. No recalcula las cuotas
    automáticamente (para no alterar cuotas que ya puedan estar pagadas);
    si cambia el importe o la cantidad de cuotas de forma sustancial,
    conviene revisar el detalle de cuotas por separado.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """UPDATE polizas
           SET compania_aseguradora = %s,
               numero_poliza = %s,
               ramo = %s,
               riesgo_patente = %s,
               vigencia_desde = %s,
               vigencia_hasta = %s,
               importe_total = %s,
               cantidad_cuotas = %s,
               estado = %s
           WHERE id = %s""",
        (compania, numero_poliza, ramo, riesgo_patente, vigencia_desde,
         vigencia_hasta, importe_total, cantidad_cuotas, estado, poliza_id),
    )
    conn.commit()
    cur.close()
    conn.close()


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


_MARCAS_ASEGURADORAS_CONOCIDAS = [
    "ALLIANZ", "ZURICH", "FEDERACION PATRONAL", "SANCOR", "LA CAJA",
    "RIVADAVIA", "SAN CRISTOBAL", "MERCANTIL ANDINA", "NACION SEGUROS",
    "PROVINCIA SEGUROS", "HDI", "ORBIS", "RUS", "MAPFRE", "MERIDIONAL",
    "BOSTON", "PRUDENCIA", "GALICIA SEGUROS", "SMG SEGUROS", "COOPERACION MUTUAL",
    "SURA", "EXPERTA", "ASOCIART",
]


def _limpiar_nombre_aseguradora(nombre):
    """
    Normaliza el nombre de una aseguradora para agrupar variantes del mismo
    nombre en los gráficos (mayúsculas, sin espacios extra, sin acentos, y
    reducido a la marca conocida si corresponde, ej: "Allianz Argentina
    Compañía de Seguros S.A." y "ALLIANZ ARGENTINA COMPANIA DE SEGUROS S.A."
    quedan ambas como "ALLIANZ").
    """
    if not nombre or not nombre.strip():
        return "Sin especificar"

    texto = nombre.strip().upper()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))

    for marca in _MARCAS_ASEGURADORAS_CONOCIDAS:
        if marca in texto:
            return marca
    return texto


def distribucion_por_aseguradora():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT compania_aseguradora FROM polizas WHERE estado = 'Activa'")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    conteo = {}
    for r in rows:
        nombre_limpio = _limpiar_nombre_aseguradora(r["compania_aseguradora"])
        conteo[nombre_limpio] = conteo.get(nombre_limpio, 0) + 1

    resultado = [
        {"compania_aseguradora": nombre, "cantidad": cantidad}
        for nombre, cantidad in conteo.items()
    ]
    resultado.sort(key=lambda x: x["cantidad"], reverse=True)
    return resultado


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


# ---------------------------------------------------------------------------
# SINIESTROS
# ---------------------------------------------------------------------------

def insertar_siniestro(cliente_id, poliza_id, tipo_siniestro, fecha_siniestro,
                        descripcion, numero_denuncia=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO siniestros (cliente_id, poliza_id, tipo_siniestro, fecha_siniestro,
                                    descripcion, numero_denuncia)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
        (cliente_id, poliza_id, tipo_siniestro, fecha_siniestro, descripcion, numero_denuncia),
    )
    siniestro_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return siniestro_id


def listar_siniestros():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT s.*, c.nombre_razon_social, c.cuit_dni, c.telefono,
                  p.numero_poliza, p.compania_aseguradora
           FROM siniestros s
           JOIN clientes c ON c.id = s.cliente_id
           LEFT JOIN polizas p ON p.id = s.poliza_id
           ORDER BY s.fecha_siniestro DESC"""
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


def listar_siniestros_cliente(cliente_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT s.*, p.numero_poliza, p.compania_aseguradora
           FROM siniestros s
           LEFT JOIN polizas p ON p.id = s.poliza_id
           WHERE s.cliente_id = %s
           ORDER BY s.fecha_siniestro DESC""",
        (cliente_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


def actualizar_estado_siniestro(siniestro_id, nuevo_estado):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE siniestros SET estado = %s WHERE id = %s", (nuevo_estado, siniestro_id))
    conn.commit()
    cur.close()
    conn.close()


def actualizar_siniestro(siniestro_id, tipo_siniestro, fecha_siniestro, descripcion,
                          numero_denuncia, estado):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """UPDATE siniestros
           SET tipo_siniestro = %s, fecha_siniestro = %s, descripcion = %s,
               numero_denuncia = %s, estado = %s
           WHERE id = %s""",
        (tipo_siniestro, fecha_siniestro, descripcion, numero_denuncia, estado, siniestro_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def eliminar_siniestro(siniestro_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM siniestros WHERE id = %s", (siniestro_id,))
    conn.commit()
    cur.close()
    conn.close()


def contar_siniestros_abiertos():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) AS total FROM siniestros WHERE estado NOT IN ('Cerrado', 'Rechazado')"
    )
    total = cur.fetchone()["total"]
    cur.close()
    conn.close()
    return total


# ---------------------------------------------------------------------------
# HISTORIAL DE INTERACCIONES Y COTIZACIONES
# ---------------------------------------------------------------------------

def insertar_interaccion(cliente_id, tipo_evento, ramo_producto, monto_cotizado,
                          resultado, detalle, fecha):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO interacciones
           (cliente_id, tipo_evento, ramo_producto, monto_cotizado, resultado, detalle, fecha)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (cliente_id, tipo_evento, ramo_producto, monto_cotizado, resultado, detalle, fecha),
    )
    interaccion_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return interaccion_id


def listar_interacciones_cliente(cliente_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT * FROM interacciones WHERE cliente_id = %s
           ORDER BY fecha DESC, fecha_carga DESC""",
        (cliente_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


def eliminar_interaccion(interaccion_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM interacciones WHERE id = %s", (interaccion_id,))
    conn.commit()
    cur.close()
    conn.close()


def detectar_oportunidades_cliente(cliente_id):
    """
    Regla simple y transparente de venta cruzada (sin IA): busca cotizaciones
    de un ramo que el cliente NO tiene contratado hoy en una póliza activa,
    y cuyo resultado quedó en 'Rechazada por precio', 'Pendiente de decision'
    o 'Sin respuesta'. Devuelve una lista de alertas con el ramo y hace
    cuánto se cotizó.
    """
    polizas_activas = historial_polizas_cliente(cliente_id)
    ramos_contratados = {
        (p["ramo"] or "").strip().upper() for p in polizas_activas if p["estado"] == "Activa"
    }

    interacciones = listar_interacciones_cliente(cliente_id)
    oportunidades = []
    vistos = set()
    for i in interacciones:
        if i["tipo_evento"] != "Cotizacion enviada":
            continue
        if i["resultado"] not in ("Rechazada por precio", "Pendiente de decision", "Sin respuesta"):
            continue
        ramo = (i["ramo_producto"] or "").strip()
        if not ramo or ramo.upper() in ramos_contratados:
            continue
        if ramo.upper() in vistos:
            continue
        vistos.add(ramo.upper())
        oportunidades.append({
            "ramo": ramo,
            "fecha": i["fecha"],
            "resultado": i["resultado"],
        })
    return oportunidades


# ---------------------------------------------------------------------------
# TAREAS Y SEGUIMIENTOS
# ---------------------------------------------------------------------------

def insertar_tarea(cliente_id, titulo, fecha_limite, prioridad):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO tareas (cliente_id, titulo, fecha_limite, prioridad)
           VALUES (%s, %s, %s, %s) RETURNING id""",
        (cliente_id, titulo, fecha_limite, prioridad),
    )
    tarea_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return tarea_id


def listar_tareas():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT t.*, c.nombre_razon_social
           FROM tareas t
           LEFT JOIN clientes c ON c.id = t.cliente_id
           ORDER BY t.fecha_limite ASC NULLS LAST"""
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


def actualizar_estado_tarea(tarea_id, nuevo_estado):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE tareas SET estado = %s WHERE id = %s", (nuevo_estado, tarea_id))
    conn.commit()
    cur.close()
    conn.close()


def eliminar_tarea(tarea_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM tareas WHERE id = %s", (tarea_id,))
    conn.commit()
    cur.close()
    conn.close()


def contar_tareas_hoy_y_vencidas():
    """Cuenta tareas no completadas con vencimiento hoy o ya pasado (vencidas)."""
    conn = get_connection()
    cur = conn.cursor()
    hoy = date.today().strftime("%Y-%m-%d")
    cur.execute(
        """SELECT COUNT(*) AS total FROM tareas
           WHERE estado != 'Completada' AND fecha_limite IS NOT NULL AND fecha_limite <= %s""",
        (hoy,),
    )
    total = cur.fetchone()["total"]
    cur.close()
    conn.close()
    return total


# ---------------------------------------------------------------------------
# PIPELINE DE PROSPECCIÓN (oportunidades comerciales)
# ---------------------------------------------------------------------------

ETAPAS_PIPELINE = ["Lead", "Contactado", "Cotizacion enviada", "Negociacion", "Cerrado", "Perdido"]


def insertar_oportunidad(nombre_prospecto, telefono, email, origen, ramo_interes,
                          monto_estimado, notas):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO oportunidades
           (nombre_prospecto, telefono, email, origen, ramo_interes, monto_estimado, notas)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (nombre_prospecto, telefono, email, origen, ramo_interes, monto_estimado, notas),
    )
    oportunidad_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return oportunidad_id


def listar_oportunidades():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM oportunidades ORDER BY fecha_actualizacion DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


def actualizar_etapa_oportunidad(oportunidad_id, nueva_etapa, motivo_perdida=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """UPDATE oportunidades
           SET etapa = %s, motivo_perdida = %s, fecha_actualizacion = NOW()
           WHERE id = %s""",
        (nueva_etapa, motivo_perdida, oportunidad_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def eliminar_oportunidad(oportunidad_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM oportunidades WHERE id = %s", (oportunidad_id,))
    conn.commit()
    cur.close()
    conn.close()


def convertir_oportunidad_a_cliente(oportunidad_id):
    """
    Convierte una oportunidad ganada en un cliente real de la cartera
    (vinculándolo por si ya existiera un cliente con ese teléfono/email no
    aplica automáticamente por CUIT porque el lead todavía no tiene uno:
    se crea el cliente con los datos disponibles y se puede completar el
    CUIT/DNI después, al cargarle la primera póliza).
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM oportunidades WHERE id = %s", (oportunidad_id,))
    op = cur.fetchone()
    cur.close()
    conn.close()
    if not op:
        raise ValueError("No se encontró la oportunidad.")

    # CUIT/DNI temporal único, para que no choque con el UNIQUE de la tabla;
    # el usuario lo puede corregir después desde la ficha del cliente.
    cuit_temporal = f"PROSPECTO-{oportunidad_id}"
    cliente_id = upsert_cliente(
        nombre=op["nombre_prospecto"],
        cuit_dni=cuit_temporal,
        telefono=op["telefono"],
        email=op["email"],
    )

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE oportunidades SET etapa = 'Cerrado', cliente_id = %s, fecha_actualizacion = NOW() WHERE id = %s",
        (cliente_id, oportunidad_id),
    )
    conn.commit()
    cur.close()
    conn.close()
    return cliente_id


# ---------------------------------------------------------------------------
# GUÍA DE RAMOS (notas y requisitos que indican los jefes, organizadas por IA)
# ---------------------------------------------------------------------------

def insertar_nota_ramo(ramo, contenido):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO notas_ramo (ramo, contenido) VALUES (%s, %s) RETURNING id",
        (ramo, contenido),
    )
    nota_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return nota_id


def listar_notas_por_ramo():
    """Devuelve un diccionario {ramo: [lista de notas]}, ordenado alfabéticamente por ramo."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM notas_ramo ORDER BY ramo, fecha_carga DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    agrupado = {}
    for r in rows:
        d = dict(r)
        agrupado.setdefault(d["ramo"], []).append(d)
    return dict(sorted(agrupado.items()))


def listar_todas_las_notas_ramo():
    """Devuelve todas las notas en una lista plana [{'ramo':..., 'contenido':...}, ...],
    útil para pasarle a la IA como contexto y evitar que duplique información."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT ramo, contenido FROM notas_ramo ORDER BY ramo")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


def eliminar_nota_ramo(nota_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM notas_ramo WHERE id = %s", (nota_id,))
    conn.commit()
    cur.close()
    conn.close()


def buscar_poliza_activa_similar(cliente_id, riesgo_patente, numero_poliza):
    """
    Busca si el cliente ya tiene una póliza ACTIVA con el mismo riesgo/patente
    o el mismo número de póliza, para detectar que una carga nueva es en
    realidad la renovación de esa misma cobertura (mismo vehículo, por
    ejemplo) y así evitar duplicarla como si fuera una póliza distinta.
    """
    riesgo_patente = (riesgo_patente or "").strip()
    numero_poliza = (numero_poliza or "").strip()
    if not riesgo_patente and not numero_poliza:
        return None

    conn = get_connection()
    cur = conn.cursor()
    condiciones = []
    parametros = [cliente_id]
    if riesgo_patente:
        condiciones.append("TRIM(UPPER(COALESCE(riesgo_patente, ''))) = UPPER(%s)")
        parametros.append(riesgo_patente)
    if numero_poliza:
        condiciones.append("TRIM(COALESCE(numero_poliza, '')) = %s")
        parametros.append(numero_poliza)

    cur.execute(
        f"""SELECT * FROM polizas
            WHERE cliente_id = %s AND estado = 'Activa' AND ({' OR '.join(condiciones)})
            ORDER BY vigencia_hasta DESC LIMIT 1""",
        tuple(parametros),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return dict(row) if row else None
