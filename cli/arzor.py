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

# Cargar variables de entorno de .env local si existe
load_dotenv()

DEFAULT_URL = os.getenv("ARZOR_URL", "http://localhost:8000")
TOKEN = os.getenv("ARZOR_TOKEN", "")

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
        # Asegurar directorios padres
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
            
        # Reemplazar solo una ocurrencia para evitar errores masivos no deseados
        new_content = content.replace(target_text, replacement_text, 1)
        
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return f"Éxito: Archivo '{path}' modificado correctamente."
    except Exception as e:
        return f"Error al editar archivo: {str(e)}"

def execute_system_command(command: str) -> str:
    """Ejecuta un comando de consola del sistema operativo y devuelve stdout/stderr."""
    try:
        # Ejecutar en shell
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

# ─── API Client & ReAct Loop ──────────────────────────────────────────────────

def call_agent_step(messages: List[Dict[str, str]], base_url: str, tier: str, agent_id: str = "") -> dict:
    """Llama al backend de Arzor para obtener el siguiente paso del agente ReAct."""
    url = f"{base_url}/platform/crew/agent-step"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {TOKEN}"
    }
    payload = {
        "messages": messages,
        "tier": tier,
        "agent_id": agent_id or None
    }
    
    resp = requests.post(url, json=payload, headers=headers, timeout=120)
    resp.raise_for_status()
    return resp.json()

def run_agent_loop(task: str, tier: str, auto_confirm: bool, agent_id: str, base_url: str):
    """Ejecuta el bucle ReAct del agente autónomo local."""
    header()
    
    if not TOKEN:
        print(c("  ✗ Error: La variable de entorno ARZOR_TOKEN está vacía.", "red"))
        print(c("    Regístrate o inicia sesión en la plataforma y configúrala en tu entorno o en el archivo .env", "gray"))
        sys.exit(1)

    print(c("  🚀 Iniciando agente autónomo local...", "cyan"))
    print(c(f"  Tarea: {task}", "white"))
    print(c(f"  Tier:  {tier}  |  Modo Auto-Confirmar: {'SÍ' if auto_confirm else 'NO'}", "gray"))
    print(c(f"  URL del Servidor: {base_url}", "gray"))
    print()

    # Inicializar el historial de conversación ReAct
    messages = [
        {"role": "user", "content": task}
    ]
    
    step_count = 0
    max_steps = 25
    
    while step_count < max_steps:
        step_count += 1
        print(c(f"  [Paso {step_count}/{max_steps}] Pensando...", "gray"))
        
        try:
            # Obtener el siguiente paso (pensamiento + acción) del LLM
            step_result = call_agent_step(messages, base_url, tier, agent_id)
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
        
        # Guardar la respuesta del asistente en el historial para mantener la consistencia
        assistant_msg = {
            "role": "assistant",
            "content": json.dumps({"thought": thought, "action": action, "args": args})
        }
        messages.append(assistant_msg)
        
        # Mostrar el razonamiento de la IA
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
            
        # Procesar herramientas
        print(c("  🛠️  Acción solicitada:", "yellow"))
        print(f"     Herramienta: {c(action, 'bold')}")
        print(f"     Argumentos:  {json.dumps(args)}")
        print()
        
        # Solicitar aprobación si no está en modo automático
        if not auto_confirm:
            try:
                confirm = input(c("     ¿Deseas permitir esta acción? [Y/n]: ", "bold")).strip().lower()
                if confirm not in ("", "y", "yes", "s", "si"):
                    print(c("\n  ✗ Ejecución cancelada por el usuario.", "red"))
                    # Enviar observación de cancelación a la IA para que pueda razonar qué hacer
                    messages.append({
                        "role": "user",
                        "content": "Acción rechazada por el usuario. Corrige tu enfoque o finaliza la tarea."
                    })
                    continue
            except (KeyboardInterrupt, EOFError):
                print(c("\n  ✗ Interrumpido por el usuario.", "red"))
                sys.exit(0)
                
        # Ejecutar la herramienta local
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
            
        # Imprimir resultado de la observación en consola para el desarrollador
        print(c("  👁️  Observación (Resultado):", "gray"))
        truncated_obs = observation[:500] + "..." if len(observation) > 500 else observation
        print(textwrap.indent(truncated_obs, "     "))
        print()
        
        # Añadir observación al historial del agente
        messages.append({
            "role": "user",
            "content": f"Resultado de la herramienta:\n{observation}"
        })
        
    else:
        print(c("  ✗ Límite de pasos alcanzado sin completar la tarea.", "red"))
        print()

# ─── CLI Entry Point ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="arzor",
        description="Agente CLI de Desarrollo Autónomo de Arzor AIs (el 'antigravity/codex' local)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        Ejemplos de uso:
          python cli/arzor.py "Crea un servidor Flask básico en un archivo llamado app.py"
          python cli/arzor.py "Escribe un script de python que ordene una lista de números" --tier pro
          python cli/arzor.py "Ejecuta los tests unitarios con pytest y corrige los fallos si los hay" -y
          
        Variables de entorno soportadas:
          ARZOR_TOKEN   → Token de autenticación de sesión de la plataforma
          ARZOR_URL     → URL base del servidor (default: http://localhost:8000)
        """)
    )
    parser.add_argument("task", nargs="*", help="Descripción de la tarea de desarrollo a realizar")
    parser.add_argument("--url", default=DEFAULT_URL, help="URL base del servidor de Arzor")
    parser.add_argument("--tier", default="balanced", choices=["fast", "balanced", "pro"],
                        help="Tier de calidad del modelo a utilizar (default: balanced)")
    parser.add_argument("-y", "--yes", action="store_true", dest="auto_confirm",
                        help="Modo automático: ejecuta acciones de herramientas sin pedir confirmación")
    parser.add_argument("--agent", default="", help="UUID de un agente especializado de tu panel de Arzor")

    args = parser.parse_args()

    # Si se ejecuta sin argumentos o sin tarea, mostrar la ayuda
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
