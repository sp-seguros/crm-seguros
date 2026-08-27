# CRM de Pólizas y Clientes — PAS (MVP)

Sistema para gestionar cartera de clientes y pólizas, con lectura automática
de PDFs por IA, alertas de vencimiento y control de cobranzas.

## 1. Arquitectura y stack

```
┌─────────────────────┐      ┌───────────────────────┐      ┌──────────────────┐
│   Streamlit (UI)     │─────▶│  pdf_extractor.py       │─────▶│  API de Claude     │
│   app.py             │      │  (arma el prompt +     │      │  (lee el PDF y     │
│                      │      │   llama a la API)       │      │   devuelve JSON)   │
└─────────┬────────────┘      └───────────────────────┘      └──────────────────┘
          │
          ▼
┌─────────────────────┐
│  db.py (SQLite)      │
│  clientes/polizas/    │
│  cuotas/alertas       │
└─────────────────────┘
```

- **Frontend + backend en uno:** Streamlit (Python). Es la opción más rápida
  para tener un CRM funcional sin separar API/frontend. El día que necesites
  multiusuario "de verdad" con roles, se migra a React + FastAPI, pero para
  un productor gestionando su propia cartera esto sobra y funciona muy bien.
- **Lectura de PDFs:** en vez de un OCR clásico (Tesseract) + reglas, se usa
  la API de Claude con "document" input: le mandás el PDF entero (nativo o
  escaneado) y te devuelve un JSON con los campos ya identificados. Esto es
  más robusto que OCR + regex porque entiende el contexto ("esto es un
  número de póliza", "esto es la vigencia hasta") aunque cada aseguradora
  tenga un formato de póliza distinto.
- **Base de datos:** SQLite para el MVP (un solo archivo, cero configuración).
  Cuando quieras acceso desde varios dispositivos o multiusuario, migrás a
  **Supabase** (Postgres gestionado, gratis hasta cierto volumen) — el código
  de `db.py` está aislado para que ese cambio sea acotado (ver sección 5).
- **Alertas:** hoy se generan como registros en la tabla `alertas` (30/15/7
  días antes del vencimiento) y se ven como código de colores en el
  Dashboard. El envío por **email real** (SMTP o servicio como Resend/SendGrid)
  y la ejecución **automática diaria** son el siguiente paso natural (ver
  sección 6, "Próximos pasos").

## 2. Modelo de datos

**`clientes`**
| campo | tipo | notas |
|---|---|---|
| id | INTEGER PK | |
| tipo_persona | TEXT | 'Fisica' / 'Juridica' |
| nombre_razon_social | TEXT | |
| cuit_dni | TEXT UNIQUE | clave de vinculación automática |
| telefono | TEXT | |
| email | TEXT | |
| direccion | TEXT | |
| fecha_alta | TEXT | |

**`polizas`**
| campo | tipo | notas |
|---|---|---|
| id | INTEGER PK | |
| cliente_id | INTEGER FK → clientes | |
| compania_aseguradora | TEXT | |
| numero_poliza | TEXT | |
| ramo | TEXT | Automotor, Hogar, Vida, ART, etc. |
| riesgo_patente | TEXT | patente, dirección, u otro descriptor |
| vigencia_desde / vigencia_hasta | TEXT (YYYY-MM-DD) | |
| importe_total | REAL | premio total |
| cantidad_cuotas | INTEGER | |
| estado | TEXT | Activa / Vencida / Anulada / Renovada |
| pdf_path | TEXT | ruta al PDF original guardado |

**`cuotas`**
| campo | tipo | notas |
|---|---|---|
| id | INTEGER PK | |
| poliza_id | INTEGER FK → polizas | |
| numero_cuota | INTEGER | |
| monto | REAL | |
| fecha_vencimiento | TEXT | generada automáticamente al cargar la póliza |
| fecha_pago | TEXT | null hasta que se marca pagada |
| estado | TEXT | Pendiente / Pagada / Vencida |

**`alertas`**
| campo | tipo | notas |
|---|---|---|
| id | INTEGER PK | |
| poliza_id | INTEGER FK → polizas | |
| tipo | TEXT | Vencimiento_Poliza / Vencimiento_Cuota |
| dias_anticipacion | INTEGER | 30 / 15 / 7 |
| fecha_alerta | TEXT | fecha en la que corresponde alertar |
| enviada | INTEGER (bool) | |
| fecha_envio | TEXT | |

## 3. Cómo correrlo en tu computadora

### Requisitos
- Python 3.10 o superior instalado.
- Una API key de Anthropic (la sacás en https://console.anthropic.com/settings/keys).

### Pasos

```bash
# 1. Entrar a la carpeta del proyecto
cd crm-seguros

# 2. Crear un entorno virtual (recomendado)
python -m venv venv
source venv/bin/activate        # En Windows: venv\Scripts\activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar tu API key
cp .env.example .env
# Abrí el archivo .env y pegá tu API key real:
# ANTHROPIC_API_KEY=sk-ant-tu-key-real

# 5. Levantar la app
streamlit run app.py
```

Se va a abrir automáticamente en `http://localhost:8501`. La base de datos
SQLite se crea sola en `data/crm_seguros.db` la primera vez que corrés la app.

## 4. Cómo desplegarlo gratis (para acceder desde el celular/otra PC)

**Opción recomendada: Streamlit Community Cloud** (gratis, pensado para esto).

1. Subí esta carpeta a un repositorio de GitHub (puede ser privado).
2. Entrá a https://share.streamlit.io/ con tu cuenta de GitHub.
3. "New app" → elegí el repo → archivo principal `app.py`.
4. En "Advanced settings" → "Secrets", pegá:
   ```toml
   ANTHROPIC_API_KEY = "sk-ant-tu-key-real"
   ```
5. Deploy. Te da una URL pública (o restringible por login) para acceder
   desde cualquier dispositivo.

**Importante sobre SQLite en la nube:** Streamlit Community Cloud reinicia el
contenedor de tanto en tanto y el archivo SQLite puede perderse. Para uso
personal esporádico puede alcanzar, pero para producción real te conviene
migrar a Supabase (paso siguiente) para no perder datos.

## 5. Migrar de SQLite a Supabase (cuando lo necesites)

Supabase te da Postgres gestionado gratis (hasta 500MB) más un panel visual.
Los cambios quedan contenidos en `db.py`:

1. Creás un proyecto en https://supabase.com/ (gratis).
2. Instalás el driver: `pip install psycopg2-binary`.
3. Reemplazás `get_connection()` en `db.py` para que use
   `psycopg2.connect(...)` con la connection string que te da Supabase,
   en vez de `sqlite3.connect(DB_PATH)`.
4. Las tablas del `CREATE TABLE` son casi idénticas en Postgres (cambian
   detalles como `AUTOINCREMENT` → `SERIAL`). Te puedo generar ese script
   `schema.sql` para Postgres cuando quieras dar este paso.
5. El resto de la app (`app.py`, `pdf_extractor.py`) no cambia nada.

## 6. Próximos pasos sugeridos (fuera del MVP)

- **Notificaciones reales por email:** un script (`enviar_alertas.py`) que
  recorra la tabla `alertas` con `enviada = 0` y `fecha_alerta <= hoy`, envíe
  el mail (por ejemplo con Resend o SMTP de Gmail) y marque `enviada = 1`.
  Se programa como tarea diaria (cron, o "Scheduled Task" si usás GitHub
  Actions apuntando a tu Supabase).
- **Renovación de pólizas:** botón en el Dashboard para "renovar" una póliza
  vencida, que copie los datos y solo pida la nueva vigencia/premio.
- **Multiusuario con login:** si en algún momento trabajás con sub-productores
  o un asistente, ahí sí conviene sumar `streamlit-authenticator` o migrar el
  frontend a algo con auth más robusto.
- **Exportar a Excel/PDF:** reportes de cartera y de cobranzas para imprimir
  o mandar a la aseguradora.

## 7. Estructura de archivos

```
crm-seguros/
├── app.py              # Interfaz Streamlit (Dashboard, Carga, Clientes, Cobranzas)
├── db.py                # Acceso a datos (SQLite) y lógica de negocio
├── pdf_extractor.py      # Llamada a la API de Claude para leer el PDF
├── requirements.txt
├── .env.example
├── data/                 # Se crea sola: acá vive el archivo .db
└── uploads/               # Se crea sola: PDFs originales guardados
```
