"""
app.py
CRM de Pólizas y Clientes para Productores Asesores de Seguros (PAS).
Ejecutar con: streamlit run app.py
"""

import os
from pathlib import Path

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

if not os.environ.get("ANTHROPIC_API_KEY"):
    st.sidebar.warning(
        "⚠️ Falta configurar ANTHROPIC_API_KEY en el archivo .env "
        "para poder usar la lectura automática de PDFs."
    )

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
                polizas = db.historial_polizas_cliente(cliente["id"])
                if polizas:
                    df = pd.DataFrame(polizas)[
                        ["compania_aseguradora", "numero_poliza", "ramo",
                         "vigencia_desde", "vigencia_hasta", "estado", "importe_total"]
                    ]
                    st.dataframe(df, use_container_width=True, hide_index=True)
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
