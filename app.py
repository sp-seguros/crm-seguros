"""
app.py
CRM de Pólizas y Clientes para Productores Asesores de Seguros (PAS).
Ejecutar con: streamlit run app.py
"""

import os
from pathlib import Path
import io
from datetime import date

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import db
from pdf_extractor import extract_policy_data

load_dotenv()

st.set_page_config(page_title="CRM Seguros", page_icon="📋", layout="wide")
db.init_db()

UPLOADS_DIR = Path(__file__).parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

COLOR_HEX = {
    "verde": "#1e7e34",
    "amarillo": "#b58900",
    "rojo": "#c0392b",
    "gris": "#6c757d",
}
COLOR_LABEL = {
    "verde": "🟢 Vigente (+30 días)",
    "amarillo": "🟡 Próxima a vencer (15-30 días)",
    "rojo": "🔴 Urgente (≤15 días)",
    "gris": "⚪ Vencida / sin fecha",
}


def badge(color: str) -> str:
    hex_color = COLOR_HEX[color]
    label = COLOR_LABEL[color]
    return (
        f"<span style='background-color:{hex_color};color:white;"
        f"padding:3px 8px;border-radius:6px;font-size:0.8em'>{label}</span>"
    )


# ---------------------------------------------------------------------------
# SIDEBAR / NAVEGACIÓN
# ---------------------------------------------------------------------------
st.sidebar.title("📋 CRM Seguros")
pagina = st.sidebar.radio(
    "Navegación",
    ["📊 Dashboard", "📥 Cargar Póliza", "👥 Clientes", "💰 Cobranzas"],
)

if not os.environ.get("GOOGLE_API_KEY"):
    st.sidebar.warning(
        "⚠️ Falta configurar GOOGLE_API_KEY en el archivo .env "
        "para poder usar la lectura automática de PDFs. "
        "Conseguí una clave gratis en https://aistudio.google.com/apikey"
    )

st.sidebar.divider()
st.sidebar.caption("💾 Copia de seguridad")
_clientes_backup = db.obtener_todos_los_clientes()
_polizas_backup = db.obtener_todas_las_polizas()
_cuotas_backup = db.obtener_todas_las_cuotas()

if _clientes_backup or _polizas_backup:
    _buffer = io.BytesIO()
    with pd.ExcelWriter(_buffer, engine="openpyxl") as writer:
        pd.DataFrame(_clientes_backup).to_excel(writer, sheet_name="Clientes", index=False)
        pd.DataFrame(_polizas_backup).to_excel(writer, sheet_name="Polizas", index=False)
        pd.DataFrame(_cuotas_backup).to_excel(writer, sheet_name="Cuotas", index=False)
    st.sidebar.download_button(
        "⬇️ Descargar todo (Excel)",
        data=_buffer.getvalue(),
        file_name=f"backup_crm_seguros_{date.today().isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        help="Guarda una copia de todos tus clientes, pólizas y cuotas en tu computadora.",
    )
else:
    st.sidebar.caption("Todavía no hay datos para respaldar.")

