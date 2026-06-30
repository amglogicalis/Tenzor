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
import random


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

# Cargar variables de entorno del archivo .env del repositorio base de Arzor
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(SCRIPT_DIR)
load_dotenv(os.path.join(REPO_DIR, ".env"), override=True)

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
    """Guarda o actualiza la variable ARZOR_TOKEN en el archivo .env del repositorio base."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_dir = os.path.dirname(script_dir)
    env_path = os.path.join(repo_dir, ".env")
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

def cmd_whoami(base_url: str):
    """Muestra información sobre la sesión de usuario activa en el CLI."""
    header()
    if not TOKEN:
        print(c("  ✗ No has iniciado sesión.", "red"))
        print(c("    Usa 'arzor login' para autenticarte con tus credenciales.", "gray"))
        print()
        return
        
    try:
        with Spinner("Obteniendo perfil del usuario"):
            result = api_get("/platform/auth/me", base_url)
            
        print(c("  🔮 Sesión de usuario activa en Arzor AIs 🔮", "cyan"))
        print(c("  ════════════════════════════════════════════", "gray"))
        print(f"  • Nombre público:  {c(result.get('display_name') or 'N/A', 'bold')}")
        print(f"  • Email:           {c(result.get('email') or 'N/A', 'white')}")
        print(f"  • Nombre de usuario:{c(result.get('username') or 'N/A', 'green')}")
        print(f"  • ID de usuario:   {c(result.get('user_id') or 'N/A', 'cyan')}")
        print(c("  ════════════════════════════════════════════", "gray"))
        print()
    except Exception as e:
        print(c(f"  ✗ Error al obtener información de la sesión: {e}", "red"))
        print(c("    Es posible que tu token de sesión haya caducado. Prueba a hacer 'arzor login' de nuevo.", "gray"))
        print()

def cmd_register(base_url: str):
    """Inicia asistente de registro interactivo para crear una nueva cuenta."""
    header()
    print(c("  ✨ Registrar Cuenta en la Plataforma Arzor AIs ✨", "cyan"))
    print(c("  Completa los siguientes datos de registro (Ctrl+C para cancelar):\n", "gray"))
    
    try:
        email = input(c("  [1/4] Email:                ", "bold")).strip()
        if not email:
            print(c("  ✗ El email es obligatorio.", "red"))
            return
            
        username = input(c("  [2/4] Nombre de usuario:    ", "bold")).strip()
        if not username:
            print(c("  ✗ El nombre de usuario es obligatorio.", "red"))
            return
            
        display_name = input(c("  [3/4] Nombre público/apodo: ", "bold")).strip()
        if not display_name:
            print(c("  ✗ El nombre público es obligatorio.", "red"))
            return
            
        password = getpass.getpass(c("  [4/4] Contraseña (mín 6):   ", "bold")).strip()
        if len(password) < 6:
            print(c("  ✗ La contraseña debe tener al menos 6 caracteres.", "red"))
            return
            
        print()
        payload = {
            "email": email,
            "password": password,
            "username": username,
            "display_name": display_name
        }
        
        with Spinner("Enviando registro de cuenta al servidor"):
            api_post("/platform/auth/register", payload, base_url)
            
        print(c("  ✅ ¡Registro de cuenta completado con éxito! ✅", "green"))
        print()
        print(c("  🔔 IMPORTANTE: Confirmación de correo requerida", "yellow"))
        print(c("  ===============================================", "gray"))
        print(c("  Hemos enviado un enlace de confirmación al correo especificado.", "white"))
        print(c("  Por favor, abre tu buzón y verifica tu dirección de email", "white"))
        print(c("  antes de intentar iniciar sesión en tu consola con 'arzor login'.", "white"))
        print()
    except KeyboardInterrupt:
        print(c("\n\n  ✗ Registro cancelado por el usuario.", "red"))
        print()
    except Exception as e:
        print(c(f"  ✗ Error al registrar la cuenta: {e}", "red"))
        print()

def cmd_logout():
    """Cierra la sesión del usuario eliminando el token JWT del archivo .env global."""
    header()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_dir = os.path.dirname(script_dir)
    env_path = os.path.join(repo_dir, ".env")
    
    if not os.path.exists(env_path):
        print(c("  ✗ No hay ningún archivo .env configurado.", "red"))
        print()
        return
        
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        new_lines = []
        token_found = False
        for line in lines:
            if line.strip().startswith("ARZOR_TOKEN="):
                token_found = True
                continue  # Eliminar esta línea
            new_lines.append(line)
            
        if token_found:
            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            global TOKEN
            TOKEN = ""
            print(c("  ✅ Sesión cerrada con éxito.", "green"))
            print(c("     El token JWT ha sido eliminado de tu archivo de configuración.", "gray"))
        else:
            print(c("  ℹ️ No se ha detectado ninguna sesión activa en el archivo .env.", "yellow"))
        print()
    except Exception as e:
        print(c(f"  ✗ Error al cerrar sesión: {e}", "red"))
        print()

def cmd_status(base_url: str):
    """Realiza un diagnóstico de la conexión y configuración de Arzor CLI."""
    header()
    print(c("  🔮 Diagnóstico de Arzor AIs CLI 🔮", "cyan"))
    print(c("  ══════════════════════════════════", "gray"))
    
    # 1. Dirección del Servidor
    print(f"  • Servidor API:     {c(base_url, 'white')}")
    
    # 2. Verificar Conexión
    try:
        start_time = time.time()
        # Endpoint ligero para ping rápido
        response = requests.get(f"{base_url}/platform/keys/models/available", headers={"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}, timeout=5)
        latency = int((time.time() - start_time) * 1000)
        print(f"  • Conexión:         {c('ONLINE', 'green')} ({latency}ms)")
    except Exception:
        print(f"  • Conexión:         {c('OFFLINE', 'red')}")
        
    # 3. Estado de la Sesión
    if TOKEN:
        print(f"  • Sesión:           {c('AUTENTICADO', 'green')}")
        # Intentar ver el perfil para confirmar validez
        try:
            profile = api_get("/platform/auth/me", base_url)
            print(f"  • Cuenta:           {c(profile.get('email'), 'bold')} ({profile.get('display_name')})")
        except Exception:
            print(f"  • Cuenta:           {c('TOKEN INVÁLIDO O EXPIRADO', 'red')}")
    else:
        print(f"  • Sesión:           {c('SIN AUTENTICAR', 'yellow')}")
        
    # 4. Entorno de Instalación
    script_dir = os.path.dirname(os.path.abspath(__file__))
    print(f"  • Ruta del CLI:     {c(script_dir, 'gray')}")
    print(c("  ══════════════════════════════════", "gray"))
    print()

def cmd_update():
    """Actualiza el CLI automáticamente jalando cambios de git y reinstalando."""
    header()
    print(c("  🔄 Actualizando Arzor AIs CLI 🔄", "cyan"))
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_dir = os.path.dirname(script_dir)
    
    try:
        # 1. Ejecutar git pull
        print(c("  • Descargando últimos cambios desde GitHub...", "white"))
        pull_res = subprocess.run(["git", "pull", "origin", "main"], cwd=repo_dir, capture_output=True, text=True, check=True)
        print(c(pull_res.stdout.strip(), "gray"))
        
        # 2. Reinstalar en modo editable
        print(c("\n  • Reinstalando el paquete en modo editable...", "white"))
        pip_cmd = "pip"
        venv_pip = os.path.join(repo_dir, "venv", "Scripts", "pip.exe")
        if os.path.exists(venv_pip):
            pip_cmd = venv_pip
        elif sys.platform != "win32":
            venv_pip_unix = os.path.join(repo_dir, "venv", "bin", "pip")
            if os.path.exists(venv_pip_unix):
                pip_cmd = venv_pip_unix
                
        install_res = subprocess.run([pip_cmd, "install", "-e", "."], cwd=repo_dir, capture_output=True, text=True, check=True)
        print(c("  ✅ Reinstalación completada con éxito.", "green"))
        print()
    except subprocess.CalledProcessError as e:
        print(c(f"\n  ✗ Error durante la actualización: {e}", "red"))
        if e.stderr:
            print(c(e.stderr, "gray"))
        print()
    except Exception as e:
        print(c(f"\n  ✗ Error inesperado al actualizar: {e}", "red"))
        print()

def cmd_test_agent(agent_name_or_id: str, base_url: str):
    """Envía un ping de prueba al agente para validar que sus API Keys y modelo responden."""
    header()
    if not TOKEN:
        print(c("  ✗ Error: Debes iniciar sesión con 'arzor login' primero.", "red"))
        print()
        return
        
    try:
        resolved_id = resolve_agent_id(agent_name_or_id, base_url)
        print(c(f"  🧪 Testeando Agente: {agent_name_or_id} ➔ {resolved_id}", "cyan"))
        
        payload = {
            "messages": [{"role": "user", "content": "test_ping"}],
            "tier": "fast",
            "agent_id": resolved_id
        }
        
        with Spinner("Enviando ping de inferencia al agente"):
            result = api_post("/platform/crew/agent-step", payload, base_url)
            
        print(c("  ✅ Inferencia exitosa. El agente responde correctamente.", "green"))
        print(f"     Respuesta de prueba: {c(result.get('thought') or 'Ping exitoso', 'gray')}")
        print()
    except Exception as e:
        print(c(f"  ✗ Test fallido: El agente no pudo completar la inferencia.", "red"))
        print(c(f"    Detalle del error: {e}", "gray"))
        print()

def cmd_clean():
    """Revierte los cambios creados o modificados en la última ejecución."""
    header()
    print(c("  🧹 Deshaciendo Cambios de la Última Tarea (Rollback) 🧹", "yellow"))
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_dir = os.path.dirname(script_dir)
    history_path = os.path.join(repo_dir, ".arzor_history.json")
    
    if not os.path.exists(history_path):
        print(c("  ✗ No se ha encontrado ningún historial de la última tarea para revertir.", "red"))
        print()
        return
        
    try:
        with open(history_path, "r", encoding="utf-8") as f:
            history = json.load(f)
            
        created_files = history.get("created_files", [])
        modified_files = history.get("modified_files", {})
        
        # 1. Eliminar archivos creados
        deleted_count = 0
        for path in created_files:
            if os.path.exists(path):
                os.remove(path)
                print(c(f"     • Eliminado: {path}", "red"))
                deleted_count += 1
                
        # 2. Restaurar archivos modificados
        restored_count = 0
        for path, old_content in modified_files.items():
            with open(path, "w", encoding="utf-8") as f:
                f.write(old_content)
            print(c(f"     • Restaurado: {path}", "green"))
            restored_count += 1
            
        os.remove(history_path)
        print()
        print(c(f"  ✅ Reversión exitosa: {deleted_count} creados borrados, {restored_count} modificados restaurados.", "green"))
        print()
    except Exception as e:
        print(c(f"  ✗ Error al ejecutar el rollback: {e}", "red"))
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
            print()
    except Exception as e:
        print(c(f"  ✗ Error al listar modelos: {e}", "red"))
        print()

def cmd_round_table(base_url: str):
    """Permite administrar e iniciar debates multi-agente en una mesa redonda."""
    header()
    if not TOKEN:
        print(c("  ✗ Error: ARZOR_TOKEN no configurado.", "red"))
        return
        
    print(c("  💬 Arzor Round Table - Debates Multi-Agente 💬", "cyan"))
    
    # 1. Recuperar agentes y mesas
    try:
        with Spinner("Obteniendo agentes y mesas redondas"):
            agents_data = api_get("/platform/agents", base_url)
            tables_data = api_get("/platform/round-table", base_url)
            
        agents = agents_data.get("agents", [])
        tables = tables_data.get("tables", [])
    except Exception as e:
        print(c(f"  ✗ Error al conectar con el servidor: {e}", "red"))
        return
        
    if not agents:
        print(c("  ✗ No tienes agentes configurados en tu cuenta.", "red"))
        print(c("    Crea al menos 2 agentes para poder iniciar un debate.", "gray"))
        print()
        return

    table_id = ""
    # 2. Elegir mesa existente o crear una nueva
    if tables:
        print(c("\n  Tus Mesas Redondas de Debate:", "bold"))
        for idx, t in enumerate(tables, start=1):
            print(f"    {idx}. {c(t['name'], 'bold')} | Tema: {c(t['topic'][:60] + '...', 'gray')} | Estado: {t['status'].upper()}")
        print(f"    N. {c('[Crear Nueva Mesa Redonda]', 'green')}")
        
        selection = input(c("\n  Selecciona una mesa o escribe 'N' para crear una: ", "bold")).strip().lower()
        if selection == 'n' or not selection:
            table_id = ""
        else:
            try:
                table_idx = int(selection)
                if 1 <= table_idx <= len(tables):
                    table_id = tables[table_idx - 1]["id"]
                else:
                    print(c("  ✗ Selección no válida.", "red"))
                    return
            except ValueError:
                table_id = ""
    
    # 3. Crear mesa redonda si no se seleccionó una existente
    if not table_id:
        print(c("\n  ✨ Crear Nueva Mesa de Debate ✨", "cyan"))
        name = input(c("  Nombre de la mesa: ", "bold")).strip()
        if not name:
            print(c("  ✗ El nombre es obligatorio.", "red"))
            return
            
        topic = input(c("  Tema de debate / pregunta a discutir: ", "bold")).strip()
        if len(topic) < 10:
            print(c("  ✗ El tema debe tener al menos 10 caracteres.", "red"))
            return
            
        description = input(c("  Descripción (Opcional): ", "bold")).strip()
        
        # Crear la mesa en el servidor
        try:
            with Spinner("Creando mesa de debate en el servidor"):
                table = api_post("/platform/round-table", {"name": name, "topic": topic, "description": description or None}, base_url)
            table_id = table["id"]
            print(c("  ✔ Mesa creada con éxito.", "green"))
        except Exception as e:
            print(c(f"  ✗ Error al crear la mesa: {e}", "red"))
            return
            
        # Añadir agentes miembros
        print(c("\n  Tus Agentes Disponibles:", "bold"))
        for idx, a in enumerate(agents, start=1):
            print(f"    {idx}. {c(a['name'], 'bold')} [{a.get('category','custom').upper()}]")
            
        member_input = input(c("\n  Selecciona los agentes que debatirán (mínimo 2, separados por comas): ", "bold")).strip()
        member_indices = [int(i.strip()) for i in member_input.split(",") if i.strip().isdigit()]
        
        if len(member_indices) < 2:
            print(c("  ✗ Debes seleccionar al menos 2 agentes para el debate.", "red"))
            return
            
        # Añadir miembros en orden de turno
        try:
            for idx, a_idx in enumerate(member_indices, start=1):
                if 1 <= a_idx <= len(agents):
                    agent_to_add = agents[a_idx - 1]
                    with Spinner(f"Añadiendo a {agent_to_add['name']} a la mesa"):
                        api_post(f"/platform/round-table/{table_id}/members", {"agent_id": agent_to_add["id"], "turn_order": idx}, base_url)
                else:
                    print(c(f"  ✗ Índice de agente {a_idx} no válido. Omitiendo.", "yellow"))
        except Exception as e:
            print(c(f"  ✗ Error al añadir agentes a la mesa: {e}", "red"))
            return
            
    # 4. Iniciar el debate
    rounds_input = input(c("\n  Número de rondas de debate (1-3) [default: 2]: ", "bold")).strip()
    rounds = 2
    if rounds_input.isdigit() and 1 <= int(rounds_input) <= 3:
        rounds = int(rounds_input)
        
    print()
    try:
        with Spinner("Los agentes están debatiendo en la mesa redonda (esto puede demorar unos segundos)"):
            result = api_post(f"/platform/round-table/{table_id}/start", {"rounds": rounds}, base_url)
    except Exception as e:
        print(c(f"  ✗ Error en el debate: {e}", "red"))
        return
        
    # 5. Imprimir los resultados
    print(c("  ════════════════════════════════════════════════════════════", "gray"))
    print(c(f"  📢 DEBATE: {result.get('topic')}", "bold"))
    print(c("  ════════════════════════════════════════════════════════════", "gray"))
    print()
    
    turns = result.get("turns", [])
    agent_colors = {}
    available_colors = ["cyan", "green", "yellow", "purple", "white"]
    
    for turn in turns:
        agent_name = turn.get("agent_name", "Agente")
        if agent_name not in agent_colors:
            # Asignar un color único a cada agente
            agent_colors[agent_name] = available_colors[len(agent_colors) % len(available_colors)]
            
        color = agent_colors[agent_name]
        print(c(f"  [💬 {agent_name} ({turn.get('provider')}/{turn.get('model')}) - Ronda {turn.get('round')}]", color))
        print(textwrap.indent(turn.get("content", ""), "     "))
        print()
        
    synthesis = result.get("synthesis", "")
    if synthesis:
        print(c("  ════════════════════════════════════════════════════════════", "gray"))
        print(c("  ⚖️ SÍNTESIS Y CONCLUSIÓN FINAL (Moderador)", "bold"))
        print(c("  ════════════════════════════════════════════════════════════", "gray"))
        print()
        print(textwrap.indent(synthesis, "     "))
        print()

def cmd_team_collaboration(task_str: str, agent_names_or_ids: str, base_url: str, auto_confirm: bool):
    """Coordina un equipo de agentes locales para resolver una tarea secuencial en cascada."""
    header()
    if not TOKEN:
        print(c("  ✗ Error: ARZOR_TOKEN no configurado.", "red"))
        return
        
    print(c("  👥 Arzor Teams - Colaboración de Agentes locales 👥", "cyan"))
    
    # 1. Recuperar agentes disponibles
    try:
        with Spinner("Obteniendo agentes del servidor"):
            data = api_get("/platform/agents", base_url)
        agents = data.get("agents", [])
    except Exception as e:
        print(c(f"  ✗ Error al obtener agentes: {e}", "red"))
        return
        
    if not agents:
        print(c("  ✗ No tienes agentes configurados en tu cuenta.", "red"))
        print(c("    Crea agentes especializados antes de lanzar un equipo.", "gray"))
        print()
        return

    selected_agents = []
    # 2. Si no se pasaron agentes, pedirlos de forma interactiva
    if not agent_names_or_ids:
        print(c("\n  Agentes Disponibles para tu Equipo:", "bold"))
        for idx, a in enumerate(agents, start=1):
            print(f"    {idx}. {c(a['name'], 'bold')} | Categoría: {a.get('category','custom').upper()} | Descripción: {a.get('description','')[:50]}")
            
        selection = input(c("\n  Selecciona los miembros de tu equipo (números separados por comas): ", "bold")).strip()
        indices = [int(i.strip()) for i in selection.split(",") if i.strip().isdigit()]
        for idx in indices:
            if 1 <= idx <= len(agents):
                selected_agents.append(agents[idx - 1])
    else:
        # Resolver los agentes pasados por comas
        names_list = [n.strip() for n in agent_names_or_ids.split(",") if n.strip()]
        for name in names_list:
            resolved_id = resolve_agent_id(name, base_url)
            # Buscar el objeto agente completo
            found = False
            for a in agents:
                if a["id"] == resolved_id:
                    selected_agents.append(a)
                    found = True
                    break
            if not found:
                print(c(f"  ✗ No se pudo encontrar al agente: '{name}'. Omitiendo.", "yellow"))

    if len(selected_agents) < 2:
        print(c("  ✗ Se requieren al menos 2 agentes válidos en el equipo para colaborar.", "red"))
        return

    print(c("\n  Miembros del equipo local configurados:", "bold"))
    for idx, a in enumerate(selected_agents, start=1):
        print(f"    • {c(a['name'], 'green')} ({a['id']})")

    # 3. Generar el Plan con el Coordinador del Equipo
    print(c("\n  🚀 Diseñando el plan de trabajo con el Coordinador de Equipo...", "cyan"))
    
    # Componer una descripción detallada de las habilidades de cada agente
    skills_context = ""
    for a in selected_agents:
        skills_context += f"- Agente: '{a['name']}' (UUID: {a['id']})\n  Instrucciones/Habilidades: {a['system_instructions'][:200]}\n"
        
    coordinator_prompt = f"""
