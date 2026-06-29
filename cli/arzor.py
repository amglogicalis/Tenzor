#!/usr/bin/env python3
"""
arzor.py
Agente CLI de Desarrollo Autónomo de Arzor AIs (el 'antigravity/codex' local).

Este cliente corre en la máquina local del desarrollador y ejecuta de forma autónoma
o guiada tareas de desarrollo utilizando los modelos y claves configurados en la plataforma.

Variables de entorno requeridas:
  ARZOR_TOKEN   → Token JWT de sesión (obtenido al registrarse/iniciar sesión)
  ARZOR_URL     → URL base del servidor de Arzor (default: http://localhost:8000)
"""
import os
import sys
import json
import argparse
import subprocess
import textwrap
from typing import List, Dict, Any, Optional

import requests
from dotenv import load_dotenv
import getpass
import threading
import time

# Asegurar la codificación UTF-8 en la consola para evitar fallos de Unicode en Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# Cargar variables de entorno de .env local si existe
load_dotenv()

DEFAULT_URL = os.getenv("ARZOR_URL", "http://localhost:8000")
TOKEN = os.getenv("ARZOR_TOKEN", "")

CODING_MODELS_WHITELIST = {
    # Google Gemini
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    
    # Groq
    "llama-3.3-70b-versatile",
    
    # DeepSeek
    "deepseek-chat",
    "deepseek-reasoner",
    
    # Mistral
    "codestral-latest",
    "mistral-large-latest",
    
    # Cerebras
    "llama3.1-70b",
    
    # SambaNova
    "DeepSeek-V3",
    "Meta-Llama-3.1-70B-Instruct",
    
    # SiliconFlow
    "deepseek-ai/DeepSeek-V3",
    "deepseek-ai/DeepSeek-R1",
    
    # Anthropic
    "claude-3-5-sonnet-20241022",
    
    # Cohere
    "command-r-plus",
    
    # Ollama
    "ollama/qwen2.5:latest",
    "ollama/llama3:latest",
}

def is_coding_model(model_id: str, provider: str) -> bool:
    """Evalúa si un modelo es de primer nivel para desarrollo, programación e informática."""
    m_id = model_id.strip().lower()
    
    # 1. Coincidencia exacta en la whitelist (insensible a mayúsculas)
    if model_id in CODING_MODELS_WHITELIST or m_id in CODING_MODELS_WHITELIST:
        return True
        
    # 2. Filtrado dinámico por términos clave (para OpenRouter u otros proveedores)
    keywords = ["coder", "coding", "reasoning", "r1", "v3", "instruct", "codestral"]
    if any(k in m_id for k in keywords):
        return True
        
    return False


COLORS = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "purple": "\033[35m",
    "cyan": "\033[36m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "gray": "\033[90m",
    "white": "\033[97m",
}

def c(text: str, color: str) -> str:
    """Aplica color ANSI al texto si la terminal lo soporta."""
    if not sys.stdout.isatty():
        return text
    return f"{COLORS.get(color, '')}{text}{COLORS['reset']}"

class Spinner:
    def __init__(self, message="Cargando"):
        self.message = message
        self.frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.stop_running = threading.Event()
        self.thread = None

    def _spin(self):
        idx = 0
        while not self.stop_running.is_set():
            frame = self.frames[idx % len(self.frames)]
            sys.stdout.write(f"\r  {COLORS['cyan']}{frame}{COLORS['reset']} {self.message}...")
            sys.stdout.flush()
            idx += 1
            time.sleep(0.1)
        # Limpiar la línea al salir
        sys.stdout.write("\r" + " " * (len(self.message) + 15) + "\r")
        sys.stdout.flush()

    def __enter__(self):
        if sys.stdout.isatty():
            self.thread = threading.Thread(target=self._spin, daemon=True)
            self.thread.start()
        else:
            sys.stdout.write(f"  {self.message}...\n")
            sys.stdout.flush()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.thread:
            self.stop_running.set()
            self.thread.join(timeout=1.0)