# ---------------------------------------------------------------------------
# DASHBOARD
# ---------------------------------------------------------------------------
if pagina == "📊 Dashboard":
    st.title("📊 Tablero de Vencimientos")

    polizas = db.listar_polizas_dashboard()

    if not polizas:
        st.info("Todavía no cargaste ninguna póliza. Andá a '📥 Cargar Póliza'.")
    else:
        df = pd.DataFrame(polizas)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("🟢 Vigentes", (df["color"] == "verde").sum())
        col2.metric("🟡 Por vencer (15-30d)", (df["color"] == "amarillo").sum())
        col3.metric("🔴 Urgentes (≤15d)", (df["color"] == "rojo").sum())
        col4.metric("⚪ Vencidas", (df["color"] == "gris").sum())

        st.divider()

        filtro_color = st.multiselect(
            "Filtrar por estado",
            options=["verde", "amarillo", "rojo", "gris"],
            default=["rojo", "amarillo", "verde", "gris"],
            format_func=lambda c: COLOR_LABEL[c],
        )
        df_filtrado = df[df["color"].isin(filtro_color)]

        for _, row in df_filtrado.iterrows():
            with st.container(border=True):
                c1, c2, c3 = st.columns([3, 3, 2])
                with c1:
                    st.markdown(f"**{row['nombre_razon_social']}**  \n{row['cuit_dni']}")
                    st.caption(f"📞 {row['telefono'] or '-'} · ✉️ {row['email'] or '-'}")
                with c2:
                    st.markdown(
                        f"**{row['compania_aseguradora'] or '-'}** — Póliza N° {row['numero_poliza'] or '-'}"
                    )
                    st.caption(f"{row['ramo'] or '-'} · {row['riesgo_patente'] or '-'}")
                    st.caption(f"Vigencia hasta: {row['vigencia_hasta'] or '-'}")
                with c3:
                    st.markdown(badge(row["color"]), unsafe_allow_html=True)
                    dias = row["dias_restantes"]
                    if dias is not None:
                        texto_dias = f"{dias} días" if dias >= 0 else f"Vencida hace {-dias} días"
                        st.caption(texto_dias)

