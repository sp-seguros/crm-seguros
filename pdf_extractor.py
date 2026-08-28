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

# Modelo gratuito recomendado (buena calidad + límite diario amplio).
# Si en algún momento preferís más volumen diario a costa de algo menos
# de precisión, se puede cambiar a "gemini-2.5-flash-lite".
MODEL = "gemini-2.5-flash"

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
  "cantidad_cuotas": integer o null
}

Si un dato no aparece en el documento o no estás seguro, devolvé null para ese campo.
No inventes datos."""


def _get_model():
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
        system_instruction=SYSTEM_PROMPT,
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
    model = _get_model()

    response = model.generate_content(
        [
            {"mime_type": "application/pdf", "data": pdf_bytes},
            "Extraé los datos de esta póliza y devolvé solo el JSON.",
        ]
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
