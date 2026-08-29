# CRM de Pólizas y Clientes — PAS (MVP)

Sistema para gestionar cartera de clientes y pólizas, con lectura automática
de PDFs por IA, alertas de vencimiento y control de cobranzas.

## 1. Arquitectura y stack

```
┌─────────────────────┐      ┌───────────────────────┐      ┌──────────────────┐
│   Streamlit (UI)     │─────▶│  pdf_extractor.py       │─────▶│  API de Gemini     │
│   app.py             │      │  (arma el prompt +     │      │  (gratis, lee el   │
│                      │      │   llama a la API)       │      │   PDF y devuelve   │
│                      │      │                         │      │   JSON)            │
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
  la API **gratuita** de Google Gemini: le mandás el PDF entero (nativo o
  escaneado) y te devuelve un JSON con los campos ya identificados. Esto es
  más robusto que librerías como pypdf/pdfplumber porque esas solo extraen
  texto plano (y no funcionan con pólizas escaneadas como imagen); Gemini
  en cambio entiende el contexto ("esto es un número de póliza", "esto es
  la vigencia hasta") aunque cada aseguradora tenga un formato distinto, y
  no requiere tarjeta de crédito para la capa gratuita.
  Límites de la capa gratuita (uso personal, sin costo): hasta ~250
  pólizas por día con el modelo `gemini-2.5-flash`, que alcanza de sobra
  para la carga normal de un productor. Si algún día necesitás más
  volumen, alcanza con activar facturación en el mismo proyecto de Google
  Cloud — el código no cambia.
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
- Una API key **gratuita** de Google Gemini (sin tarjeta): la sacás en
  https://aistudio.google.com/apikey con cualquier cuenta de Google, en
  menos de dos minutos ("Get API key" → "Create API key").

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
# GOOGLE_API_KEY=AIzaSy-tu-key-real

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
   GOOGLE_API_KEY = "AIzaSy-tu-key-real"
   ```
5. Deploy. Te da una URL pública (o restringible por login) para acceder
   desde cualquier dispositivo.

**Importante sobre SQLite en la nube:** Streamlit Community Cloud reinicia el
contenedor de tanto en tanto y el archivo SQLite puede perderse. Para uso
personal esporádico puede alcanzar, pero para producción real te conviene
migrar a Supabase (paso siguiente) para no perder datos.

## 5. Base de datos: Supabase (PostgreSQL) — obligatorio

El sistema usa **Supabase** como base de datos permanente. A diferencia del
SQLite local de las primeras versiones, estos datos **no se pierden** cuando
Streamlit Cloud reinicia el servidor.

### Crear tu proyecto de Supabase (gratis, sin tarjeta)

1. Entrá a https://supabase.com/ y creá una cuenta (podés usar tu cuenta de GitHub).
2. Hacé clic en "New Project". Elegí un nombre (ej: `crm-seguros`) y una
   **contraseña de base de datos** — anotala, la vas a necesitar.
3. Esperá 1-2 minutos mientras Supabase prepara tu base de datos.
4. Una vez lista, andá a **Project Settings** (ícono de engranaje) → **Database**.
5. Buscá la sección **"Connection string"** → pestaña **"URI"**. Copiá esa
   cadena completa (empieza con `postgresql://postgres:...`).
6. Reemplazá `[YOUR-PASSWORD]` dentro de esa cadena por la contraseña que
   pusiste en el paso 2.

### Configurar la conexión

En tu archivo `.env` local (o en "Secrets" de Streamlit Cloud), agregá:

```
SUPABASE_DB_URL=postgresql://postgres:tu-password-real@db.xxxxxxxxxxxx.supabase.co:5432/postgres
```

No hace falta crear las tablas a mano: la app las crea solas la primera vez
que arranca (`db.init_db()`).

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