# ---------------------------------------------------------------------------
# CARGAR PÓLIZA
# ---------------------------------------------------------------------------
elif pagina == "📥 Cargar Póliza":
    st.title("📥 Carga Inteligente de Pólizas")
    st.write("Subí el PDF de la póliza y la IA va a extraer los datos automáticamente.")

    archivo = st.file_uploader("Arrastrá o seleccioná el PDF de la póliza", type=["pdf"])

    if archivo is not None:
        if "extraccion" not in st.session_state or st.session_state.get("archivo_actual") != archivo.name:
            with st.spinner("Leyendo el PDF con IA..."):
                try:
                    pdf_bytes = archivo.getvalue()
                    datos = extract_policy_data(pdf_bytes)
                    st.session_state["extraccion"] = datos
                    st.session_state["archivo_actual"] = archivo.name
                    st.session_state["pdf_bytes"] = pdf_bytes
                    st.success("Datos extraídos. Revisá y corregí antes de guardar.")
                except Exception as e:
                    st.error(f"No se pudo procesar el PDF: {e}")
                    st.session_state.pop("extraccion", None)

    if "extraccion" in st.session_state:
        datos = st.session_state["extraccion"]

        with st.form("form_confirmacion"):
            st.subheader("Datos del Cliente")
            c1, c2 = st.columns(2)
            nombre = c1.text_input("Nombre / Razón Social", value=datos.get("nombre_razon_social") or "")
            cuit_dni = c2.text_input("CUIT / DNI", value=datos.get("cuit_dni") or "")
            tipo_persona = c1.selectbox(
                "Tipo de persona", ["Fisica", "Juridica"],
                index=0 if (datos.get("tipo_persona") or "Fisica") == "Fisica" else 1,
            )
            telefono = c2.text_input("Teléfono", value=datos.get("telefono") or "")
            email = st.text_input("Email", value=datos.get("email") or "")

            st.subheader("Datos de la Póliza")
            c3, c4 = st.columns(2)
            compania = c3.text_input("Compañía Aseguradora", value=datos.get("compania_aseguradora") or "")
            numero_poliza = c4.text_input("N° de Póliza", value=datos.get("numero_poliza") or "")
            ramo = c3.text_input("Ramo", value=datos.get("ramo") or "")
            riesgo_patente = c4.text_input("Riesgo / Patente", value=datos.get("riesgo_patente") or "")

            c5, c6 = st.columns(2)
            vigencia_desde = c5.text_input(
                "Vigencia Desde (YYYY-MM-DD)", value=datos.get("vigencia_desde") or ""
            )
            vigencia_hasta = c6.text_input(
                "Vigencia Hasta (YYYY-MM-DD)", value=datos.get("vigencia_hasta") or ""
            )

            c7, c8 = st.columns(2)
            importe_total = c7.number_input(
                "Importe / Premio total",
                min_value=0.0,
                value=float(datos.get("importe_total") or 0),
                step=100.0,
            )
            cantidad_cuotas = c8.number_input(
                "Cantidad de cuotas",
                min_value=1,
                value=int(datos.get("cantidad_cuotas") or 1),
                step=1,
            )

            st.subheader("Medio de Pago")
            st.caption(
                "Por seguridad nunca se guarda el número completo de la tarjeta "
                "ni el código de seguridad, solo los últimos 4 dígitos. "
                "Completá solo los campos que correspondan según la forma de pago."
            )
            opciones_pago = ["", "Debito Automatico", "CBU", "Tarjeta de Credito", "Cuponera", "Mercado Pago"]
            forma_pago_ia = datos.get("forma_pago") or ""
            idx_pago = opciones_pago.index(forma_pago_ia) if forma_pago_ia in opciones_pago else 0
            forma_pago = st.selectbox("Forma de pago", opciones_pago, index=idx_pago)

            cp1, cp2, cp3, cp4 = st.columns(4)
            banco_emisor = cp1.text_input("Banco", placeholder="Ej: BBVA")
            marca_tarjeta = cp2.selectbox("Marca de tarjeta (si aplica)", ["", "Visa", "Mastercard", "Amex", "Otra"])
            ultimos_4_digitos = cp3.text_input("Últimos 4 dígitos (si aplica)", max_chars=4)
            vencimiento_tarjeta = cp4.text_input("Vto. tarjeta MM/AA (si aplica)", placeholder="12/28")
            cbu_cvu = st.text_input("CBU / CVU (si aplica)")

            guardar = st.form_submit_button("💾 Guardar Póliza", type="primary")

            if guardar:
                if not cuit_dni or not nombre:
                    st.error("Nombre y CUIT/DNI son obligatorios.")
                else:
                    pdf_path = UPLOADS_DIR / f"{cuit_dni}_{numero_poliza or 'sinnro'}.pdf"
                    pdf_path.write_bytes(st.session_state["pdf_bytes"])

                    cliente_id = db.upsert_cliente(
                        nombre=nombre, cuit_dni=cuit_dni, telefono=telefono,
                        email=email, tipo_persona=tipo_persona,
                        forma_pago=forma_pago or None,
                        banco_emisor=banco_emisor or None,
                        marca_tarjeta=marca_tarjeta or None,
                        ultimos_4_digitos=ultimos_4_digitos or None,
                        vencimiento_tarjeta=vencimiento_tarjeta or None,
                        cbu_cvu=cbu_cvu or None,
                    )
                    db.insertar_poliza(
                        cliente_id=cliente_id,
                        compania=compania,
                        numero_poliza=numero_poliza,
                        ramo=ramo,
                        riesgo_patente=riesgo_patente,
                        vigencia_desde=vigencia_desde,
                        vigencia_hasta=vigencia_hasta,
                        importe_total=importe_total,
                        cantidad_cuotas=int(cantidad_cuotas),
                        pdf_path=str(pdf_path),
                    )
                    st.success(f"✅ Póliza guardada y vinculada a {nombre}.")
                    for k in ("extraccion", "archivo_actual", "pdf_bytes"):
                        st.session_state.pop(k, None)
                    st.rerun()