def header():
    print()
    print(c("  🔮 Arzor AIs CLI Agent", "purple") + c(" — Asistente de Desarrollo Autónomo (BYOK)", "gray"))
    print(c("  " + "═" * 60, "gray"))
    print()

# ─── Herramientas Locales de Python ──────────────────────────────────────────

def list_directory(path: str = ".") -> str:
    """Lista el contenido de un directorio local."""
    try:
        if not os.path.exists(path):
            return f"Error: El directorio '{path}' no existe."
        if not os.path.isdir(path):
            return f"Error: '{path}' no es un directorio."
        
        items = os.listdir(path)
        result = []
        for item in sorted(items):
            full_path = os.path.join(path, item)
            if os.path.isdir(full_path):
                result.append(f"📁 {item}/")
            else:
                size = os.path.getsize(full_path)
                result.append(f"📄 {item} ({size} bytes)")
        
        return "\n".join(result) if result else "(directorio vacío)"
    except Exception as e:
        return f"Error al listar directorio: {str(e)}"

def read_file_content(path: str) -> str:
    """Lee y devuelve el contenido de un archivo local."""
    try:
        if not os.path.exists(path):
            return f"Error: El archivo '{path}' no existe."
        if os.path.isdir(path):
            return f"Error: '{path}' es un directorio, usa list_directory."
            
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception as e:
        return f"Error al leer archivo: {str(e)}"

def write_file_content(path: str, content: str) -> str:
    """Escribe o crea un archivo local con el contenido dado."""
    try:
        dir_name = os.path.dirname(path)
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)
            
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Éxito: Archivo '{path}' escrito correctamente."
    except Exception as e:
        return f"Error al escribir archivo: {str(e)}"

def edit_file_content(path: str, target_text: str, replacement_text: str) -> str:
    """Reemplaza un fragmento de texto exacto en un archivo local."""
    try:
        if not os.path.exists(path):
            return f"Error: El archivo '{path}' no existe."
            
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
            
        if target_text not in content:
            return f"Error: No se encontró la coincidencia exacta de 'target_text' en el archivo '{path}'."
            
        new_content = content.replace(target_text, replacement_text, 1)
        
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return f"Éxito: Archivo '{path}' modificado correctamente."
    except Exception as e:
        return f"Error al editar archivo: {str(e)}"

