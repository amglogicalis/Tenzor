#!/usr/bin/env python3
"""
tenzor_crew.py
CLI de Arzor DevCrew — asistente de desarrollo con IA desde la terminal.

Uso:
  python cli/tenzor_crew.py plan   "Implementar sistema de caché Redis"
  python cli/tenzor_crew.py write  --step-title "Crear RedisClient" --step-desc "..."
  python cli/tenzor_crew.py plan   "..." --tier pro --tech "Python, FastAPI, Redis"
  python cli/tenzor_crew.py write  --step-title "..." --file src/cache.py --existing src/cache.py

Variables de entorno requeridas:
  ARZOR_TOKEN   → Token JWT de sesión (obtenido con login)
  ARZOR_URL     → URL base de la API (default: http://localhost:8000)

Opcionales:
  ARZOR_AGENT   → UUID del agente a usar por defecto
"""
import os
import sys
import json
import argparse
import textwrap
from typing import Optional

import requests

# ─── Config ───────────────────────────────────────────────────────────────────
DEFAULT_URL = os.getenv("ARZOR_URL", "http://localhost:8000")
TOKEN = os.getenv("ARZOR_TOKEN", "")
DEFAULT_AGENT = os.getenv("ARZOR_AGENT", "")

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
    """Aplica color ANSI si el terminal lo soporta."""
    if not sys.stdout.isatty():
        return text
    return f"{COLORS.get(color,'')}{text}{COLORS['reset']}"


def header():
    print()
    print(c("  🤖 Arzor DevCrew", "purple") + c(" — Asistente de Desarrollo con IA", "gray"))
    print(c("  " + "─" * 50, "gray"))
    print()


# ─── API Client ───────────────────────────────────────────────────────────────

def api_post(path: str, payload: dict, base_url: str = DEFAULT_URL) -> dict:
    url = f"{base_url}{path}"
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        print(c(f"\n  ✗ Error: No se puede conectar a {base_url}", "red"))
        print(c(f"    Asegúrate de que el servidor está corriendo (ARZOR_URL={base_url})", "gray"))
        sys.exit(1)
    except requests.exceptions.Timeout:
        print(c("\n  ✗ Timeout: El servidor tardó demasiado en responder.", "red"))
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        detail = "Error desconocido"
        try:
            detail = e.response.json().get("detail", str(e))
        except Exception:
            pass
        print(c(f"\n  ✗ Error {e.response.status_code}: {detail}", "red"))
        sys.exit(1)


# ─── Comandos ─────────────────────────────────────────────────────────────────

def cmd_plan(args):
    """Genera un plan de implementación para una tarea."""
    header()
    task = " ".join(args.task)
    print(c("  📋 Generando plan de implementación…", "cyan"))
    print(c(f"  Tarea: {task[:80]}{'…' if len(task)>80 else ''}", "gray"))
    print(c(f"  Stack: {args.tech}", "gray"))
    print(c(f"  Tier:  {args.tier}", "gray"))
    print()

    payload = {
        "task": task,
        "tech_stack": args.tech,
        "context": args.context or "",
        "tier": args.tier,
    }
    if args.agent or DEFAULT_AGENT:
        payload["agent_id"] = args.agent or DEFAULT_AGENT

    result = api_post("/platform/crew/plan", payload, args.url)

    # Detectar error de parseo
    if "error" in result and "raw_response" in result:
        print(c("  ⚠ El LLM no respetó el formato JSON. Respuesta raw:", "yellow"))
        print(textwrap.indent(result["raw_response"], "    "))
        return

    # Mostrar resumen
    print(c("  ✅ Plan generado:", "green"))
    print()
    print(c("  📝 RESUMEN", "bold"))
    print(f"  {result.get('summary', 'N/A')}")
    print()
    print(f"  Complejidad: {_complexity_badge(result.get('complexity','?'))}  "
          f"Estimación: {c(str(result.get('estimated_hours','?')) + 'h', 'cyan')}")
    print()

    # Pasos
    steps = result.get("steps", [])
    if steps:
        print(c("  📌 PASOS DE IMPLEMENTACIÓN", "bold"))
        print()
        for step in steps:
            type_icon = {"create": "🆕", "modify": "✏️", "delete": "🗑️",
                         "config": "⚙️", "test": "🧪"}.get(step.get("type", ""), "📌")
            print(f"  {type_icon}  {c(f'[{step[\"id\"]}]', 'gray')} {c(step['title'], 'white')}")
            print(f"     {c(step.get('description',''), 'gray')}")
            if step.get("files"):
                files_str = ", ".join(c(f, "cyan") for f in step["files"])
                print(f"     Archivos: {files_str}")
            print()

    # Riesgos
    risks = result.get("risks", [])
    if risks:
        print(c("  ⚠ RIESGOS IDENTIFICADOS", "yellow"))
        for r in risks:
            print(f"  • {r}")
        print()

    # Dependencias
    deps = result.get("dependencies", [])
    if deps:
        print(c("  📦 DEPENDENCIAS", "gray"))
        print(f"  {', '.join(deps)}")
        print()

    # Meta
    meta = result.get("_meta", {})
    if meta:
        print(c(f"  Provider: {meta.get('provider')} · {meta.get('model')} · "
                f"{meta.get('tokens_in',0)+meta.get('tokens_out',0)} tokens · "
                f"{meta.get('latency_ms',0):.0f}ms", "gray"))

    # Guardar si se especifica output
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(c(f"\n  💾 Plan guardado en: {args.output}", "green"))