# ---------------------------------------------------------------------------
# CLIENTES
# ---------------------------------------------------------------------------
elif pagina == "👥 Clientes":
    st.title("👥 Clientes")
    busqueda = st.text_input("Buscar por nombre o CUIT/DNI")
    clientes = db.listar_clientes(busqueda)

    if not clientes:
        st.info("No se encontraron clientes.")
    else:
        for cliente in clientes:
            with st.expander(f"{cliente['nombre_razon_social']} — {cliente['cuit_dni']}"):
                st.caption(f"📞 {cliente['telefono'] or '-'} · ✉️ {cliente['email'] or '-'}")

                forma_pago = cliente.get("forma_pago")
                if forma_pago:
                    if forma_pago == "Tarjeta de Credito":
                        detalle_pago = (
                            f"💳 {forma_pago} — {cliente.get('marca_tarjeta') or '-'} "
                            f"terminada en {cliente.get('ultimos_4_digitos') or '----'} "
                            f"({cliente.get('banco_emisor') or '-'}), "
                            f"vence {cliente.get('vencimiento_tarjeta') or '-'}"
                        )
                    elif forma_pago in ("Debito Automatico", "CBU"):
                        detalle_pago = (
                            f"🏦 {forma_pago} — {cliente.get('banco_emisor') or '-'} "
                            f"({cliente.get('cbu_cvu') or '-'})"
                        )
                    else:
                        detalle_pago = f"💰 {forma_pago}"
                    st.caption(detalle_pago)
                else:
                    st.caption("💰 Medio de pago: sin registrar")

                polizas = db.historial_polizas_cliente(cliente["id"])
                if polizas:
                    for poliza in polizas:
                        c1, c2, c3, c4, c5 = st.columns([2, 2, 1.5, 1.5, 1])
                        c1.markdown(f"**{poliza['compania_aseguradora'] or '-'}**")
                        c1.caption(f"Póliza {poliza['numero_poliza'] or '-'} · {poliza['ramo'] or '-'}")
                        c2.caption(f"Desde: {poliza['vigencia_desde'] or '-'}")
                        c2.caption(f"Hasta: {poliza['vigencia_hasta'] or '-'}")
                        c3.caption(f"Estado: {poliza['estado']}")
                        monto = f"${poliza['importe_total']:,.2f}" if poliza["importe_total"] else "-"
                        c4.caption(monto)

                        confirm_key = f"confirmar_borrar_{poliza['id']}"
                        if st.session_state.get(confirm_key):
                            c5.caption("¿Seguro?")
                            if c5.button("✅ Sí, borrar", key=f"si_{poliza['id']}"):
                                db.eliminar_poliza(poliza["id"])
                                st.session_state.pop(confirm_key, None)
                                st.rerun()
                            if c5.button("Cancelar", key=f"no_{poliza['id']}"):
                                st.session_state.pop(confirm_key, None)
                                st.rerun()
                        else:
                            if c5.button("🗑️ Eliminar", key=f"del_{poliza['id']}"):
                                st.session_state[confirm_key] = True
                                st.rerun()
                        st.divider()
                else:
                    st.caption("Sin pólizas cargadas todavía.")

# ---------------------------------------------------------------------------
# COBRANZAS
# ---------------------------------------------------------------------------
elif pagina == "💰 Cobranzas":
    st.title("💰 Control de Cobranzas")
    cuotas = db.listar_cuotas_pendientes()

    if not cuotas:
        st.info("No hay cuotas pendientes. 🎉")
    else:
        df = pd.DataFrame(cuotas)
        col1, col2 = st.columns(2)
        col1.metric("Cuotas pendientes", (df["estado"] == "Pendiente").sum())
        col2.metric("Cuotas vencidas", (df["estado"] == "Vencida").sum())

        st.divider()

        for _, row in df.iterrows():
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([3, 2, 2, 1])
                c1.markdown(f"**{row['nombre_razon_social']}**")
                c1.caption(f"Póliza {row['numero_poliza']} · {row['compania_aseguradora']}")
                c2.markdown(f"Cuota N° {row['numero_cuota']}")
                c2.caption(f"Vence: {row['fecha_vencimiento']}")
                c3.markdown(f"${row['monto']:,.2f}")
                estado_color = "🔴" if row["estado"] == "Vencida" else "🟡"
                c3.caption(f"{estado_color} {row['estado']}")
                if c4.button("Pagada", key=f"pagar_{row['id']}"):
                    db.marcar_cuota_pagada(row["id"])
                    st.rerun()
