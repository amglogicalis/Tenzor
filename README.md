# 🧠 Tenzor API

Tenzor es una API privada e independiente de Inteligencia Artificial especializada exclusivamente en desarrollo de software, DevOps, e infraestructuras Cloud (AWS, Azure, GCP, Terraform, Docker, Kubernetes, CI/CD).

El proyecto está diseñado como un **API Gateway / Wrapper inteligente** que inyecta reglas estrictas a modelos base de alto rendimiento (Groq / Gemini) y gestiona un sistema de API Keys propio almacenado en Supabase, todo de manera 100% gratuita.

---

## 🚀 Inicio Rápido (Local)

### 1. Requisitos Previos
Asegúrate de tener Python 3.10+ instalado en tu máquina.

### 2. Configurar Variables de Entorno
Copia el archivo de plantilla y renómbralo a `.env`:
```bash
cp .env.example .env
```
Abre `.env` y rellena tus claves:
- `GROQ_API_KEY`: Tu API Key gratuita de [Groq Console](https://console.groq.com).
- `GEMINI_API_KEY`: Tu API Key del plan Google AI PRO.
- `ADMIN_SECRET_KEY`: Una clave secreta inventada por ti para proteger los endpoints de creación de API Keys.
- *(Opcional)* `SUPABASE_URL` y `SUPABASE_KEY`: Credenciales de tu base de datos de Supabase. Si las dejas vacías, la API funcionará en **Modo Desarrollo (Dev Mode)** y aceptará cualquier key de cliente que comience con `tenzor-`.

### 3. Ejecutar la Aplicación
1. Crea y activa el entorno virtual:
   ```bash
   python -m venv venv
   # En Windows (PowerShell):
   .\venv\Scripts\Activate.ps1
   # En Linux/macOS:
   source venv/bin/activate
   ```
2. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```
3. Inicia el servidor de desarrollo:
   ```bash
   python -m uvicorn app.main:app --reload --port 8000
   ```

El servidor estará corriendo en `http://127.0.0.1:8000`. Puedes abrir la documentación interactiva (Swagger UI) en `http://127.0.0.1:8000/docs`.

---

## 🛠️ Cómo Utilizar la API (OpenAI-Compatible)

Tenzor es 100% compatible con el formato oficial de OpenAI. Esto significa que puedes usar las librerías oficiales de OpenAI en tus proyectos de Python o JS cambiando únicamente la URL base y la clave de acceso.

### Ejemplo con `curl`:
```bash
curl -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer tenzor-tu-api-key-de-cliente" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "¿Cómo despliego un bucket de S3 con Terraform?"}
    ],
    "temperature": 0.7
  }'
```

### Comportamiento de Filtrado (System Prompt):
- Si preguntas algo de programación o Cloud, Tenzor responderá de forma experta y concisa.
- Si le pides una receta de pizza, ayuda con marketing o cualquier tema no-IT, responderá exactamente:
  > *Lo siento, soy una IA especializada exclusivamente en desarrollo de software e infraestructuras Cloud. No puedo ayudarte con ese tema.*

---

## 🔑 Gestión de API Keys (Endpoints de Administración)

Para crear, desactivar o listar las API Keys que das a tus usuarios o usas en otros proyectos, usa los endpoints `/admin`. Todas las peticiones al admin deben llevar la cabecera `X-Admin-Secret` con el valor que configuraste en tu `.env`.

### 1. Crear una API Key para un usuario o proyecto:
```bash
curl -X POST http://127.0.0.1:8000/admin/keys \
  -H "X-Admin-Secret: tu_clave_secreta_admin" \
  -H "Content-Type: application/json" \
  -d '{
    "owner_name": "Proyecto React",
    "rate_limit": 150
  }'
```
*Devuelve la API Key generada (Ej: `tenzor-31a89bc...`). Guárdala bien ya que no se puede volver a mostrar.*

### 2. Listar todas las API Keys y su uso:
```bash
curl -X GET http://127.0.0.1:8000/admin/keys \
  -H "X-Admin-Secret: tu_clave_secreta_admin"
```

### 3. Desactivar / Activar una Key:
```bash
curl -X PATCH "http://127.0.0.1:8000/admin/keys/<UUID_DE_LA_LLAVE>/status?is_active=false" \
  -H "X-Admin-Secret: tu_clave_secreta_admin"
```

---

## 🚀 Despliegue en Render (100% Gratis)

1. Sube este repositorio de código a tu cuenta privada de **GitHub** o **GitLab**.
2. Entra en [Render.com](https://render.com) y crea un nuevo **Web Service**.
3. Conéctalo a tu repositorio.
4. Render detectará el `Dockerfile` automáticamente. Asegúrate de configurar la opción de despliegue como **Docker**.
5. En la sección de **Environment Variables** de Render, añade tus variables de entorno:
   - `GROQ_API_KEY`
   - `GEMINI_API_KEY`
   - `ADMIN_SECRET_KEY`
   - `SUPABASE_URL`
   - `SUPABASE_KEY`
6. ¡Haz clic en Desplegar! Tu API tendrá una URL pública (ej: `https://tenzor-api.onrender.com`) lista para consumir 24/7.

---

## 🔮 Arzor AIs CLI (Agente de Desarrollo Autónomo local)

El proyecto incluye un potente cliente de consola autónomo e interactivo que ejecuta tareas de desarrollo local en tu ordenador:

* **Inicio de Sesión e Integración**: `arzor login`
* **Administración**: `arzor list-agents`, `arzor create-agent`, `arzor list-models`
* **Ejecución de Tareas ReAct**: `arzor "Crea un script que consuma la API"`

### ⚡ Onboarding e Instalación Automática (Recomendado)

Puedes preparar el entorno e instalar el comando `arzor` globalmente ejecutando el script interactivo correspondiente en la raíz del proyecto:

#### En Windows 🪟
Abre PowerShell como **Administrador** y ejecuta:
```powershell
Set-ExecutionPolicy RemoteSigned -Scope Process -Force
.\setup.ps1
```
*(O de forma directa omitiendo políticas: `powershell -ExecutionPolicy Bypass -File .\setup.ps1`)*.

#### En Linux / macOS 🐧🍎
Abre tu terminal y ejecuta:
```bash
chmod +x setup.sh
./setup.sh
```

**Nota**: Tras completar el asistente de setup por primera vez, cierra tu ventana de terminal actual y abre una nueva para que se cargue el comando `arzor` global en tu sistema.

Para obtener instrucciones completas, explicaciones detalladas de comandos y ejemplos de uso, consulta el **[Manual del CLI de Arzor AIs](cli_manual.md)**.