Actúa como un Director de Proyecto / Coordinador técnico de desarrollo de software.
Tu objetivo es recibir una tarea general y la lista de agentes especializados disponibles, y diseñar un plan secuencial paso a paso (desglose de subtareas) para resolver la tarea trabajando colaborativamente sobre los archivos de la máquina local.

Lista de agentes especializados disponibles:
{skills_context}

Tarea general a resolver en la máquina local:
"{task_str}"

Diseña un plan secuencial ordenado. Cada paso del plan debe ser ejecutado por uno de los agentes disponibles en base a su especialización. El resultado de un paso servirá de base para el siguiente agente.
Devuelve tu respuesta únicamente en formato JSON válido con la siguiente estructura, sin textos explicativos ni antes ni después del bloque de código.

Estructura requerida:
{{
  "plan": [
    {{
      "step": 1,
      "agent_id": "UUID_DE_UN_AGENTE_DISPONIBLE",
      "agent_name": "Nombre exacto del agente",
      "subtask": "Prompt/Instrucciones específicas, detalladas e individuales para que este agente ejecute su paso autónomo ReAct en local."
    }}
  ]
}}
"""
    try:
        # Llamar al endpoint del backend como un paso único ReAct de razonamiento
        with Spinner("Analizando tarea y estructurando plan de pasos"):
            result = call_agent_step(
                messages=[{"role": "user", "content": coordinator_prompt}],
                base_url=base_url,
                tier="balanced"
            )
            
        content = result.get("content", "")
        # Extraer el bloque JSON de la respuesta
        import re
        json_match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            # Intentar parsear el contenido crudo
            json_str = content.strip()
            
        plan_data = json.loads(json_str)
        plan = plan_data.get("plan", [])
    except Exception as e:
        print(c(f"  ✗ Error al diseñar el plan con el Coordinador: {e}", "red"))
        print(c(f"    Respuesta cruda del servidor: {content[:400]}...", "gray"))
        return

    if not plan:
        print(c("  ✗ El Coordinador no pudo generar un plan de subtareas válido.", "red"))
        return

    print(c("\n  📋 Plan de Trabajo Diseñado por el Coordinador:", "bold"))
    for p in plan:
        print(f"    Paso {p['step']}. {c('[' + p['agent_name'] + ']', 'cyan')} -> {p['subtask']}")

    # 4. Confirmar ejecución
    print()
    confirm = "y"
    if not auto_confirm:
        confirm = input(c("  ¿Deseas iniciar la ejecución en cascada de este plan? [Y/n]: ", "bold")).strip().lower()
        if not confirm:
            confirm = "y"
            
    if confirm != "y":
        print(c("  ✗ Plan cancelado por el usuario.", "red"))
        return

    # 5. Ejecutar pasos en cascada
    print(c("\n  🚀 Iniciando ejecución de tareas colaborativas en cascada...\n", "cyan"))
    
    for p in plan:
        print(c(f"  [Paso {p['step']}/{len(plan)}] Activando a {p['agent_name']}...", "bold"))
        print(c(f"  Instrucción: {p['subtask']}", "gray"))
        print()
        
        # Ejecutar el bucle local de ReAct para este agente con su subtarea
        try:
            run_agent_loop(
                task=p['subtask'],
                tier="balanced",
                auto_confirm=auto_confirm,
                agent_id=p['agent_id'],
                base_url=base_url
            )
            print(c(f"  ✔ Paso {p['step']} completado por {p['agent_name']}.\n", "green"))
        except Exception as e:
            print(c(f"  ✗ Error en la ejecución del Paso {p['step']} por {p['agent_name']}: {e}", "red"))
            cont = input(c("  ¿Deseas continuar con el siguiente paso del plan de todas formas? [y/N]: ", "bold")).strip().lower()
            if cont != "y":
                print(c("  ✗ Ejecución del equipo abortada por el usuario.", "red"))
                return
                
    print(c("  ✅ ¡El equipo de desarrollo ha completado satisfactoriamente el plan de trabajo! ✅", "green"))
    print()


def cmd_create_agent_interactive(base_url: str):
    """Guía interactiva paso a paso para crear un agente desde la consola."""
    header()
    if not TOKEN:
        print(c("  ✗ Error: ARZOR_TOKEN no configurado.", "red"))
        return
        
    print(c("  ✨ Creación interactiva de nuevo Agente Personalizado ✨", "cyan"))
    print(c("  Responde a los siguientes pasos (Presiona Ctrl+C para cancelar):\n", "gray"))
    
    # Modelos de fallback estáticos por si falla la API
    fallback_models = [
        {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash", "provider": "google"},
        {"id": "gemini-1.5-pro", "name": "Gemini 1.5 Pro", "provider": "google"},
        {"id": "claude-3-5-sonnet-latest", "name": "Claude 3.5 Sonnet", "provider": "anthropic"},
        {"id": "claude-3-5-haiku-latest", "name": "Claude 3.5 Haiku", "provider": "anthropic"},
        {"id": "deepseek-coder", "name": "DeepSeek Coder", "provider": "deepseek"},
        {"id": "deepseek-reasoner", "name": "DeepSeek R1 / Reasoner", "provider": "deepseek"},
        {"id": "llama-3.3-70b-versatile", "name": "Llama 3.3 70B", "provider": "groq"},
        {"id": "mixtral-8x7b-32768", "name": "Mixtral 8x7B", "provider": "groq"},
        {"id": "codestral-latest", "name": "Codestral", "provider": "mistral"},
        {"id": "mistral-large-latest", "name": "Mistral Large", "provider": "mistral"},
        {"id": "meta-llama/llama-3.3-70b-instruct", "name": "Llama 3.3 70B (OpenRouter)", "provider": "openrouter"},
        {"id": "deepseek/deepseek-r1", "name": "DeepSeek R1 (OpenRouter)", "provider": "openrouter"}
    ]
    
    try:
        # Obtener modelos disponibles del servidor
        try:
            with Spinner("Obteniendo catálogo de modelos disponibles"):
                models = api_get("/platform/keys/models/available", base_url)
            if not models:
                models = fallback_models
        except Exception:
            models = fallback_models
            
        # 1. Nombre
        name = ""
        while len(name.strip()) < 2:
            name = input(c("  [1/6] Nombre del Agente (mínimo 2 letras): ", "bold")).strip()
            
        # 2. Descripción
        description = input(c("  [2/6] Descripción / Rol del Agente: ", "bold")).strip()
        
        # 3. Categoría
        categories = ["dev", "ops", "data", "science", "creative", "custom"]
        print(c("\n  Categorías válidas:", "gray"))
        for i, cat in enumerate(categories, start=1):
            print(f"    {i}. {cat}")
        cat_idx = 0
        while cat_idx < 1 or cat_idx > len(categories):
            try:
                cat_input = input(c("  [3/6] Selecciona el número de la categoría [default: 1]: ", "bold")).strip()
                if not cat_input:
                    cat_idx = 1
                else:
                    cat_idx = int(cat_input)
            except ValueError:
                pass
        category = categories[cat_idx - 1]
        
        # 4. Proveedor
        # Extraer proveedores únicos de la lista de modelos
        providers = sorted(list(set(m.get("provider", "other") for m in models)))
        print(c("\n  Proveedores disponibles en tu cuenta:", "gray"))
        for i, prov in enumerate(providers, start=1):
            print(f"    {i}. {prov.upper()}")
        prov_idx = 0
        while prov_idx < 1 or prov_idx > len(providers):
            try:
                prov_input = input(c("  [4/6] Selecciona el número de proveedor [default: 1]: ", "bold")).strip()
                if not prov_input:
                    prov_idx = 1
                else:
                    prov_idx = int(prov_input)
            except ValueError:
                pass
        preferred_provider = providers[prov_idx - 1]
        
        # 5. Modelo
        # Filtrar modelos por el proveedor elegido
        filtered_models = [m for m in models if m.get("provider") == preferred_provider]
        print(c(f"\n  Modelos de {preferred_provider.upper()} disponibles:", "gray"))
        for i, m in enumerate(filtered_models, start=1):
            print(f"    {i}. {m.get('name') or m.get('id')}")
        model_idx = 0
        while model_idx < 1 or model_idx > len(filtered_models):
            try:
                model_input = input(c("  [5/6] Selecciona el número del modelo [default: 1]: ", "bold")).strip()
                if not model_input:
                    model_idx = 1
                else:
                    model_idx = int(model_input)
            except ValueError:
                pass
        chosen_model = filtered_models[model_idx - 1]
        preferred_model = chosen_model["id"]
        
        # Calcular el base_tier de forma automática a partir del ID del modelo
        model_lower = preferred_model.lower()
        if any(w in model_lower for w in ["flash", "instant", "haiku", "speed", "fast"]):
            base_tier = "fast"
        elif any(w in model_lower for w in ["pro", "large", "reasoner", "ultra", "opus", "r1", "o1", "o3"]):
            base_tier = "pro"
        else:
            base_tier = "balanced"
            
        # 6. Instrucciones
        print(c("\n  Escribe las instrucciones de comportamiento (personality/reglas) para el agente.", "gray"))
        print(c("  (Mínimo 20 caracteres)", "gray"))
        system_instructions = ""
        while len(system_instructions.strip()) < 20:
            system_instructions = input(c("  [6/6] Instrucciones del sistema: ", "bold")).strip()
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

def run_agent_loop(task: str, tier: str, auto_confirm: bool, agent_id: str, base_url: str, dry_run: bool = False):
    """Ejecuta el bucle ReAct del agente autónomo local (o plan de simulación)."""
    header()
    
    # Historial de cambios locales para el comando clean
    created_files = []
    modified_files = {}
    
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

    if dry_run:
        print(c("  ✨ Iniciando PLAN DE SIMULACIÓN del agente autónomo... (Dry-Run)", "yellow"))
    else:
        print(c("  🚀 Iniciando agente autónomo local...", "cyan"))
    print(c(f"  Tarea: {task}", "white"))
    print(c(f"  Tier:  {tier}  |  Modo Auto-Confirmar: {'SÍ' if auto_confirm or dry_run else 'NO'}", "gray"))
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
        
        # Fallback de seguridad en el cliente: si el backend falló al parsear y devolvió el JSON crudo en el mensaje
        if (not action or action == "finish") and args.get("message"):
            raw_msg = args["message"].strip()
            try:
                import re
                cleaned = raw_msg
                cleaned = re.sub(r'^```(?:json)?', '', cleaned)
                cleaned = re.sub(r'```$', '', cleaned).strip()
                
                start_idx = cleaned.find('{')
                end_idx = cleaned.rfind('}')
                if start_idx != -1 and end_idx != -1:
                    cleaned = cleaned[start_idx:end_idx+1]
                    
                # Si el modelo duplicó las llaves ({{ ... }}), limpiar las externas sobrantes
                if cleaned.startswith("{{") and cleaned.endswith("}}"):
                    cleaned = cleaned[1:-1]
                    
                # Sanitizar saltos de línea crudos
                sanitized = []
                in_string = False
                escape = False
                for char in cleaned:
                    if char == '"' and not escape:
                        in_string = not in_string
                    if char == '\\' and in_string:
                        escape = not escape
                    else:
                        escape = False
                        
                    if in_string and char in ('\n', '\r'):
                        sanitized.append('\\n')
                    else:
                        sanitized.append(char)
                cleaned_json = "".join(sanitized)
                
                parsed_data = json.loads(cleaned_json)
                if "action" in parsed_data and parsed_data["action"] != "finish":
                    thought = parsed_data.get("thought", thought)
                    action = parsed_data["action"]
                    args = parsed_data.get("args", {})
            except Exception:
                pass
        
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
            
            # Guardar el historial de transacciones locales para el comando clean
            if not dry_run and (created_files or modified_files):
                try:
                    script_dir = os.path.dirname(os.path.abspath(__file__))
                    repo_dir = os.path.dirname(script_dir)
                    history_path = os.path.join(repo_dir, ".arzor_history.json")
                    with open(history_path, "w", encoding="utf-8") as f:
                        json.dump({
                            "task": task,
                            "created_files": created_files,
                            "modified_files": modified_files
                        }, f, indent=2)
                except Exception:
                    pass
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
        if dry_run:
            # Modo Simulación (Plan)
            if action == "list_directory":
                observation = list_directory(args.get("path", "."))
            elif action == "read_file_content":
                observation = read_file_content(args.get("path", ""))
            elif action == "write_file_content":
                path = args.get("path", "")
                content = args.get("content", "")
                print(c(f"     [PLAN] Se crearía el archivo '{path}' con contenido:", "yellow"))
                print(textwrap.indent(content, "       "))
                print()
                observation = f"Éxito: [DRY-RUN] Archivo '{path}' simulado correctamente en memoria."
            elif action == "edit_file_content":
                path = args.get("path", "")
                target = args.get("target_text", "")
                replacement = args.get("replacement_text", "")
                print(c(f"     [PLAN] En el archivo '{path}', se reemplazaría:", "yellow"))
                print(c("       <<< ELIMINAR:", "red"))
                print(textwrap.indent(target, "         "))
                print(c("       >>> INSERTA:", "green"))
                print(textwrap.indent(replacement, "         "))
                print()
                observation = f"Éxito: [DRY-RUN] Modificación en '{path}' simulada correctamente en memoria."
            elif action == "execute_system_command":
                cmd = args.get("command", "")
                print(c(f"     [PLAN] Se ejecutaría el comando: {cmd}", "yellow"))
                observation = f"Éxito: [DRY-RUN] Comando '{cmd}' simulado con éxito (Salida simulada por entorno de pruebas)."
            else:
                observation = f"Error: La herramienta '{action}' no está soportada."
        else:
            # Modo Ejecución Real
            if action == "list_directory":
                observation = list_directory(args.get("path", "."))
            elif action == "read_file_content":
                observation = read_file_content(args.get("path", ""))
            elif action == "write_file_content":
                path = args.get("path", "")
                # Guardar backup original si ya existe
                if os.path.exists(path):
                    if path not in modified_files:
                        try:
                            with open(path, "r", encoding="utf-8", errors="replace") as f:
                                modified_files[path] = f.read()
                        except Exception:
                            pass
                else:
                    if path not in created_files:
                        created_files.append(path)
                observation = write_file_content(path, args.get("content", ""))
            elif action == "edit_file_content":
                path = args.get("path", "")
                # Guardar backup original
                if os.path.exists(path) and path not in modified_files:
                    try:
                        with open(path, "r", encoding="utf-8", errors="replace") as f:
                            modified_files[path] = f.read()
                    except Exception:
                        pass
                observation = edit_file_content(path, args.get("target_text", ""), args.get("replacement_text", ""))
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
    special_commands = {
        "list-agents", "create-agent", "list-models", "login", 
        "round-table", "debate", "team", "whoami", "user", 
        "register", "signup", "logout", "status", "update", 
        "clean", "test-agent", "plan"
    }
    
    # Manejar compatibilidad ergonómica directa
    is_special = len(sys.argv) > 1 and sys.argv[1] in special_commands
    
    parser = argparse.ArgumentParser(
        prog="arzor",
        description="Agente CLI de Desarrollo Autónomo de Arzor AIs (el 'antigravity/codex' local)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        Comandos de Administración:
          python cli/arzor.py login          → Inicia sesión y guarda tu token automáticamente
          python cli/arzor.py register       → Crea una nueva cuenta interactiva en la plataforma
          python cli/arzor.py whoami         → Muestra los detalles de tu cuenta de usuario conectada
          python cli/arzor.py logout         → Cierra la sesión activa localmente
          python cli/arzor.py status         → Diagnóstico de la conexión y configuración
          python cli/arzor.py update         → Descarga e instala los últimos cambios automáticamente
          python cli/arzor.py clean          → Deshace los cambios locales de la última tarea
          python cli/arzor.py test-agent [A] → Verifica la salud e inferencia de un agente
          python cli/arzor.py plan [T]       → Muestra un dry-run simulado en memoria de una tarea
          python cli/arzor.py list-agents    → Lista todos tus agentes personalizados
          python cli/arzor.py create-agent   → Asistente por pasos para crear un agente
          python cli/arzor.py list-models    → Muestra todos tus modelos de IA activos
          python cli/arzor.py debate         → Inicia debates en mesa redonda entre tus agentes
          python cli/arzor.py team [tarea]   → Ejecuta tareas complejas con un equipo de agentes locales
          
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
        subparsers.add_parser("round-table", help="Administrar e iniciar debates interactivos de mesas redondas")
        subparsers.add_parser("debate", help="Alias de round-table")
        
        team_parser = subparsers.add_parser("team", help="Ejecutar tareas locales secuenciales coordinadas por un equipo")
        team_parser.add_argument("task", nargs="+", help="Descripción de la tarea general a resolver")
        team_parser.add_argument("--agents", default="", help="Nombres o UUIDs de los agentes del equipo separados por comas")
        team_parser.add_argument("-y", "--yes", action="store_true", dest="auto_confirm", help="Modo automático: confirma herramientas sin preguntar")
        
        subparsers.add_parser("whoami", help="Ver información sobre la sesión de usuario activa")
        subparsers.add_parser("user", help="Alias de whoami")
        subparsers.add_parser("register", help="Registrar una nueva cuenta en la plataforma")
        subparsers.add_parser("signup", help="Alias de register")
        
        subparsers.add_parser("logout", help="Cerrar la sesión activa de Arzor localmente")
        subparsers.add_parser("status", help="Muestra el diagnóstico y salud de conexión de Arzor CLI")
        subparsers.add_parser("update", help="Descargar e instalar automáticamente la última versión del CLI")
        subparsers.add_parser("clean", help="Deshacer los cambios de archivos locales de la última tarea")
        
        test_parser = subparsers.add_parser("test-agent", help="Probar el tiempo de respuesta e inferencia de un agente")
        test_parser.add_argument("agent", help="Nombre o UUID del agente personalizado a validar")
        
        plan_parser = subparsers.add_parser("plan", help="Muestra un plan dry-run simulado en memoria de una tarea")
        plan_parser.add_argument("task", nargs="+", help="Descripción de la tarea a simular")
        plan_parser.add_argument("--tier", default="balanced", choices=["fast", "balanced", "pro"], help="Tier de calidad a simular")
        plan_parser.add_argument("--agent", default="", help="Nombre o UUID del agente personalizado a simular")
        
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
        elif args.command in ("round-table", "debate"):
            cmd_round_table(args.url)
        elif args.command == "team":
            cmd_team_collaboration(" ".join(args.task), args.agents, args.url, args.auto_confirm)
        elif args.command in ("whoami", "user"):
            cmd_whoami(args.url)
        elif args.command in ("register", "signup"):
            cmd_register(args.url)
        elif args.command == "logout":
            cmd_logout()
        elif args.command == "status":
            cmd_status(args.url)
        elif args.command == "update":
            cmd_update()
        elif args.command == "clean":
            cmd_clean()
        elif args.command == "test-agent":
            cmd_test_agent(args.agent, args.url)
        elif args.command == "plan":
            run_agent_loop(
                task=" ".join(args.task),
                tier=args.tier,
                auto_confirm=True,  # Para plan se pre-confirma la simulación sin molestar
                agent_id=args.agent,
                base_url=args.url,
                dry_run=True
            )
            
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
