"""
db.py
Capa de acceso a datos para el CRM de seguros.
Usa SQLite (archivo local) para el MVP. Migrar a Postgres/Supabase
más adelante solo requiere cambiar la conexión (ver README).
"""

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "crm_seguros.db"


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Crea las tablas si no existen. Llamar una sola vez al arrancar la app."""
    conn = get_connection()
    cur = conn.cursor()

    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo_persona TEXT CHECK(tipo_persona IN ('Fisica','Juridica')) DEFAULT 'Fisica',
            nombre_razon_social TEXT NOT NULL,
            cuit_dni TEXT UNIQUE NOT NULL,
            telefono TEXT,
            email TEXT,
            direccion TEXT,
            fecha_alta TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS polizas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
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
            fecha_carga TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS cuotas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            poliza_id INTEGER NOT NULL,
            numero_cuota INTEGER,
            monto REAL,
            fecha_vencimiento TEXT,
            fecha_pago TEXT,
            estado TEXT CHECK(estado IN ('Pendiente','Pagada','Vencida')) DEFAULT 'Pendiente',
            FOREIGN KEY (poliza_id) REFERENCES polizas(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS alertas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            poliza_id INTEGER NOT NULL,
            tipo TEXT CHECK(tipo IN ('Vencimiento_Poliza','Vencimiento_Cuota')),
            dias_anticipacion INTEGER,
            fecha_alerta TEXT,
            enviada INTEGER DEFAULT 0,
            fecha_envio TEXT,
            FOREIGN KEY (poliza_id) REFERENCES polizas(id) ON DELETE CASCADE
        );
        """
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# CLIENTES
# ---------------------------------------------------------------------------

def buscar_cliente_por_cuit(cuit_dni: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM clientes WHERE cuit_dni = ?", (cuit_dni,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def upsert_cliente(nombre, cuit_dni, telefono=None, email=None,
                    tipo_persona="Fisica", direccion=None):
    """
    Vinculación automática por CUIT/DNI:
    - Si el cliente existe -> actualiza datos de contacto y devuelve su id.
    - Si no existe -> lo crea.
    """
    existente = buscar_cliente_por_cuit(cuit_dni)
    conn = get_connection()
    cur = conn.cursor()

    if existente:
        cur.execute(
            """UPDATE clientes
               SET nombre_razon_social = COALESCE(?, nombre_razon_social),
                   telefono = COALESCE(?, telefono),
                   email = COALESCE(?, email),
                   direccion = COALESCE(?, direccion)
               WHERE cuit_dni = ?""",
            (nombre, telefono, email, direccion, cuit_dni),
        )
        conn.commit()
        cliente_id = existente["id"]
    else:
        cur.execute(
            """INSERT INTO clientes (tipo_persona, nombre_razon_social, cuit_dni, telefono, email, direccion)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (tipo_persona, nombre, cuit_dni, telefono, email, direccion),
        )
        conn.commit()
        cliente_id = cur.lastrowid

    conn.close()
    return cliente_id


def listar_clientes(filtro: str = ""):
    conn = get_connection()
    if filtro:
        rows = conn.execute(
            """SELECT * FROM clientes
               WHERE nombre_razon_social LIKE ? OR cuit_dni LIKE ?
               ORDER BY nombre_razon_social""",
            (f"%{filtro}%", f"%{filtro}%"),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM clientes ORDER BY nombre_razon_social"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def historial_polizas_cliente(cliente_id: int):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM polizas WHERE cliente_id = ? ORDER BY vigencia_hasta DESC",
        (cliente_id,),
    ).fetchall()
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
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (cliente_id, compania, numero_poliza, ramo, riesgo_patente,
         vigencia_desde, vigencia_hasta, importe_total, cantidad_cuotas, pdf_path),
    )
    poliza_id = cur.lastrowid
    conn.commit()
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
               VALUES (?, ?, ?, ?, 'Pendiente')""",
            (poliza_id, i + 1, monto_cuota, fecha_venc.strftime("%Y-%m-%d")),
        )
    conn.commit()
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
               VALUES (?, 'Vencimiento_Poliza', ?, ?)""",
            (poliza_id, dias, fecha_alerta.strftime("%Y-%m-%d")),
        )
    conn.commit()
    conn.close()


def listar_polizas_dashboard():
    """
    Devuelve todas las pólizas con los días restantes hasta el vencimiento,
    para armar el tablero de colores (Verde / Amarillo / Rojo / Gris-vencida).
    """
    conn = get_connection()
    rows = conn.execute(
        """SELECT p.*, c.nombre_razon_social, c.cuit_dni, c.telefono, c.email
           FROM polizas p
           JOIN clientes c ON c.id = p.cliente_id
           ORDER BY p.vigencia_hasta ASC"""
    ).fetchall()
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
    conn.execute("UPDATE polizas SET estado = ? WHERE id = ?", (nuevo_estado, poliza_id))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# COBRANZAS (CUOTAS)
# ---------------------------------------------------------------------------

def listar_cuotas_pendientes():
    conn = get_connection()
    rows = conn.execute(
        """SELECT cu.*, p.numero_poliza, p.compania_aseguradora, c.nombre_razon_social, c.telefono
           FROM cuotas cu
           JOIN polizas p ON p.id = cu.poliza_id
           JOIN clientes c ON c.id = p.cliente_id
           WHERE cu.estado != 'Pagada'
           ORDER BY cu.fecha_vencimiento ASC"""
    ).fetchall()
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
    conn.execute(
        "UPDATE cuotas SET estado = 'Pagada', fecha_pago = ? WHERE id = ?",
        (date.today().strftime("%Y-%m-%d"), cuota_id),
    )
    conn.commit()
    conn.close()
