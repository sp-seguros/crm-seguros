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
- Si no podés determinar el ramo de una parte del texto, usá "Otro"."""


def organizar_notas_por_ramo(texto: str) -> list:
    """
    Recibe un texto libre (posiblemente con notas de varios ramos mezcladas)
    y devuelve una lista de {"ramo": ..., "contenido": ...} ya separados y
    prolijos, usando la IA para clasificar por ramo.
    """
    model = _get_model(SYSTEM_PROMPT_NOTAS_RAMO)

    response = model.generate_content(
        f"Organizá estas notas por ramo:\n\n{texto}",
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
