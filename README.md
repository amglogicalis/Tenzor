# 🔮 Arzor AIs & Tenzor API

> **Suite Profesional de Ingeniería de Software Autónoma**: Agente CLI interactivo local de desarrollo de código y API Gateway de inferencia avanzada especializada en Cloud, DevOps e Ingeniería de Sistemas.

[![Licencia](https://img.shields.io/badge/Licencia-Propietaria-red.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)

---

## 🔮 1. Arzor AIs (Agente de Desarrollo Autónomo Local)

**Arzor AIs** es un cliente de consola (CLI) avanzado y reactivo que ejecuta tareas de desarrollo de software directo sobre tu ordenador. Integra herramientas locales optimizadas de lectura/escritura de código en parches de red ligeros, búsquedas recursivas y control de rondas.

### ⚡ Onboarding e Instalación Automática

Prepara tu entorno e instala el comando `arzor` globalmente en tu terminal ejecutando el script interactivo correspondiente:

#### En Windows 🪟
Abre PowerShell como **Administrador** y ejecuta:
```powershell
Set-ExecutionPolicy RemoteSigned -Scope Process -Force
.\setup.ps1
```
*(O de forma directa omitiendo políticas: `powershell -ExecutionPolicy Bypass -File .\setup.ps1`)*

#### En Linux / macOS 🐧🍎
Ejecuta desde la terminal:
```bash
chmod +x setup.sh
./setup.sh
```

> [!NOTE]
> Tras completar el asistente de setup por primera vez, cierra tu ventana de terminal actual y abre una nueva para que se cargue la variable global `arzor` en tu shell.

---

### 💻 Catálogo de Comandos del CLI

El comando `arzor` expone los siguientes puntos de entrada de primer nivel:

| Categoría | Comando | Descripción |
| :--- | :--- | :--- |
| **Sesión / Acceso** | `arzor login` | Inicia sesión de forma segura y persiste tu token JWT localmente. |
| | `arzor logout` | Cierra la sesión activa borrando el token del entorno local. |
| | `arzor whoami` | Muestra la identidad y correo de la cuenta vinculada al CLI. |
| | `arzor register` | Asistente de registro interactivo en consola para crear cuentas. |
| **Administración** | `arzor list-agents` | Lista los agentes de desarrollo personalizados de tu perfil. |
| | `arzor create-agent` | Asistente por pasos interactivo para compilar nuevos agentes. |
| | `arzor list-models` | Lista todos los modelos activos de tus proveedores configurados. |
| | `arzor status` | Diagnóstico de red, latencia con el servidor y salud del token. |
| | `arzor update` | Descarga de parches y reinstala el CLI en modo editable. |
| **API Keys** | `arzor list-keys` | Muestra tus claves activas ofuscadas con máscara (`sk-****`). |
| | `arzor add-keys [p] [k]` | Registra o actualiza una API key para un proveedor (Groq, Google, etc.). |
| | `arzor remove-keys [p]` | Elimina del servidor la API Key del proveedor indicado. |
| **Ejecución y Test** | `arzor "[tarea]"` | Inicia el bucle autónomo ReAct interactivo para resolver la tarea. |
| | `arzor test-agent [a]` | Ping ligero de inferencia para evaluar la salud del modelo del agente. |
| **Simulación y Deshacer**| `arzor plan "[tarea]"` | Dry-run síncrono en memoria; muestra parches de archivos sin alterar el disco. |
| | `arzor clean` | Revierte y restaura por completo los archivos de la última tarea. |
| **Colaboración** | `arzor debate` | Inicia una mesa redonda interactiva de debate entre tus agentes. |
| | `arzor team "[tarea]"` | Divide una meta-tarea compleja coordinando un equipo en cascada. |

Para instrucciones detalladas, parámetros avanzados del bucle ReAct (`--max-steps`, `--tier`) y ejemplos de uso, consulta el **[Manual Completo del CLI de Arzor AIs](cli_manual.md)**.

---

## 🧠 2. Tenzor API (API Gateway / Wrapper Inferencia)

**Tenzor** es una API Gateway compatible con OpenAI especializada exclusivamente en Ingeniería de Software. Inyecta reglas estrictas de dominio fáctico a modelos base, gestiona cuotas y almacena claves en Supabase de forma transparente.

### 🚀 Inicio Rápido Local (Desarrollo)

1. **Configurar el Entorno**:
   Copia el archivo de variables e ingresa tus API keys:
   ```bash
   cp .env.example .env
   ```
   *Rellena `GROQ_API_KEY`, `GEMINI_API_KEY`, `ADMIN_SECRET_KEY` y opcionalmente tu base de datos de Supabase.*
2. **Preparar Entorno Virtual**:
   ```bash
   python -m venv venv
   # Activar (Ej: Windows PowerShell):
   .\venv\Scripts\Activate.ps1
   # Instalar dependencias:
   pip install -r requirements.txt
   ```
3. **Lanzar el Servidor**:
   ```bash
   python -m uvicorn app.main:app --reload --port 8000
   ```
   *Accede a la documentación Swagger UI interactiva en `http://127.0.0.1:8000/docs`.*

---

### 🛠️ Consumo Compatible con OpenAI

Puedes redirigir tus aplicaciones y librerías de OpenAI (Python/JS SDK) a Tenzor modificando únicamente la URL base y la clave de acceso.

#### Ejemplo de Inferencia con `curl`
```bash
curl -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer tenzor-tu-api-key-de-cliente" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "¿Cómo despliego un clúster de GKE con Terraform?"}
    ],
    "temperature": 0.2
  }'
```

#### Comportamiento del Dominio
* Si preguntas sobre programación o Cloud ➔ Responderá con alto nivel de expertise técnica.
* Si le pides recetas, marketing o preguntas fuera del dominio ➔ Responderá exactamente:
  > *Lo siento, soy una IA especializada exclusivamente en desarrollo de software e infraestructuras Cloud. No puedo ayudarte con ese tema.*

---

### 🔑 Endpoints de Administración de API Keys (`/admin`)

Requieren la cabecera de autenticación `X-Admin-Secret` configurada en tu archivo `.env`.

* **Crear Clave de Cliente**:
  ```bash
  curl -X POST http://127.0.0.1:8000/admin/keys \
    -H "X-Admin-Secret: tu_secreto_admin" \
    -H "Content-Type: application/json" \
    -d '{"owner_name": "Backend Produccion", "rate_limit": 200}'
  ```
* **Listar Claves y Métricas de Uso**:
  ```bash
  curl -X GET http://127.0.0.1:8000/admin/keys -H "X-Admin-Secret: tu_secreto_admin"
  ```
* **Desactivar Clave**:
  ```bash
  curl -X PATCH "http://127.0.0.1:8000/admin/keys/<UUID>/status?is_active=false" -H "X-Admin-Secret: tu_secreto_admin"
  ```

---

### ☁️ Despliegue en la Nube (Render Docker)

1. Sube este repositorio de código a tu cuenta privada de **GitHub**.
2. En [Render.com](https://render.com), crea un nuevo **Web Service** y conéctalo al repositorio.
3. El despliegue se configurará automáticamente como **Docker**.
4. Inyecta tus claves y secretos en la sección de **Variables de Entorno**.
5. ¡Haz clic en desplegar! Tu API estará activa en su URL de Render (ej: `https://tenzor-api.onrender.com`).

---

## 🛡️ 3. Licencia y Restricciones Operativas

Este proyecto se distribuye bajo una **Licencia Propietaria Estricta de Derechos Reservados**. 

Copyright (c) 2026 Adrián (amglogicalis). Todos los derechos reservados.

* **Queda estrictamente prohibido**: La copia, duplicación, clonado, redistribución comercial, sublicenciamiento o alteración del Software sin consentimiento expreso previo por escrito del titular del copyright.
* **Restricción de Inferencia e IA**: Se prohíbe explícitamente el uso de este software, su arquitectura, sus prompts del compilador AFT o su código fuente para el entrenamiento, ajuste fino (fine-tuning) o validación de modelos de Inteligencia Artificial (LLMs) o frameworks competitivos.

Para el texto legal completo y penalizaciones, consulta el archivo **[LICENSE](LICENSE)**.
