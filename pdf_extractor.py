"""
pdf_extractor.py
Envía el PDF de la póliza a la API GRATUITA de Google Gemini y le pide
que devuelva SOLO un JSON con los campos clave.

Por qué Gemini y no una librería como pypdf/pdfplumber:
- pypdf/pdfplumber solo extraen texto "tal cual" del PDF: no entienden
  qué parte es el CUIT, cuál es la vigencia, etc. Además no funcionan
  con pólizas escaneadas (imagen), que son muy comunes.
- Gemini lee el PDF (texto o escaneado) y devuelve directamente los
  campos identificados, igual que hacíamos antes con la API de Claude,
  pero con una capa 100% gratuita (sin tarjeta) para uso personal.

Conseguir la clave gratis en: https://aistudio.google.com/apikey
"""

import json
import os

import google.generativeai as genai

# Modelo gratuito recomendado: Flash-Lite está pensado justo para tareas de
# extracción de datos de documentos (más rápido y con más margen diario
# gratuito que el modelo Flash completo). Si Google vuelve a actualizar los
# modelos disponibles y este deja de funcionar, el mensaje de error indica
# el nombre del modelo nuevo a usar.
MODEL = "gemini-3.5-flash-lite"

SYSTEM_PROMPT = """Sos un asistente experto en pólizas de seguro argentinas.
Vas a recibir el PDF de una póliza. Tu única tarea es extraer los datos
clave y devolver EXCLUSIVAMENTE un objeto JSON válido, sin texto adicional,
sin markdown, sin explicaciones.

Estructura exacta a devolver:
{
  "nombre_razon_social": string o null,
  "cuit_dni": string o null (solo números, sin puntos ni guiones),
  "tipo_persona": "Fisica" o "Juridica",
  "telefono": string o null,
  "email": string o null,
  "compania_aseguradora": string o null,
  "numero_poliza": string o null,
  "ramo": string o null (ej: Automotor, Hogar, Vida, ART, Comercio),
  "riesgo_patente": string o null (patente del vehículo, dirección del inmueble, u otro descriptor del riesgo asegurado),
  "vigencia_desde": string en formato YYYY-MM-DD o null,
  "vigencia_hasta": string en formato YYYY-MM-DD o null,
  "importe_total": number o null (premio total en pesos, sin símbolo de moneda),
  "cantidad_cuotas": integer o null,
  "forma_pago": string o null (una de: "Debito Automatico", "CBU", "Tarjeta de Credito", "Cuponera", "Mercado Pago" — solo si está explícito en el documento)
}

Si un dato no aparece en el documento o no estás seguro, devolvé null para ese campo.
No inventes datos."""


def _get_model(system_instruction):
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No se encontró GOOGLE_API_KEY en las variables de entorno. "
            "Conseguí una clave gratis en https://aistudio.google.com/apikey "
            "y configurala en el archivo .env (o en 'Secrets' si está en Streamlit Cloud)."
        )
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(
        model_name=MODEL,
        system_instruction=system_instruction,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            temperature=0,
        ),
    )


def extract_policy_data(pdf_bytes: bytes) -> dict:
    """
    Recibe los bytes crudos de un PDF y devuelve un diccionario con
    los campos extraídos. Lanza excepción si la API falla o si la
    respuesta no es JSON válido.
    """
    model = _get_model(SYSTEM_PROMPT)

    response = model.generate_content(
        [
            {"mime_type": "application/pdf", "data": pdf_bytes},
            "Extraé los datos de esta póliza y devolvé solo el JSON.",
        ],
        request_options={"timeout": 90},
    )

    raw_text = (response.text or "").strip()
    cleaned = raw_text.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"La IA no devolvió un JSON válido. Respuesta cruda:\n{raw_text}"
        ) from e

    return data


SYSTEM_PROMPT_NOTAS_RAMO = """Sos un asistente que ayuda a una productora de
seguros argentina a organizar apuntes sueltos que le van dictando sus jefes
sobre qué pedirle a los clientes según el ramo de la póliza (ej: "para auto
pedir cédula verde", "para vida obligatorio de empleada doméstica pedir
tarjeta de crédito", etc.).

Vas a recibir un texto libre, que puede mezclar indicaciones de varios ramos
distintos en el mismo párrafo, o ser sobre un solo ramo. Tu tarea es separarlo
en items individuales, cada uno asociado a UN ramo, y devolver EXCLUSIVAMENTE
un JSON válido con este formato, sin texto adicional ni markdown:

{
  "items": [
    {"ramo": "Automotor", "contenido": "Pedir cédula verde y último recibo de patente."},
    {"ramo": "Vida Obligatorio", "contenido": "Si es empleada doméstica, pedir tarjeta de crédito para el pago."}
  ]
}

Reglas:
- Usá nombres de ramo consistentes y en Argentina (Automotor, Hogar, Vida,
  Vida Obligatorio, ART, Comercio, Responsabilidad Civil, Caución, Otro).
- Si el texto ya viene claramente separado por ramo, respetá esa separación.
- Si menciona una condición particular (ej. "si es empleada doméstica"),
  incluila dentro del texto de "contenido", no la inventes ni la ignores.
- No resumas de más: conservá el detalle práctico tal como lo escribió la
  productora, solo reorganizado y prolijo.
- Si no podés determinar el ramo de una parte del texto, usá "Otro".
- Vas a recibir también una lista de notas QUE YA ESTÁN GUARDADAS. Si algo
  del texto nuevo ya está cubierto por una nota existente (aunque esté
  redactado distinto, con otras palabras), NO la vuelvas a incluir en tu
  respuesta. Devolvé únicamente los items genuinamente nuevos, que agregan
  información que todavía no estaba anotada."""