def cmd_write(args):
    """Genera código para un paso del plan."""
    header()
    print(c("  ⚡ Generando código…", "cyan"))
    print(c(f"  Paso: {args.step_title}", "gray"))
    if args.files:
        print(c(f"  Archivos: {', '.join(args.files)}", "gray"))
    print()

    existing_code = ""
    if args.existing:
        try:
            with open(args.existing, "r", encoding="utf-8") as f:
                existing_code = f.read()
            print(c(f"  📂 Contexto cargado: {args.existing} ({len(existing_code)} chars)", "gray"))
        except FileNotFoundError:
            print(c(f"  ⚠ Archivo de contexto no encontrado: {args.existing}", "yellow"))

    payload = {
        "step_title": args.step_title,
        "step_description": args.step_desc,
        "files": args.files or [],
        "existing_code": existing_code,
        "tier": args.tier,
    }
    if args.agent or DEFAULT_AGENT:
        payload["agent_id"] = args.agent or DEFAULT_AGENT

    result = api_post("/platform/crew/write", payload, args.url)

    if "error" in result and "raw_response" in result:
        print(c("  ⚠ El LLM no respetó el formato JSON. Respuesta raw:", "yellow"))
        print(textwrap.indent(result["raw_response"], "    "))
        return

    # Mostrar código
    file_dest = result.get("file", "output.py")
    language = result.get("language", "python")
    code = result.get("code", "")
    notes = result.get("integration_notes", "")
    hints = result.get("test_hints", [])

    print(c(f"  ✅ Código generado para: {c(file_dest, 'cyan')}", "green"))
    print(c(f"  Lenguaje: {language}", "gray"))
    print()
    print(c("  ─── CÓDIGO ───────────────────────────────────────────", "gray"))
    print()
    print(textwrap.indent(code, "  "))
    print()
    print(c("  ─── NOTAS DE INTEGRACIÓN ─────────────────────────────", "gray"))
    print(f"  {notes}")
    print()
    if hints:
        print(c("  ─── SUGERENCIAS DE TEST ──────────────────────────────", "gray"))
        for h in hints:
            print(f"  • {h}")
        print()

    # Guardar el código generado
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(code)
        print(c(f"  💾 Código guardado en: {args.output}", "green"))
    elif args.write_to_file:
        try:
            with open(file_dest, "w", encoding="utf-8") as f:
                f.write(code)
            print(c(f"  💾 Código escrito en: {file_dest}", "green"))
        except Exception as e:
            print(c(f"  ✗ No se pudo escribir el archivo: {e}", "red"))

    meta = result.get("_meta", {})
    if meta:
        print(c(f"  Provider: {meta.get('provider')} · {meta.get('model')} · "
                f"{meta.get('tokens_in',0)+meta.get('tokens_out',0)} tokens · "
                f"{meta.get('latency_ms',0):.0f}ms", "gray"))


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _complexity_badge(complexity: str) -> str:
    colors = {"low": "green", "medium": "yellow", "high": "red"}
    icons = {"low": "🟢", "medium": "🟡", "high": "🔴"}
    return f"{icons.get(complexity,'❓')} {c(complexity.upper(), colors.get(complexity,'white'))}"


# ─── CLI Entry Point ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="tenzor-crew",
        description="Arzor DevCrew — Asistente de desarrollo con IA",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        Ejemplos:
          %(prog)s plan "Añadir autenticación JWT a la API"
          %(prog)s plan "Sistema de caché Redis" --tier pro --tech "Python, Redis, FastAPI"
          %(prog)s write --step-title "Crear RedisClient" --step-desc "Cliente Redis reutilizable"
          %(prog)s write --step-title "Crear modelo User" --files models/user.py --existing models/user.py
          
        Variables de entorno:
          ARZOR_TOKEN   → Token JWT (requerido para API)
          ARZOR_URL     → URL del servidor (default: http://localhost:8000)
          ARZOR_AGENT   → UUID del agente por defecto
        """)
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="URL base de la API")
    parser.add_argument("--tier", default="balanced", choices=["fast","balanced","pro"],
                        help="Tier del provider de IA")
    parser.add_argument("--agent", default="", help="UUID del agente a usar")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # plan
    plan_p = subparsers.add_parser("plan", help="Genera un plan de implementación")
    plan_p.add_argument("task", nargs="+", help="Descripción de la tarea")
    plan_p.add_argument("--tech", default="Python, FastAPI, Supabase",
                        help="Stack tecnológico (default: Python, FastAPI, Supabase)")
    plan_p.add_argument("--context", default="", help="Contexto adicional")
    plan_p.add_argument("--output", default="", help="Archivo donde guardar el plan (JSON)")

    # write
    write_p = subparsers.add_parser("write", help="Genera código para un paso del plan")
    write_p.add_argument("--step-title", required=True, dest="step_title",
                         help="Título del paso")
    write_p.add_argument("--step-desc", required=True, dest="step_desc",
                         help="Descripción detallada del paso")
    write_p.add_argument("--files", nargs="*", default=[],
                         help="Archivos a crear/modificar")
    write_p.add_argument("--existing", default="",
                         help="Archivo existente a usar como contexto (se lee su contenido)")
    write_p.add_argument("--output", default="",
                         help="Guardar el código generado en este archivo")
    write_p.add_argument("--write-to-file", action="store_true", dest="write_to_file",
                         help="Escribe el código al archivo de destino indicado por el LLM")

    args = parser.parse_args()

    if args.command == "plan":
        cmd_plan(args)
    elif args.command == "write":
        cmd_write(args)


if __name__ == "__main__":
    main()
