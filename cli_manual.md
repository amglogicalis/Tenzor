# Manual del CLI de Arzor AIs 🔮

El CLI de **Arzor AIs** es tu asistente de desarrollo autónomo local (equivalente a tu propio *antigravity/codex*). Este cliente interactúa directamente con los archivos y la terminal de tu máquina para resolver tareas de programación, DevOps e infraestructura de forma automática, utilizando los agentes y modelos configurados en tu cuenta de Arzor.

---

## 🚀 Instalación y Configuración

### 1. Requisitos Previos
* Python 3.9 o superior.
* Acceso a internet para comunicarse con el servidor de Arzor AIs.

### 2. Registro del Comando Global `arzor`
Para poder ejecutar el comando `arzor` desde cualquier directorio de tu ordenador sin anteponer la ruta de Python, clona el repositorio y ejecuta en tu terminal:

```bash
pip install -e .
```
*(El flag `-e` indica modo editable, lo que permite que cualquier cambio que se haga en el código se aplique al instante sin reinstalar).*

### ⚡ Onboarding e Instalación Automática (Recomendado)

El repositorio incluye asistentes de instalación que preparan el entorno virtual, configuran tus variables de conexión en el `.env`, registran el comando `arzor` en el PATH de tu usuario e inician el login de forma interactiva:

#### En Windows 🪟
Abre PowerShell como **Administrador** y ejecuta:
```powershell
Set-ExecutionPolicy RemoteSigned -Scope Process -Force
.\setup.ps1
```
*(O puedes ejecutarlo omitiendo políticas temporales: `powershell -ExecutionPolicy Bypass -File .\setup.ps1`)*.

#### En Linux / macOS 🐧🍎
Abre tu terminal y ejecuta:
```bash
chmod +x setup.sh
./setup.sh
```

**Nota**: Tras completar el asistente de setup por primera vez, cierra tu ventana de terminal actual y abre una nueva para que se cargue el comando `arzor` global en tu sistema.


#### Configuración del PATH en Windows (si no se reconoce el comando):
Si al ejecutar `arzor` recibes un error de "comando no reconocido", añade la carpeta de scripts de Python a tu variable de entorno `PATH` de Windows.
* **Si instalaste como usuario (User Roaming)**:
  ```powershell
  [Environment]::SetEnvironmentVariable("PATH", [Environment]::GetEnvironmentVariable("PATH", "User") + ";C:\Users\$env:USERNAME\AppData\Roaming\Python\Python314\Scripts", "User")
  ```
  *(Reemplaza `Python314` por tu versión de Python, por ejemplo `Python312` o `Python311`)*.
* **Si instalaste a nivel de sistema**:
  ```powershell
  [Environment]::SetEnvironmentVariable("PATH", [Environment]::GetEnvironmentVariable("PATH", "User") + ";C:\Python314\Scripts", "User")
  ```
* **¡Importante!** Cierra tu terminal de PowerShell y abre una nueva ventana para que se aplique la variable.

#### Configuración del PATH en Linux/macOS:
Asegúrate de que el directorio de binarios locales de usuario esté en tu `$PATH`:
```bash
export PATH="$HOME/.local/bin:$PATH"
```
Puedes agregar esta línea a tu archivo de configuración del shell (`~/.bashrc` o `~/.zshrc`).

---

## 🔑 Autenticación (`login`)

El CLI requiere un token JWT para comunicarse de forma segura con el backend. Para evitar tener que copiarlo manualmente del navegador, puedes iniciar sesión directamente desde la terminal:

```bash
arzor login
```
* Te pedirá de forma interactiva tu **Email** y tu **Contraseña** (oculta por seguridad).
* Tras validar con el servidor, guardará tu token de sesión automáticamente en el archivo `.env` local (`ARZOR_TOKEN="..."`).

---

## 📋 Comandos de Administración

### 1. Listar tus Agentes Personalizados
Muestra la lista de todos tus agentes especializados creados en tu cuenta, detallando su UUID, categoría, tier de calidad e IA preferida:
```bash
arzor list-agents
```

