"""
pdf_extractor.py
Envía el PDF de la póliza a la API de Claude (modelo con capacidad de
lectura de documentos) y le pide que devuelva SOLO un JSON con los
campos clave. No usamos OCR tradicional: el modelo lee el PDF directamente
(funciona tanto con PDFs nativos como escaneados/imagen).
"""

import base64
import json
import os

import anthropic

MODEL = "claude-sonnet-4-6"

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


def _get_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No se encontró ANTHROPIC_API_KEY en las variables de entorno. "
            "Configurala en el archivo .env"
        )
    return anthropic.Anthropic(api_key=api_key)


def extract_policy_data(pdf_bytes: bytes) -> dict:
    """
    Recibe los bytes crudos de un PDF y devuelve un diccionario con
    los campos extraídos. Lanza excepción si la API falla o si la
    respuesta no es JSON válido.
    """
    client = _get_client()
    b64_pdf = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": b64_pdf,
                        },
                    },
                    {
                        "type": "text",
                        "text": "Extraé los datos de esta póliza y devolvé solo el JSON.",
                    },
                ],
            }
        ],
    )

    raw_text = "".join(
        block.text for block in message.content if block.type == "text"
    ).strip()

    # Por las dudas el modelo agregue fences de markdown, los limpiamos
    cleaned = raw_text.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"La IA no devolvió un JSON válido. Respuesta cruda:\n{raw_text}"
        ) from e

    return data