def execute_system_command(command: str) -> str:
    """Ejecuta un comando de consola del sistema operativo y devuelve stdout/stderr."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60
        )
        output = []
        if result.stdout:
            output.append(f"[stdout]\n{result.stdout}")
        if result.stderr:
            output.append(f"[stderr]\n{result.stderr}")
            
        status = f"Retorno: {result.returncode}"
        output.append(status)
        
        return "\n".join(output) if output else "(sin salida)"
    except subprocess.TimeoutExpired:
        return "Error: Tiempo de ejecución excedido (Timeout de 60s)."
    except Exception as e:
        return f"Error al ejecutar comando: {str(e)}"

# ─── API Client Helpers ───────────────────────────────────────────────────────

def _headers() -> Dict[str, str]:
    headers = {}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    return headers

def api_get(path: str, base_url: str) -> Any:
    url = f"{base_url}{path}"
    try:
        resp = requests.get(url, headers=_headers(), timeout=45)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        detail = str(e)
        try:
            detail = e.response.json().get("detail", detail)
        except Exception:
            pass
        raise RuntimeError(detail)
        
    try:
        return resp.json()
    except json.JSONDecodeError:
        if "html" in resp.headers.get("Content-Type", "").lower() or resp.text.strip().startswith("<!DOCTYPE"):
            raise RuntimeError("El servidor de Arzor respondió con una página HTML en lugar de datos JSON. Verifica que la dirección URL (ARZOR_URL) apunte a la API de tu backend y no al frontend web.")
        raise RuntimeError(f"El servidor devolvió una respuesta no válida (no es JSON): {resp.text[:200]}")

def api_post(path: str, payload: dict, base_url: str) -> Any:
    url = f"{base_url}{path}"
    headers = _headers()
    headers["Content-Type"] = "application/json"
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        detail = str(e)
        try:
            detail = e.response.json().get("detail", detail)
        except Exception:
            pass
        raise RuntimeError(detail)
        
    try:
        return resp.json()
    except json.JSONDecodeError:
        if "html" in resp.headers.get("Content-Type", "").lower() or resp.text.strip().startswith("<!DOCTYPE"):
            raise RuntimeError("El servidor de Arzor respondió con una página HTML en lugar de datos JSON. Verifica que la dirección URL (ARZOR_URL) apunte a la API de tu backend y no al frontend web.")
        raise RuntimeError(f"El servidor devolvió una respuesta no válida (no es JSON): {resp.text[:200]}")


def resolve_agent_id(agent_name_or_id: str, base_url: str) -> str:
    """Intenta buscar un agente por nombre en la cuenta del usuario para resolver su UUID."""
    if not agent_name_or_id:
        return ""
    try:
        data = api_get("/platform/agents", base_url)
        agents = data.get("agents", [])
        for agent in agents:
            # Coincidencia exacta por ID
            if agent["id"] == agent_name_or_id:
                return agent["id"]
            # Coincidencia por nombre (ignora mayúsculas/minúsculas)
            if agent["name"].strip().lower() == agent_name_or_id.strip().lower():
                return agent["id"]
        return agent_name_or_id  # Fallback a devolver el mismo string (podría ser un UUID directo)
    except Exception:
        return agent_name_or_id

def save_token_to_env(token: str):
    """Guarda o actualiza la variable ARZOR_TOKEN en el archivo .env del directorio actual."""
    env_path = ".env"
    lines = []
    token_inserted = False
    
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        for i, line in enumerate(lines):
            if line.strip().startswith("ARZOR_TOKEN="):
                lines[i] = f'ARZOR_TOKEN="{token}"\n'
                token_inserted = True
                break
                
    if not token_inserted:
        lines.append(f'\nARZOR_TOKEN="{token}"\n')
        
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

def cmd_login(base_url: str):
    """Inicia sesión en Arzor de forma interactiva y guarda el token JWT en el .env."""
    header()
    print(c("  🔑 Iniciar sesión en tu cuenta de Arzor AIs 🔑", "cyan"))
    try:
        email = input(c("  Email:      ", "bold")).strip()
        if not email:
            print(c("  ✗ Error: El email es obligatorio.", "red"))
            return
            
        password = getpass.getpass(c("  Contraseña: ", "bold")).strip()
        if not password:
            print(c("  ✗ Error: La contraseña es obligatoria.", "red"))
            return
            
        print()
        payload = {"email": email, "password": password}
        with Spinner("Autenticando credenciales con el servidor"):
            result = api_post("/platform/auth/login", payload, base_url)
        
        token = result.get("access_token")
        if not token:
            print(c("  ✗ Error: El servidor no devolvió un token de acceso válido.", "red"))
            return
            
        save_token_to_env(token)
        # Actualizar la variable en memoria para esta sesión
        global TOKEN
        TOKEN = token
        
        print(c("  ✅ ¡Inicio de sesión exitoso!", "green"))
        print(c(f"     Usuario: {result.get('display_name') or result.get('username') or email}", "white"))
        print(c("     El token JWT se ha guardado en tu archivo .env local.", "gray"))
        print()
    except KeyboardInterrupt:
        print(c("\n\n  ✗ Inicio de sesión cancelado por el usuario.", "red"))
        print()
    except Exception as e:
        print(c(f"  ✗ Error al iniciar sesión: {e}", "red"))
        print()


# ─── Comandos CLI Expandidos ──────────────────────────────────────────────────

def cmd_list_agents(base_url: str):
    """Muestra la lista de agentes del usuario en consola."""
    header()
    if not TOKEN:
        print(c("  ✗ Error: ARZOR_TOKEN no configurado.", "red"))
        return
        
    print()
    try:
        with Spinner("Obteniendo tus agentes personalizados"):
            data = api_get("/platform/agents", base_url)
        agents = data.get("agents", [])
        if not agents:
            print(c("  No tienes agentes creados todavía.", "yellow"))
            print(c("  Crea uno interactivamente con: python cli/arzor.py create-agent", "gray"))
            print()
            return
            
        print()
        for idx, agent in enumerate(agents, start=1):
            category_icon = {"dev": "💻", "ops": "⚙️", "data": "📊", "science": "🔬", "creative": "🎨"}.get(agent.get("category", ""), "🤖")
            agent_id = agent["id"]
            print(f"  {idx}. {category_icon}  {c(agent['name'], 'bold')} {c(f'[{agent_id}]', 'gray')}")
            print(f"     Descripción:  {agent.get('description') or 'Sin descripción.'}")
            print(f"     Categoría:    {c(agent.get('category','custom').upper(), 'cyan')}  |  Tier: {c(agent.get('base_tier','balanced').upper(), 'yellow')}")
            provider = agent.get("preferred_provider") or "Por defecto del sistema"
            model = agent.get("preferred_model") or "Por defecto del sistema"
            print(f"     Config IA:    {c(provider, 'purple')} / {c(model, 'gray')}")
            print()
    except Exception as e:
        print(c(f"  ✗ Error al obtener agentes: {e}", "red"))
        print()

def cmd_list_models(base_url: str):
    """Muestra los modelos disponibles en base a tus API keys activas."""
    header()
    if not TOKEN:
        print(c("  ✗ Error: ARZOR_TOKEN no configurado.", "red"))
        return
        
    print()
    try:
        with Spinner("Consultando modelos de tus proveedores (esto puede demorar unos segundos)"):
            models = api_get("/platform/keys/models/available", base_url)
        if not models:
            print(c("  No hay modelos disponibles configurados en tu cuenta.", "yellow"))
            print(c("  Configura tus API Keys en el Panel Web de Arzor.", "gray"))
            print()
            return
            
        # Filtrar modelos de codificación
        coding_models = [m for m in models if is_coding_model(m.get("id", ""), m.get("provider", ""))]
        if not coding_models:
            print(c("  No hay modelos de programación/desarrollo disponibles con tus API Keys configuradas.", "yellow"))
            print(c("  Configura claves para Google, Groq, DeepSeek, Anthropic o Mistral en el Panel Web.", "gray"))
            print()
            return
            
        # Agrupar por proveedor
        grouped = {}
        for m in coding_models:
            prov = m.get("provider", "Otros").upper()
            if prov not in grouped:
                grouped[prov] = []
            grouped[prov].append(m)
            
        print()
        for provider, items in sorted(grouped.items()):
            print(f"  🌐 Proveedor: {c(provider, 'bold')}")
            for item in items:
                free_badge = c("(Gratuito)", "green") if item.get("free") else c("(Pago)", "yellow")
                print(f"    • ID: {c(item['id'], 'cyan'):<45} {item['name']:<40} {free_badge}")
            print()
    except Exception as e:
        print(c(f"  ✗ Error al listar modelos: {e}", "red"))
        print()

def cmd_create_agent_interactive(base_url: str):
    """Guía interactiva paso a paso para crear un agente desde la consola."""
    header()
    if not TOKEN:
        print(c("  ✗ Error: ARZOR_TOKEN no configurado.", "red"))
        return
        
    print(c("  ✨ Creación interactiva de nuevo Agente Personalizado ✨", "cyan"))
    print(c("  Responde a los siguientes pasos (Presiona Ctrl+C para cancelar):\n", "gray"))
    
    try:
        # 1. Nombre
        name = ""
        while len(name.strip()) < 2:
            name = input(c("  [1/7] Nombre del Agente (mínimo 2 letras): ", "bold")).strip()
            
        # 2. Descripción
        description = input(c("  [2/7] Descripción / Rol del Agente: ", "bold")).strip()
        
        # 3. Categoría
        categories = ["dev", "ops", "data", "science", "creative", "custom"]
        print(c("\n  Categorías válidas:", "gray"))
        for i, cat in enumerate(categories, start=1):
            print(f"    {i}. {cat}")
        cat_idx = 0
        while cat_idx < 1 or cat_idx > len(categories):
            try:
                cat_input = input(c("  [3/7] Selecciona el número de la categoría [default: 1]: ", "bold")).strip()
                if not cat_input:
                    cat_idx = 1
                else:
                    cat_idx = int(cat_input)
            except ValueError:
                pass
        category = categories[cat_idx - 1]
        
        # 4. Tier
        tiers = ["balanced", "pro", "fast"]
        print(c("\n  Tiers de Calidad / Velocidad:", "gray"))
        for i, t in enumerate(tiers, start=1):
            print(f"    {i}. {t}")
        tier_idx = 0
        while tier_idx < 1 or tier_idx > len(tiers):
            try:
                tier_input = input(c("  [4/7] Selecciona el número de Tier [default: 1]: ", "bold")).strip()
                if not tier_input:
                    tier_idx = 1
                else:
                    tier_idx = int(tier_input)
            except ValueError:
                pass
        base_tier = tiers[tier_idx - 1]
        
        # 5. Proveedor
        print(c("\n  Proveedores soportados (google, groq, openrouter, deepseek, cohere, etc.):", "gray"))
        preferred_provider = input(c("  [5/7] Proveedor preferido (Opcional, Enter para omitir): ", "bold")).strip().lower()
        if not preferred_provider:
            preferred_provider = None
            
        # 6. Modelo
        preferred_model = input(c("  [6/7] Modelo preferido (Opcional, Enter para omitir): ", "bold")).strip()
        if not preferred_model:
            preferred_model = None
            
        # 7. Instrucciones
        print(c("\n  Escribe las instrucciones de comportamiento (personality/reglas) para el agente.", "gray"))
        print(c("  (Ingresa una sola línea o pulsa enter si es corta. Mínimo 20 caracteres)", "gray"))
        system_instructions = ""
        while len(system_instructions.strip()) < 20:
            system_instructions = input(c("  [7/7] Instrucciones del sistema: ", "bold")).strip()
            if len(system_instructions.strip()) < 20:
                print(c("  ✗ Las instrucciones deben tener al menos 20 caracteres.", "yellow"))
                
        # Crear payload
        payload = {
            "name": name,
            "description": description or None,
            "category": category,
            "base_tier": base_tier,
            "system_instructions": system_instructions,
            "is_public": False,
            "preferred_provider": preferred_provider,
            "preferred_model": preferred_model
        }
        
        print()
        with Spinner("Registrando nuevo agente en el servidor"):
            result = api_post("/platform/agents", payload, base_url)
        print(c(f"  ✅ ¡Agente creado con éxito!", "green"))
        print(f"     Nombre: {c(result['name'], 'bold')}")
        print(f"     ID:     {c(result['id'], 'cyan')}")
        print()
        
    except KeyboardInterrupt:
        print(c("\n\n  ✗ Creación cancelada por el usuario.", "red"))
        print()

# ─── ReAct Loop ───────────────────────────────────────────────────────────────

def call_agent_step(messages: List[Dict[str, str]], base_url: str, tier: str, agent_id: str = "") -> dict:
    """Llama al backend de Arzor para obtener el siguiente paso del agente ReAct."""
    payload = {
        "messages": messages,
        "tier": tier,
        "agent_id": agent_id or None
    }
    return api_post("/platform/crew/agent-step", payload, base_url)

def run_agent_loop(task: str, tier: str, auto_confirm: bool, agent_id: str, base_url: str):
    """Ejecuta el bucle ReAct del agente autónomo local."""
    header()
    
    if not TOKEN:
        print(c("  ✗ Error: La variable de entorno ARZOR_TOKEN está vacía.", "red"))
        print(c("    Regístrate o inicia sesión en la plataforma y configúrala en tu entorno o en el archivo .env", "gray"))
        sys.exit(1)

    # Resolver el agente por nombre si se proporcionó
    resolved_agent_id = ""
    if agent_id:
        with Spinner("Resolviendo agente"):
            resolved_agent_id = resolve_agent_id(agent_id, base_url)
        if resolved_agent_id != agent_id:
            print(c(f"  ✔ Agente resuelto: {c(agent_id, 'bold')} ➔ {c(resolved_agent_id, 'cyan')}", "gray"))
        else:
            print(c(f"  • Usando identificador/UUID directo: {c(agent_id, 'cyan')}", "gray"))
        print()

    print(c("  🚀 Iniciando agente autónomo local...", "cyan"))
    print(c(f"  Tarea: {task}", "white"))
    print(c(f"  Tier:  {tier}  |  Modo Auto-Confirmar: {'SÍ' if auto_confirm else 'NO'}", "gray"))
    print(c(f"  URL del Servidor: {base_url}", "gray"))
    print()

    messages = [
        {"role": "user", "content": task}
    ]
    
    step_count = 0
    max_steps = 25
    
    while step_count < max_steps:
        step_count += 1
        
        try:
            with Spinner(f"[Paso {step_count}/{max_steps}] Pensando y analizando"):
                step_result = call_agent_step(messages, base_url, tier, resolved_agent_id)
        except requests.exceptions.HTTPError as e:
            detail = "Error de conexión o validación."
            try:
                detail = e.response.json().get("detail", str(e))
            except Exception:
                pass
            print(c(f"\n  ✗ Error del Servidor ({e.response.status_code}): {detail}", "red"))
            sys.exit(1)
        except Exception as e:
            print(c(f"\n  ✗ Error de red al conectar al servidor de Arzor: {e}", "red"))
            sys.exit(1)
            
        thought = step_result.get("thought", "")
        action = step_result.get("action", "")
        args = step_result.get("args", {})
        
        assistant_msg = {
            "role": "assistant",
            "content": json.dumps({"thought": thought, "action": action, "args": args})
        }
        messages.append(assistant_msg)
        
        if thought:
            print(c("\n  🧠 Pensamiento:", "cyan"))
            print(textwrap.indent(thought, "     "))
            print()
            
        if not action or action == "finish":
            print(c("  ✅ Tarea completada con éxito.", "green"))
            if args.get("message"):
                print(c("\n  📝 Mensaje final de la IA:", "bold"))
                print(textwrap.indent(args["message"], "     "))
            print()
            break
            
        print(c("  🛠️  Acción solicitada:", "yellow"))
        print(f"     Herramienta: {c(action, 'bold')}")
        print(f"     Argumentos:  {json.dumps(args)}")
        print()
        
        if not auto_confirm:
            try:
                confirm = input(c("     ¿Deseas permitir esta acción? [Y/n]: ", "bold")).strip().lower()
                if confirm not in ("", "y", "yes", "s", "si"):
                    print(c("\n  ✗ Ejecución cancelada por el usuario.", "red"))
                    messages.append({
                        "role": "user",
                        "content": "Acción rechazada por el usuario. Corrige tu enfoque o finaliza la tarea."
                    })
                    continue
            except (KeyboardInterrupt, EOFError):
                print(c("\n  ✗ Interrumpido por el usuario.", "red"))
                sys.exit(0)
                
        observation = ""
        if action == "list_directory":
            observation = list_directory(args.get("path", "."))
        elif action == "read_file_content":
            observation = read_file_content(args.get("path", ""))
        elif action == "write_file_content":
            observation = write_file_content(args.get("path", ""), args.get("content", ""))
        elif action == "edit_file_content":
            observation = edit_file_content(args.get("path", ""), args.get("target_text", ""), args.get("replacement_text", ""))
        elif action == "execute_system_command":
            observation = execute_system_command(args.get("command", ""))
        else:
            observation = f"Error: La herramienta '{action}' no está soportada."
            
        print(c("  👁️  Observación (Resultado):", "gray"))
        truncated_obs = observation[:500] + "..." if len(observation) > 500 else observation
        print(textwrap.indent(truncated_obs, "     "))
        print()
        
        messages.append({
            "role": "user",
            "content": f"Resultado de la herramienta:\n{observation}"
        })
        
    else:
        print(c("  ✗ Límite de pasos alcanzado sin completar la tarea.", "red"))
        print()

# ─── CLI Entry Point ──────────────────────────────────────────────────────────

def main():
    # Comprobar si se llama a un comando especial o a una tarea directa
    special_commands = {"list-agents", "create-agent", "list-models", "login"}
    
    # Manejar compatibilidad ergonómica directa
    is_special = len(sys.argv) > 1 and sys.argv[1] in special_commands
    
    parser = argparse.ArgumentParser(
        prog="arzor",
        description="Agente CLI de Desarrollo Autónomo de Arzor AIs (el 'antigravity/codex' local)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        Comandos de Administración:
          python cli/arzor.py login          → Inicia sesión y guarda tu token automáticamente
          python cli/arzor.py list-agents    → Lista todos tus agentes personalizados
          python cli/arzor.py create-agent   → Asistente por pasos para crear un agente
          python cli/arzor.py list-models    → Muestra todos tus modelos de IA activos
          
        Ejemplos de ejecución de tareas:
          python cli/arzor.py "Crea un servidor Flask en app.py"
          python cli/arzor.py "Ejecuta los tests unitarios" -y --agent "Dev Python"
        """)
    )

    
    if is_special:
        # Definir subparsers para comandos especiales si se invoca uno
        subparsers = parser.add_subparsers(dest="command", required=True)
        subparsers.add_parser("list-agents", help="Listar tus agentes personalizados en la plataforma")
        subparsers.add_parser("create-agent", help="Iniciar asistente interactivo de creación de agentes")
        subparsers.add_parser("list-models", help="Listar todos los modelos de IA activos en tu cuenta")
        subparsers.add_parser("login", help="Iniciar sesión en la plataforma y configurar credenciales locales")
        
        # Argumentos compartidos globales de conexión
        parser.add_argument("--url", default=DEFAULT_URL, help="URL base del servidor de Arzor")
        args = parser.parse_args()
        
        if args.command == "list-agents":
            cmd_list_agents(args.url)
        elif args.command == "list-models":
            cmd_list_models(args.url)
        elif args.command == "create-agent":
            cmd_create_agent_interactive(args.url)
        elif args.command == "login":
            cmd_login(args.url)

            
    else:
        # Comportamiento por defecto: Ejecutar una tarea autónoma ReAct
        parser.add_argument("task", nargs="*", help="Descripción de la tarea de desarrollo a realizar")
        parser.add_argument("--url", default=DEFAULT_URL, help="URL base del servidor de Arzor")
        parser.add_argument("--tier", default="balanced", choices=["fast", "balanced", "pro"],
                            help="Tier de calidad del modelo a utilizar (default: balanced)")
        parser.add_argument("-y", "--yes", action="store_true", dest="auto_confirm",
                            help="Modo automático: ejecuta acciones de herramientas sin pedir confirmación")
        parser.add_argument("--agent", default="", help="Nombre o UUID del agente personalizado a usar")

        args = parser.parse_args()

        if not args.task:
            parser.print_help()
            sys.exit(0)

        task_str = " ".join(args.task)
        run_agent_loop(
            task=task_str,
            tier=args.tier,
            auto_confirm=args.auto_confirm,
            agent_id=args.agent,
            base_url=args.url
        )

if __name__ == "__main__":
    main()