def _formatear_notas_existentes(notas_existentes) -> str:
    if not notas_existentes:
        return "(Todavía no hay ninguna nota guardada.)"
    return "\n".join(f"- [{n['ramo']}] {n['contenido']}" for n in notas_existentes)


def organizar_notas_por_ramo(texto: str, notas_existentes=None) -> list:
    """
    Recibe un texto libre (posiblemente con notas de varios ramos mezcladas)
    y devuelve una lista de {"ramo": ..., "contenido": ...} ya separados y
    prolijos, usando la IA para clasificar por ramo. Si se pasan
    'notas_existentes' (lista de dicts con 'ramo' y 'contenido'), la IA
    descarta cualquier cosa que ya esté cubierta por esas notas.
    """
    model = _get_model(SYSTEM_PROMPT_NOTAS_RAMO)

    prompt = (
        f"Notas que ya están guardadas:\n{_formatear_notas_existentes(notas_existentes)}\n\n"
        f"Texto nuevo a organizar:\n{texto}"
    )
    response = model.generate_content(
        prompt,
        request_options={"timeout": 60},
    )

    raw_text = (response.text or "").strip()
    cleaned = raw_text.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"La IA no devolvió un JSON válido. Respuesta cruda:\n{raw_text}"
        ) from e

    return data.get("items", [])


SYSTEM_PROMPT_CHAT_WHATSAPP = """Sos un asistente que ayuda a una productora
de seguros argentina a rescatar información útil de una conversación de
WhatsApp exportada (con jefes, compañeros o supervisores), que mezcla charla
cotidiana con instrucciones de trabajo reales.

Vas a recibir el texto crudo de un chat exportado de WhatsApp (con formato
típico "DD/MM/AA, HH:MM - Nombre: mensaje", puede incluir líneas como
"<Multimedia omitido>" que debés ignorar).

Tu tarea es leer TODO el chat y quedarte EXCLUSIVAMENTE con los mensajes que
sean indicaciones de trabajo relacionadas a pólizas de seguro: qué pedirle a
un cliente según el ramo, requisitos de documentación, condiciones
particulares (ej. "si es empleada doméstica pedir tarjeta de crédito"),
procedimientos internos, etc. IGNORÁ por completo saludos, charla personal,
chistes, coordinación de horarios, o cualquier cosa que no sea una
indicación de trabajo concreta sobre seguros.

Devolvé EXCLUSIVAMENTE un JSON válido, sin texto adicional ni markdown, con
este formato:

{
  "items": [
    {"ramo": "Automotor", "contenido": "Pedir cédula verde y último recibo de patente."},
    {"ramo": "Vida Obligatorio", "contenido": "Si es empleada doméstica, pedir tarjeta de crédito para el pago."}
  ]
}

Reglas:
- Usá nombres de ramo consistentes (Automotor, Hogar, Vida, Vida Obligatorio,
  ART, Comercio, Responsabilidad Civil, Caución, Otro).
- Si un mismo tema se repite en varios mensajes del chat, unificalo en un
  solo item (no dupliques).
- Si el chat no tiene ninguna indicación relevante de seguros, devolvé
  "items": [] (una lista vacía), no inventes nada.
- Vas a recibir también una lista de notas QUE YA ESTÁN GUARDADAS de cargas
  anteriores. Si algo del chat ya está cubierto por una nota existente
  (aunque esté escrito distinto), NO la vuelvas a incluir. Devolvé
  únicamente información genuinamente nueva."""


def organizar_notas_desde_chat(texto_chat: str, notas_existentes=None):
    """
    Recibe el texto crudo de un chat de WhatsApp exportado y devuelve solo
    los items relevantes a seguros, organizados por ramo, ignorando charla
    que no tenga que ver con el trabajo.

    Procesa el chat COMPLETO sin importar cuán largo sea: si supera un
    tamaño manejable por llamada, lo divide en tramos y hace varias
    llamadas seguidas a la IA. Cada tramo "ve" lo que ya se encontró en los
    tramos anteriores (y lo que ya estaba guardado de antes), para no
    duplicar información entre tramos.

    Devuelve (items_nuevos, cantidad_de_tramos_procesados).
    """
    TAMANIO_TRAMO = 80_000
    MAX_TRAMOS = 20  # ~1.600.000 caracteres en total como techo razonable

    tramos = [
        texto_chat[i:i + TAMANIO_TRAMO]
        for i in range(0, len(texto_chat), TAMANIO_TRAMO)
    ] or [""]

    if len(tramos) > MAX_TRAMOS:
        tramos = tramos[-MAX_TRAMOS:]  # se queda con la parte más reciente

    model = _get_model(SYSTEM_PROMPT_CHAT_WHATSAPP)
    notas_acumuladas = list(notas_existentes or [])
    items_nuevos_totales = []

    for idx, tramo in enumerate(tramos):
        prompt = (
            f"Notas que ya están guardadas o ya encontradas en tramos anteriores "
            f"de este mismo chat:\n{_formatear_notas_existentes(notas_acumuladas)}\n\n"
            f"Este es el tramo {idx + 1} de {len(tramos)} del chat exportado:\n\n{tramo}"
        )
        response = model.generate_content(prompt, request_options={"timeout": 90})

        raw_text = (response.text or "").strip()
        cleaned = raw_text.replace("```json", "").replace("```", "").strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"La IA no devolvió un JSON válido en el tramo {idx + 1} de {len(tramos)}. "
                f"Respuesta cruda:\n{raw_text}"
            ) from e

        nuevos = data.get("items", [])
        items_nuevos_totales.extend(nuevos)
        notas_acumuladas.extend(nuevos)

    return items_nuevos_totales, len(tramos)
