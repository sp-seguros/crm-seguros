"""
app.py
CRM de Pólizas y Clientes para Productores Asesores de Seguros (PAS).
Ejecutar con: streamlit run app.py
"""

import os
from pathlib import Path
import io
import urllib.parse
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

import db
from pdf_extractor import extract_policy_data

load_dotenv()

st.set_page_config(page_title="CRM Seguros", page_icon="📋", layout="wide")
db.init_db()

st.markdown(
    """
    <style>
    /* Barra lateral con fondo suave a tono con la paleta */
    section[data-testid="stSidebar"] {
        background-color: #F4F2FF;
        border-right: 1px solid #E4DFFB;
    }

    /* Acento de color debajo del título principal, con jerarquía tipográfica */
    h1 {
        border-bottom: 3px solid #5B48EE;
        padding-bottom: 8px;
        display: inline-block;
        font-weight: 800 !important;
        letter-spacing: -0.5px;
    }

    /* Tarjetas de métricas (st.metric) con borde, sombra suave y contenido centrado */
    div[data-testid="stMetric"] {
        background-color: #ffffff;
        border: 1px solid #e6e9ef;
        border-radius: 12px;
        padding: 16px 12px 12px 12px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
        text-align: center;
    }
    div[data-testid="stMetric"] > div {
        justify-content: center;
    }
    div[data-testid="stMetricLabel"] {
        justify-content: center;
    }

    /* Pills de los filtros (multiselect) con look más suave */
    span[data-baseweb="tag"] {
        border-radius: 999px !important;
        background-color: #EDE9FE !important;
        color: #4C1D95 !important;
    }

    /* Contenedores con borde (st.container(border=True)) más redondeados */
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 12px !important;
        box-shadow: 0 1px 4px rgba(15, 23, 42, 0.05);
    }

    /* Fichas de clientes / grupos desplegables */
    div[data-testid="stExpander"] {
        border-radius: 10px;
        border: 1px solid #e6e9ef;
        overflow: hidden;
    }

    /* Jerarquía tipográfica de subtítulos */
    h2, h3 { font-weight: 700 !important; }

    /* Botones con esquinas más redondeadas */
    button[kind="primary"], button[kind="secondary"] {
        border-radius: 8px !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

UPLOADS_DIR = Path(__file__).parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

COLOR_PASTEL = {
    "verde": ("#DCFCE7", "#15803D"),
    "amarillo": ("#FEF3C7", "#B45309"),
    "rojo": ("#FEE2E2", "#B91C1C"),
    "gris": ("#F1F5F9", "#475569"),
}
COLOR_LABEL = {
    "verde": "🟢 Vigente (+30 días)",
    "amarillo": "🟡 Próxima a vencer (15-30 días)",
    "rojo": "🔴 Urgente (≤15 días)",
    "gris": "⚪ Vencida / sin fecha",
}

ESTADO_POLIZA_TIPO = {
    "Activa": "verde", "Vencida": "rojo", "Anulada": "gris", "Renovada": "gris",
}
ESTADO_SINIESTRO_TIPO = {
    "Denunciado": "amarillo", "En revision": "amarillo", "Pendiente liquidacion": "amarillo",
    "Cerrado": "verde", "Rechazado": "rojo",
}


def badge_pastel(texto: str, tipo: str) -> str:
    """Etiqueta ('pill') con color pastel suave, para estados de pólizas y siniestros."""
    bg, fg = COLOR_PASTEL.get(tipo, COLOR_PASTEL["gris"])
    return (
        f"<span style='background-color:{bg};color:{fg};"
        f"padding:3px 12px;border-radius:999px;font-size:0.8em;font-weight:600;'>{texto}</span>"
    )


def badge(color: str) -> str:
    label = COLOR_LABEL[color]
    return badge_pastel(label, color)


def estado_vacio(icono: str, mensaje: str):
    st.markdown(
        f"""
        <div style='background-color:#F4F2FF;border:1px solid #E4DFFB;
                    border-radius:12px;padding:28px 20px;text-align:center;'>
            <div style='font-size:2em;'>{icono}</div>
            <div style='color:#4C1D95;font-weight:600;margin-top:6px;'>{mensaje}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# SIDEBAR / NAVEGACIÓN
# ---------------------------------------------------------------------------
st.sidebar.title("📋 CRM Seguros")

_siniestros_abiertos_count = db.contar_siniestros_abiertos()
_tareas_hoy_count = db.contar_tareas_hoy()
_opciones_nav = [
    "📊 Dashboard", "📥 Cargar Póliza", "👥 Clientes", "💰 Cobranzas",
    "🚨 Siniestros", "🗓️ Tareas",
]


def _formato_nav(opcion):
    if opcion == "🚨 Siniestros" and _siniestros_abiertos_count > 0:
        return f"🚨 Siniestros ({_siniestros_abiertos_count})"
    if opcion == "🗓️ Tareas" and _tareas_hoy_count > 0:
        return f"🗓️ Tareas ({_tareas_hoy_count})"
    return opcion


pagina = st.sidebar.radio("Navegación", _opciones_nav, format_func=_formato_nav)

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

    if _siniestros_abiertos_count > 0:
        st.warning(
            f"🚨 Tenés **{_siniestros_abiertos_count} siniestro(s) en proceso**. "
            "Revisalos en la sección '🚨 Siniestros' del menú."
        )
    if _tareas_hoy_count > 0:
        st.info(
            f"🗓️ Tenés **{_tareas_hoy_count} tarea(s) para hoy**. "
            "Revisalas en la sección '🗓️ Tareas' del menú."
        )

    polizas = db.listar_polizas_dashboard()
    df_polizas_completo = pd.DataFrame(polizas) if polizas else pd.DataFrame()
    proximos_30_dias = (
        df_polizas_completo["color"].isin(["amarillo", "rojo"]).sum()
        if not df_polizas_completo.empty else 0
    )

    metricas = db.metricas_generales()
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("👥 Total Clientes", metricas["total_clientes"])
    m2.metric("📄 Pólizas Vigentes", metricas["polizas_vigentes"])
    m3.metric("🔔 Próx. Vencimientos (30d)", proximos_30_dias)
    m4.metric("💵 Prima Total", f"${metricas['prima_total']:,.0f}")
    m5.metric("📊 Prima Promedio", f"${metricas['prima_promedio']:,.0f}")

    ramo_data = db.distribucion_por_ramo()
    aseg_data = db.distribucion_por_aseguradora()
    if ramo_data or aseg_data:
        st.divider()
        st.subheader("Distribución de cartera")
        g1, g2 = st.columns(2)
        if ramo_data:
            fig_ramo = px.pie(
                pd.DataFrame(ramo_data), names="ramo", values="cantidad",
                title="Por Ramo", hole=0.4,
            )
            g1.plotly_chart(fig_ramo, use_container_width=True)
        if aseg_data:
            fig_aseg = px.pie(
                pd.DataFrame(aseg_data), names="compania_aseguradora", values="cantidad",
                title="Por Aseguradora", hole=0.4,
            )
            g2.plotly_chart(fig_aseg, use_container_width=True)

    st.divider()

    if not polizas:
        st.info("Todavía no cargaste ninguna póliza. Andá a '📥 Cargar Póliza'.")
    else:
        df = df_polizas_completo

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

        fc1, fc2 = st.columns([2, 1])
        busqueda_dash = fc1.text_input(
            "🔎 Buscar por cliente o CUIT/DNI", placeholder="Escribí un nombre o número..."
        )
        aseguradoras_disponibles = sorted(
            df["compania_aseguradora"].dropna().unique().tolist()
        )
        aseguradora_sel = fc2.selectbox(
            "Aseguradora", ["Todas"] + aseguradoras_disponibles
        )

        df_filtrado = df[df["color"].isin(filtro_color)]

        if busqueda_dash:
            mask = (
                df_filtrado["nombre_razon_social"].str.contains(busqueda_dash, case=False, na=False)
                | df_filtrado["cuit_dni"].str.contains(busqueda_dash, case=False, na=False)
            )
            df_filtrado = df_filtrado[mask]

        if aseguradora_sel != "Todas":
            df_filtrado = df_filtrado[df_filtrado["compania_aseguradora"] == aseguradora_sel]

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
            polizas_cliente = db.historial_polizas_cliente(cliente["id"])
            siniestros_cliente = db.listar_siniestros_cliente(cliente["id"])
            poliza_activa = next((p for p in polizas_cliente if p["estado"] == "Activa"), None)
            siniestros_abiertos = sum(
                1 for s in siniestros_cliente if s["estado"] not in ("Cerrado", "Rechazado")
            )

            resumen_poliza = (
                f"📄 {poliza_activa['compania_aseguradora'] or '-'} N°{poliza_activa['numero_poliza'] or '-'}"
                if poliza_activa else "📄 sin póliza activa"
            )
            resumen_pago = f"💳 {cliente.get('forma_pago') or 'sin medio de pago'}"
            resumen_siniestros = f"🚨 {siniestros_abiertos} abierto(s)" if siniestros_cliente else ""

            titulo_ficha = (
                f"{cliente['nombre_razon_social']} — {cliente['cuit_dni']}  ·  "
                f"{resumen_poliza}  ·  {resumen_pago}"
                + (f"  ·  {resumen_siniestros}" if resumen_siniestros else "")
            )

            with st.expander(titulo_ficha):
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

                if siniestros_cliente:
                    st.caption(f"🚨 {len(siniestros_cliente)} siniestro(s) — {siniestros_abiertos} abierto(s)")

                polizas = polizas_cliente
                if polizas:
                    for poliza in polizas:
                        c1, c2, c3, c4, c5, c6, c7 = st.columns([2, 2, 1.2, 1.2, 1, 1, 1])
                        c1.markdown(f"**{poliza['compania_aseguradora'] or '-'}**")
                        c1.caption(f"Póliza {poliza['numero_poliza'] or '-'} · {poliza['ramo'] or '-'}")
                        c2.caption(f"Desde: {poliza['vigencia_desde'] or '-'}")
                        c2.caption(f"Hasta: {poliza['vigencia_hasta'] or '-'}")
                        c3.markdown(
                            badge_pastel(poliza["estado"], ESTADO_POLIZA_TIPO.get(poliza["estado"], "gris")),
                            unsafe_allow_html=True,
                        )
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

                        editar_key = f"mostrar_editar_{poliza['id']}"
                        if c6.button("✏️ Editar", key=f"btn_editar_{poliza['id']}"):
                            st.session_state[editar_key] = not st.session_state.get(editar_key, False)
                            st.rerun()

                        if st.session_state.get(editar_key):
                            with st.form(f"form_editar_{poliza['id']}"):
                                st.caption("Corregí los datos de esta póliza y guardá los cambios.")
                                ec1, ec2 = st.columns(2)
                                ed_compania = ec1.text_input(
                                    "Compañía Aseguradora", value=poliza["compania_aseguradora"] or "",
                                    key=f"ed_compania_{poliza['id']}",
                                )
                                ed_numero = ec2.text_input(
                                    "N° de Póliza", value=poliza["numero_poliza"] or "",
                                    key=f"ed_numero_{poliza['id']}",
                                )
                                ed_ramo = ec1.text_input(
                                    "Ramo", value=poliza["ramo"] or "", key=f"ed_ramo_{poliza['id']}",
                                )
                                ed_riesgo = ec2.text_input(
                                    "Riesgo / Patente", value=poliza["riesgo_patente"] or "",
                                    key=f"ed_riesgo_{poliza['id']}",
                                )
                                ed_desde = ec1.text_input(
                                    "Vigencia Desde (YYYY-MM-DD)", value=poliza["vigencia_desde"] or "",
                                    key=f"ed_desde_{poliza['id']}",
                                )
                                ed_hasta = ec2.text_input(
                                    "Vigencia Hasta (YYYY-MM-DD)", value=poliza["vigencia_hasta"] or "",
                                    key=f"ed_hasta_{poliza['id']}",
                                )
                                ed_importe = ec1.number_input(
                                    "Importe / Premio total", min_value=0.0,
                                    value=float(poliza["importe_total"] or 0), step=100.0,
                                    key=f"ed_importe_{poliza['id']}",
                                )
                                ed_cuotas = ec2.number_input(
                                    "Cantidad de cuotas", min_value=1,
                                    value=int(poliza["cantidad_cuotas"] or 1), step=1,
                                    key=f"ed_cuotas_{poliza['id']}",
                                )
                                estados_poliza = ["Activa", "Vencida", "Anulada", "Renovada"]
                                ed_estado = st.selectbox(
                                    "Estado", estados_poliza,
                                    index=estados_poliza.index(poliza["estado"])
                                    if poliza["estado"] in estados_poliza else 0,
                                    key=f"ed_estado_{poliza['id']}",
                                )
                                st.caption(
                                    "Nota: si cambiás el importe o la cantidad de cuotas, las cuotas ya "
                                    "generadas no se recalculan automáticamente."
                                )
                                confirmar_editar = st.form_submit_button("💾 Guardar cambios", type="primary")
                                if confirmar_editar:
                                    db.actualizar_poliza(
                                        poliza_id=poliza["id"],
                                        compania=ed_compania,
                                        numero_poliza=ed_numero,
                                        ramo=ed_ramo,
                                        riesgo_patente=ed_riesgo,
                                        vigencia_desde=ed_desde,
                                        vigencia_hasta=ed_hasta,
                                        importe_total=ed_importe,
                                        cantidad_cuotas=int(ed_cuotas),
                                        estado=ed_estado,
                                    )
                                    st.session_state.pop(editar_key, None)
                                    st.success("Póliza actualizada correctamente.")
                                    st.rerun()

                        if poliza["estado"] == "Activa":
                            renovar_key = f"mostrar_renovar_{poliza['id']}"
                            if c7.button("🔄 Renovar", key=f"btn_renovar_{poliza['id']}"):
                                st.session_state[renovar_key] = not st.session_state.get(renovar_key, False)
                                st.rerun()

                            if st.session_state.get(renovar_key):
                                with st.form(f"form_renovar_{poliza['id']}"):
                                    st.caption(
                                        "Se crea una póliza nueva para el próximo período; "
                                        "esta póliza actual queda marcada como 'Renovada' "
                                        "y se conserva en el historial."
                                    )
                                    rc1, rc2 = st.columns(2)
                                    nuevo_numero = rc1.text_input(
                                        "N° de póliza (nuevo o el mismo)",
                                        value=poliza["numero_poliza"] or "",
                                    )
                                    try:
                                        desde_sugerido = poliza["vigencia_hasta"] or ""
                                        hasta_sugerido = (
                                            datetime.strptime(poliza["vigencia_hasta"], "%Y-%m-%d")
                                            + timedelta(days=365)
                                        ).strftime("%Y-%m-%d")
                                    except (ValueError, TypeError):
                                        desde_sugerido = ""
                                        hasta_sugerido = ""
                                    nueva_desde = rc1.text_input("Nueva vigencia desde", value=desde_sugerido)
                                    nueva_hasta = rc2.text_input("Nueva vigencia hasta", value=hasta_sugerido)
                                    nuevo_importe = rc1.number_input(
                                        "Nuevo importe / premio",
                                        min_value=0.0,
                                        value=float(poliza["importe_total"] or 0),
                                        step=100.0,
                                    )
                                    nueva_cant_cuotas = rc2.number_input(
                                        "Nueva cantidad de cuotas",
                                        min_value=1,
                                        value=int(poliza["cantidad_cuotas"] or 1),
                                        step=1,
                                    )
                                    confirmar_renovar = st.form_submit_button(
                                        "✅ Confirmar renovación", type="primary"
                                    )
                                    if confirmar_renovar:
                                        db.renovar_poliza(
                                            poliza_id=poliza["id"],
                                            numero_poliza=nuevo_numero,
                                            vigencia_desde=nueva_desde,
                                            vigencia_hasta=nueva_hasta,
                                            importe_total=nuevo_importe,
                                            cantidad_cuotas=int(nueva_cant_cuotas),
                                        )
                                        st.session_state.pop(renovar_key, None)
                                        st.success("Póliza renovada correctamente.")
                                        st.rerun()
                        st.divider()
                else:
                    st.caption("Sin pólizas cargadas todavía.")

                # -----------------------------------------------------------
                # Historial de Interacciones / Cotizaciones + Perfil Comercial
                # -----------------------------------------------------------
                st.subheader("🗒️ Historial y Cotizaciones")

                oportunidades = db.detectar_oportunidades_venta_cruzada(cliente["id"])
                if oportunidades:
                    for op in oportunidades:
                        monto_txt = f" (${op['monto_cotizado']:,.2f})" if op["monto_cotizado"] else ""
                        st.warning(
                            f"💡 **Oportunidad de venta cruzada**: cotizó **{op['ramo']}**"
                            f"{monto_txt} el {op['fecha'] or '-'} — resultado: "
                            f"*{op['resultado']}*. No tiene una póliza activa de ese ramo."
                        )

                with st.expander("➕ Registrar interacción / cotización"):
                    with st.form(f"form_interaccion_{cliente['id']}"):
                        if1, if2 = st.columns(2)
                        tipo_evento = if1.selectbox(
                            "Tipo de evento",
                            ["Reunion", "Llamada/WhatsApp", "Cotizacion enviada", "Nota interna"],
                            key=f"tipo_evento_{cliente['id']}",
                        )
                        fecha_interaccion = if2.text_input(
                            "Fecha (YYYY-MM-DD)", value=date.today().strftime("%Y-%m-%d"),
                            key=f"fecha_inter_{cliente['id']}",
                        )
                        ramo_producto = if1.text_input(
                            "Ramo / Producto cotizado (si aplica)",
                            placeholder="Ej: Auto, Hogar, Vida, ART",
                            key=f"ramo_inter_{cliente['id']}",
                        )
                        monto_cotizado = if2.number_input(
                            "Monto / prima cotizada (opcional)", min_value=0.0, step=100.0,
                            key=f"monto_inter_{cliente['id']}",
                        )
                        resultado = st.selectbox(
                            "Resultado / Feedback",
                            ["", "Aceptada", "Rechazada por precio", "Pendiente de decision", "Sin respuesta"],
                            key=f"resultado_inter_{cliente['id']}",
                        )
                        detalle = st.text_area(
                            "Detalle / resumen de la conversación",
                            key=f"detalle_inter_{cliente['id']}",
                        )
                        guardar_interaccion = st.form_submit_button("💾 Guardar", type="primary")
                        if guardar_interaccion:
                            db.insertar_interaccion(
                                cliente_id=cliente["id"],
                                tipo_evento=tipo_evento,
                                ramo_producto=ramo_producto or None,
                                monto_cotizado=monto_cotizado or None,
                                resultado=resultado or None,
                                detalle=detalle or None,
                                fecha=fecha_interaccion or None,
                            )
                            st.success("Interacción registrada correctamente.")
                            st.rerun()

                interacciones_cliente = db.listar_interacciones_cliente(cliente["id"])
                if not interacciones_cliente:
                    st.caption("Todavía no hay interacciones registradas con este cliente.")
                else:
                    ICONO_EVENTO = {
                        "Reunion": "🤝", "Llamada/WhatsApp": "💬",
                        "Cotizacion enviada": "📤", "Nota interna": "📝",
                    }
                    RESULTADO_TIPO = {
                        "Aceptada": "verde", "Rechazada por precio": "rojo",
                        "Pendiente de decision": "amarillo", "Sin respuesta": "gris",
                    }
                    for inter in interacciones_cliente:
                        ic1, ic2 = st.columns([5, 1])
                        icono = ICONO_EVENTO.get(inter["tipo_evento"], "•")
                        linea = f"{icono} **{inter['tipo_evento']}** — {inter['fecha'] or '-'}"
                        if inter["ramo_producto"]:
                            linea += f" · {inter['ramo_producto']}"
                        if inter["monto_cotizado"]:
                            linea += f" · ${inter['monto_cotizado']:,.2f}"
                        ic1.markdown(linea)
                        if inter["detalle"]:
                            ic1.caption(inter["detalle"])
                        if inter["resultado"]:
                            ic1.markdown(
                                badge_pastel(
                                    inter["resultado"],
                                    RESULTADO_TIPO.get(inter["resultado"], "gris"),
                                ),
                                unsafe_allow_html=True,
                            )
                        if ic2.button("🗑️", key=f"del_inter_{inter['id']}", help="Eliminar"):
                            db.eliminar_interaccion(inter["id"])
                            st.rerun()
                        st.divider()

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
                c1, c2, c3, c4, c5 = st.columns([3, 2, 2, 1.3, 1])
                c1.markdown(f"**{row['nombre_razon_social']}**")
                c1.caption(f"Póliza {row['numero_poliza']} · {row['compania_aseguradora']}")
                c2.markdown(f"Cuota N° {row['numero_cuota']}")
                c2.caption(f"Vence: {row['fecha_vencimiento']}")
                c3.markdown(f"${row['monto']:,.2f}")
                estado_color = "🔴" if row["estado"] == "Vencida" else "🟡"
                c3.caption(f"{estado_color} {row['estado']}")

                telefono_digits = "".join(ch for ch in str(row.get("telefono") or "") if ch.isdigit())
                if telefono_digits:
                    if not telefono_digits.startswith("54"):
                        telefono_digits = "54" + telefono_digits
                    primer_nombre = (row["nombre_razon_social"] or "").split()[0]
                    mensaje = (
                        f"Hola {primer_nombre}, te escribo para recordarte que la cuota N° "
                        f"{row['numero_cuota']} de tu póliza {row['numero_poliza']} "
                        f"({row['compania_aseguradora']}) por ${row['monto']:,.2f} vence el "
                        f"{row['fecha_vencimiento']}. ¡Cualquier consulta, avisame!"
                    )
                    wa_link = f"https://wa.me/{telefono_digits}?text={urllib.parse.quote(mensaje)}"
                    c4.link_button("💬 WhatsApp", wa_link)
                else:
                    c4.caption("Sin teléfono")

                if c5.button("Pagada", key=f"pagar_{row['id']}"):
                    db.marcar_cuota_pagada(row["id"])
                    st.rerun()

# ---------------------------------------------------------------------------
# SINIESTROS
# ---------------------------------------------------------------------------
elif pagina == "🚨 Siniestros":
    st.title("🚨 Gestión de Siniestros")

    with st.expander("➕ Cargar nuevo siniestro"):
        clientes_todos = db.listar_clientes()
        if not clientes_todos:
            st.info("Primero tenés que cargar al menos un cliente (desde 'Cargar Póliza').")
        else:
            sel1, sel2 = st.columns(2)
            opciones_cliente = {
                f"{c['nombre_razon_social']} — {c['cuit_dni']}": c["id"] for c in clientes_todos
            }
            nombre_cliente_sel = sel1.selectbox(
                "Cliente", options=list(opciones_cliente.keys()), key="siniestro_cliente_sel"
            )
            cliente_id_sel = opciones_cliente[nombre_cliente_sel]

            polizas_cliente_sel = db.historial_polizas_cliente(cliente_id_sel)
            opciones_poliza = {"Sin vincular a una póliza específica": None}
            for p in polizas_cliente_sel:
                etiqueta = f"{p['compania_aseguradora'] or '-'} — Póliza {p['numero_poliza'] or '-'} ({p['estado']})"
                opciones_poliza[etiqueta] = p["id"]
            nombre_poliza_sel = sel2.selectbox("Póliza vinculada", options=list(opciones_poliza.keys()))
            poliza_id_sel = opciones_poliza[nombre_poliza_sel]

            with st.form("form_nuevo_siniestro"):
                sf1, sf2 = st.columns(2)
                tipo_siniestro = sf1.selectbox(
                    "Tipo de siniestro",
                    ["Choque", "Robo/Hurto", "Incendio", "Granizo", "Rotura de cristales",
                     "Responsabilidad Civil", "Daños por agua", "Otro"],
                )
                fecha_siniestro = sf2.text_input(
                    "Fecha del siniestro (YYYY-MM-DD)", value=date.today().strftime("%Y-%m-%d")
                )
                numero_denuncia = st.text_input(
                    "N° de denuncia en la aseguradora (si ya lo tenés)"
                )
                descripcion = st.text_area("Descripción / detalle")
                guardar_siniestro = st.form_submit_button("💾 Registrar siniestro", type="primary")

                if guardar_siniestro:
                    db.insertar_siniestro(
                        cliente_id=cliente_id_sel,
                        poliza_id=poliza_id_sel,
                        tipo_siniestro=tipo_siniestro,
                        fecha_siniestro=fecha_siniestro,
                        descripcion=descripcion,
                        numero_denuncia=numero_denuncia or None,
                    )
                    st.success("Siniestro registrado correctamente.")
                    st.rerun()

    st.divider()

    siniestros = db.listar_siniestros()
    if not siniestros:
        estado_vacio("🚨", "Todavía no hay siniestros cargados.")
    else:
        ESTADOS_SINIESTRO = ["Denunciado", "En revision", "Pendiente liquidacion", "Cerrado", "Rechazado"]
        ESTADO_ICONO = {
            "Denunciado": "🆕", "En revision": "🔎", "Pendiente liquidacion": "⏳",
            "Cerrado": "✅", "Rechazado": "❌",
        }

        filtro_estado = st.multiselect(
            "Filtrar por estado", options=ESTADOS_SINIESTRO, default=ESTADOS_SINIESTRO
        )

        for s in siniestros:
            if s["estado"] not in filtro_estado:
                continue
            with st.container(border=True):
                sc1, sc2, sc3, sc4 = st.columns([3, 2, 1.6, 1.2])
                sc1.markdown(f"**{s['nombre_razon_social']}** — {s['cuit_dni']}")
                sc1.caption(
                    f"{s['tipo_siniestro'] or '-'} · "
                    f"{s['compania_aseguradora'] or 'sin póliza vinculada'} "
                    f"{('N° ' + s['numero_poliza']) if s['numero_poliza'] else ''}"
                )
                if s["descripcion"]:
                    sc1.caption(f"📝 {s['descripcion']}")
                if s.get("numero_denuncia"):
                    sc1.caption(f"🔖 Denuncia N° {s['numero_denuncia']}")
                sc2.caption(f"📅 Fecha: {s['fecha_siniestro'] or '-'}")

                nuevo_estado = sc3.selectbox(
                    "Estado",
                    ESTADOS_SINIESTRO,
                    index=ESTADOS_SINIESTRO.index(s["estado"]),
                    key=f"estado_siniestro_{s['id']}",
                    label_visibility="collapsed",
                )
                if nuevo_estado != s["estado"]:
                    db.actualizar_estado_siniestro(s["id"], nuevo_estado)
                    st.rerun()
                sc3.markdown(
                    badge_pastel(
                        f"{ESTADO_ICONO.get(s['estado'], '')} {s['estado']}",
                        ESTADO_SINIESTRO_TIPO.get(s["estado"], "gris"),
                    ),
                    unsafe_allow_html=True,
                )

                confirm_key_sin = f"confirmar_borrar_siniestro_{s['id']}"
                if st.session_state.get(confirm_key_sin):
                    sc4.caption("¿Seguro?")
                    if sc4.button("✅ Sí, borrar", key=f"si_sin_{s['id']}"):
                        db.eliminar_siniestro(s["id"])
                        st.session_state.pop(confirm_key_sin, None)
                        st.rerun()
                    if sc4.button("Cancelar", key=f"no_sin_{s['id']}"):
                        st.session_state.pop(confirm_key_sin, None)
                        st.rerun()
                else:
                    if sc4.button("🗑️ Eliminar", key=f"del_sin_{s['id']}"):
                        st.session_state[confirm_key_sin] = True
                        st.rerun()

                editar_key_sin = f"mostrar_editar_sin_{s['id']}"
                if sc4.button("✏️ Editar", key=f"btn_editar_sin_{s['id']}"):
                    st.session_state[editar_key_sin] = not st.session_state.get(editar_key_sin, False)
                    st.rerun()

                if st.session_state.get(editar_key_sin):
                    with st.form(f"form_editar_sin_{s['id']}"):
                        esf1, esf2 = st.columns(2)
                        ed_tipo = esf1.selectbox(
                            "Tipo de siniestro",
                            ["Choque", "Robo/Hurto", "Incendio", "Granizo", "Rotura de cristales",
                             "Responsabilidad Civil", "Daños por agua", "Otro"],
                            index=(
                                ["Choque", "Robo/Hurto", "Incendio", "Granizo", "Rotura de cristales",
                                 "Responsabilidad Civil", "Daños por agua", "Otro"].index(s["tipo_siniestro"])
                                if s["tipo_siniestro"] in
                                ["Choque", "Robo/Hurto", "Incendio", "Granizo", "Rotura de cristales",
                                 "Responsabilidad Civil", "Daños por agua", "Otro"] else 0
                            ),
                        )
                        ed_fecha = esf2.text_input(
                            "Fecha del siniestro (YYYY-MM-DD)", value=s["fecha_siniestro"] or ""
                        )
                        ed_denuncia = st.text_input(
                            "N° de denuncia en la aseguradora", value=s.get("numero_denuncia") or ""
                        )
                        ed_descripcion = st.text_area("Descripción / detalle", value=s["descripcion"] or "")
                        confirmar_editar_sin = st.form_submit_button("💾 Guardar cambios", type="primary")
                        if confirmar_editar_sin:
                            db.actualizar_siniestro(
                                siniestro_id=s["id"],
                                tipo_siniestro=ed_tipo,
                                fecha_siniestro=ed_fecha,
                                descripcion=ed_descripcion,
                                numero_denuncia=ed_denuncia or None,
                                estado=s["estado"],
                            )
                            st.session_state.pop(editar_key_sin, None)
                            st.success("Siniestro actualizado correctamente.")
                            st.rerun()

# ---------------------------------------------------------------------------
# TAREAS Y SEGUIMIENTOS
# ---------------------------------------------------------------------------
elif pagina == "🗓️ Tareas":
    st.title("🗓️ Tareas y Seguimientos")

    clientes_todos_tareas = db.listar_clientes()
    opciones_cliente_tarea = {"Sin cliente asociado": None}
    for c in clientes_todos_tareas:
        opciones_cliente_tarea[f"{c['nombre_razon_social']} — {c['cuit_dni']}"] = c["id"]

    with st.expander("➕ Nueva tarea"):
        with st.form("form_nueva_tarea"):
            tf1, tf2 = st.columns(2)
            titulo_tarea = tf1.text_input(
                "Título", placeholder="Ej: Llamar para recalcular cotización de Auto"
            )
            cliente_tarea_sel = tf2.selectbox(
                "Cliente asociado (opcional)", options=list(opciones_cliente_tarea.keys())
            )
            fecha_limite_tarea = tf1.text_input(
                "Fecha límite (YYYY-MM-DD)", value=date.today().strftime("%Y-%m-%d")
            )
            prioridad_tarea = tf2.selectbox("Prioridad", ["Alta", "Media", "Baja"], index=1)
            guardar_tarea = st.form_submit_button("💾 Guardar tarea", type="primary")

            if guardar_tarea:
                if not titulo_tarea:
                    st.error("El título de la tarea es obligatorio.")
                else:
                    db.insertar_tarea(
                        titulo=titulo_tarea,
                        cliente_id=opciones_cliente_tarea[cliente_tarea_sel],
                        fecha_limite=fecha_limite_tarea or None,
                        prioridad=prioridad_tarea,
                    )
                    st.success("Tarea creada correctamente.")
                    st.rerun()

    st.divider()

    tareas = db.listar_tareas()
    if not tareas:
        estado_vacio("🗓️", "Todavía no hay tareas cargadas.")
    else:
        hoy_str = date.today().strftime("%Y-%m-%d")

        def _es_vencida(t):
            return (
                t["fecha_limite"] and t["fecha_limite"] < hoy_str
                and t["estado"] != "Completada"
            )

        cant_hoy = sum(1 for t in tareas if t["fecha_limite"] == hoy_str and t["estado"] != "Completada")
        cant_vencidas = sum(1 for t in tareas if _es_vencida(t))
        cant_pendientes = sum(1 for t in tareas if t["estado"] != "Completada")

        tm1, tm2, tm3 = st.columns(3)
        tm1.metric("📌 Pendientes", cant_pendientes)
        tm2.metric("🗓️ Para hoy", cant_hoy)
        tm3.metric("🔴 Vencidas", cant_vencidas)

        st.divider()

        filtro_rapido = st.radio(
            "Filtro rápido",
            ["Todas", "Tareas de Hoy", "Vencidas", "Por Cliente"],
            horizontal=True,
        )

        cliente_filtro_sel = None
        if filtro_rapido == "Por Cliente":
            cliente_filtro_sel = st.selectbox(
                "Elegí un cliente", options=list(opciones_cliente_tarea.keys())
            )

        filtro_estado_tarea = st.multiselect(
            "Filtrar por estado",
            ["Pendiente", "En proceso", "Completada"],
            default=["Pendiente", "En proceso", "Completada"],
        )

        tareas_filtradas = [t for t in tareas if t["estado"] in filtro_estado_tarea]
        if filtro_rapido == "Tareas de Hoy":
            tareas_filtradas = [t for t in tareas_filtradas if t["fecha_limite"] == hoy_str]
        elif filtro_rapido == "Vencidas":
            tareas_filtradas = [t for t in tareas_filtradas if _es_vencida(t)]
        elif filtro_rapido == "Por Cliente" and cliente_filtro_sel:
            cid = opciones_cliente_tarea[cliente_filtro_sel]
            tareas_filtradas = [t for t in tareas_filtradas if t["cliente_id"] == cid]

        if not tareas_filtradas:
            st.caption("No hay tareas que coincidan con este filtro.")

        PRIORIDAD_TIPO = {"Alta": "rojo", "Media": "amarillo", "Baja": "verde"}
        ESTADOS_TAREA = ["Pendiente", "En proceso", "Completada"]

        for t in tareas_filtradas:
            with st.container(border=True):
                tc1, tc2, tc3, tc4 = st.columns([3, 1.5, 1.3, 1])
                tc1.markdown(f"**{t['titulo']}**")
                if t.get("nombre_razon_social"):
                    tc1.caption(f"👤 {t['nombre_razon_social']}")
                else:
                    tc1.caption("Sin cliente asociado")
                tc1.markdown(
                    badge_pastel(t["prioridad"], PRIORIDAD_TIPO.get(t["prioridad"], "gris")),
                    unsafe_allow_html=True,
                )

                if _es_vencida(t):
                    tc2.markdown("🔴 **Vencida**")
                tc2.caption(f"Vence: {t['fecha_limite'] or '-'}")

                nuevo_estado_tarea = tc3.selectbox(
                    "Estado", ESTADOS_TAREA,
                    index=ESTADOS_TAREA.index(t["estado"]) if t["estado"] in ESTADOS_TAREA else 0,
                    key=f"estado_tarea_{t['id']}",
                    label_visibility="collapsed",
                )
                if nuevo_estado_tarea != t["estado"]:
                    db.actualizar_estado_tarea(t["id"], nuevo_estado_tarea)
                    st.rerun()

                confirm_key_tarea = f"confirmar_borrar_tarea_{t['id']}"
                if st.session_state.get(confirm_key_tarea):
                    tc4.caption("¿Seguro?")
                    if tc4.button("✅ Sí", key=f"si_tarea_{t['id']}"):
                        db.eliminar_tarea(t["id"])
                        st.session_state.pop(confirm_key_tarea, None)
                        st.rerun()
                    if tc4.button("Cancelar", key=f"no_tarea_{t['id']}"):
                        st.session_state.pop(confirm_key_tarea, None)
                        st.rerun()
                else:
                    if tc4.button("🗑️", key=f"del_tarea_{t['id']}", help="Eliminar"):
                        st.session_state[confirm_key_tarea] = True
                        st.rerun()

                editar_key_tarea = f"mostrar_editar_tarea_{t['id']}"
                if tc4.button("✏️", key=f"btn_editar_tarea_{t['id']}", help="Editar"):
                    st.session_state[editar_key_tarea] = not st.session_state.get(editar_key_tarea, False)
                    st.rerun()

                if st.session_state.get(editar_key_tarea):
                    with st.form(f"form_editar_tarea_{t['id']}"):
                        etf1, etf2 = st.columns(2)
                        ed_titulo_tarea = etf1.text_input("Título", value=t["titulo"])
                        opciones_cliente_actual = list(opciones_cliente_tarea.keys())
                        cliente_actual_nombre = next(
                            (k for k, v in opciones_cliente_tarea.items() if v == t["cliente_id"]),
                            "Sin cliente asociado",
                        )
                        ed_cliente_tarea = etf2.selectbox(
                            "Cliente asociado", opciones_cliente_actual,
                            index=opciones_cliente_actual.index(cliente_actual_nombre)
                            if cliente_actual_nombre in opciones_cliente_actual else 0,
                        )
                        ed_fecha_tarea = etf1.text_input(
                            "Fecha límite (YYYY-MM-DD)", value=t["fecha_limite"] or ""
                        )
                        prioridades_tarea = ["Alta", "Media", "Baja"]
                        ed_prioridad_tarea = etf2.selectbox(
                            "Prioridad", prioridades_tarea,
                            index=prioridades_tarea.index(t["prioridad"])
                            if t["prioridad"] in prioridades_tarea else 1,
                        )
                        confirmar_editar_tarea = st.form_submit_button("💾 Guardar cambios", type="primary")
                        if confirmar_editar_tarea:
                            db.actualizar_tarea(
                                tarea_id=t["id"],
                                titulo=ed_titulo_tarea,
                                cliente_id=opciones_cliente_tarea[ed_cliente_tarea],
                                fecha_limite=ed_fecha_tarea or None,
                                prioridad=ed_prioridad_tarea,
                                estado=t["estado"],
                            )
                            st.session_state.pop(editar_key_tarea, None)
                            st.success("Tarea actualizada correctamente.")
                            st.rerun()