### 2. Crear un Agente Nuevo (Asistente Interactivo)
Inicia un asistente interactivo por consola en **6 pasos** para registrar un nuevo agente en tu cuenta, seleccionando dinámicamente tu proveedor e IA de una lista numerada:
```bash
arzor create-agent
```
El asistente te guiará de forma estructurada:
* **Nombre** y **Descripción**.
* **Categoría** (dev, ops, data, science, creative, custom).
* **Selección de Proveedor**: Escoge el proveedor (Google, Groq, DeepSeek, Anthropic, etc.) desde una lista numerada.
* **Selección de Modelo**: Muestra en tiempo real la lista numerada de modelos de codificación activos en tu cuenta para ese proveedor para que elijas uno al instante.
* **Instrucciones de Sistema**: Define las reglas de comportamiento y la personalidad del agente.
*(El nivel de Tier se calcula automáticamente en base al modelo elegido, facilitando la configuración).*


### 3. Listar Modelos de Programación Disponibles
Consulta al servidor y lista los modelos de IA activos para tu cuenta en base a tus API Keys, **filtrando exclusivamente** aquellos aptos para programación y desarrollo (oculta modelos conversacionales genéricos):
```bash
arzor list-models
```

### 4. Debates Multi-Agente (`debate` / `round-table`)
Inicia discusiones y debates síncronos en tiempo real entre múltiples agentes de tu cuenta sobre cualquier pregunta técnica o de arquitectura:
```bash
arzor debate
```
* **Asistente interactivo**: Permite elegir una mesa redonda existente o crear una nueva (Nombre, Tema, Rondas) seleccionando de 2 a 5 agentes participantes.
* **Chat animado con colores**: Pinta las intervenciones de cada agente miembro en formato chat coloreado y finaliza imprimiendo una síntesis/conclusión escrita por el moderador de la mesa redonda.

### 5. Colaboración en Equipos Locales (`team`)
Ejecuta tareas complejas dividiéndolas en subtareas y coordinando secuencialmente a un equipo de tus agentes en tu máquina local:
```bash
arzor team "Diseña un CRUD de usuarios, escribe la API y realiza tests en pytest" --agents "Dev DB, Dev Backend, Dev Tester"
```
* **Coordinación Inteligente**: Un agente Coordinador del sistema analiza la tarea y las habilidades de tus agentes y diseña un plan secuencial de subtareas.
* **Cascada local autónoma**: Ejecuta de forma secuencial cada subtarea llamando al agente asignado en tu máquina de desarrollo. Cada agente trabaja directamente sobre el código local construido por el agente anterior, completando el ciclo colaborativo.


---

## 🤖 Ejecución de Tareas Autónomas (Bucle ReAct)

Para lanzar al agente autónomo a resolver una tarea de codificación o sistema en tu ordenador, escribe tu prompt directamente como argumento principal:

```bash
arzor "Crea un script en Python que analice el archivo logs.txt y extraiga las IPs"
```

### Parámetros Disponibles:
* `--agent "Nombre o UUID"`: Especifica qué agente especializado de tu cuenta deseas utilizar. Si escribes el nombre del agente (ej. `"Dev Python"`), el CLI resolverá automáticamente su UUID consultando al servidor.
* `--tier {fast,balanced,pro}`: Indica la calidad del modelo (por defecto `balanced`).
* `-y`, `--yes`: **Modo automático (no interactivo)**. El agente ejecutará comandos del sistema y escribirá/modificará archivos locales sin pedirte confirmación.
* `--url "URL"`: Sobrescribe temporalmente la URL del servidor de Arzor.

---

## 🛡️ Seguridad y Confirmación Interactiva

Por defecto (sin el flag `-y`), el CLI actúa de forma segura pidiéndote confirmación interactiva por consola `[Y/n]` antes de ejecutar cualquier acción destructiva o invasiva en tu ordenador:

* **Modificación y Creación de Archivos**: Muestra la ruta del archivo y los cambios a realizar.
* **Ejecución de Comandos**: Muestra el comando exacto antes de ejecutarlo en tu shell de PowerShell/Bash.

---

## 🔍 Resolución de Problemas

* **Errores de codificación de caracteres (Unicode / Emoji)**:
  El CLI reconfigura automáticamente el flujo de salida a UTF-8. En Windows, si estás en una versión muy antigua de PowerShell, es recomendable ejecutar `chcp 65001` en tu terminal antes de usar el CLI para garantizar compatibilidad total con emojis y símbolos de barra.
* **Servidor local vs producción**:
  Puedes cambiar el servidor al que se conecta el CLI editando la variable `ARZOR_URL` en tu archivo `.env`:
  - Producción: `ARZOR_URL="https://tenzor-web.onrender.com"`
  - Desarrollo local: `ARZOR_URL="http://localhost:8000"`
