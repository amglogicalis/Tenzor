import os
import sys
import tempfile
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

# Añadir la raíz del proyecto y cli/ al path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from cli.arzor import (
    list_directory,
    read_file_content,
    write_file_content,
    edit_file_content,
    execute_system_command,
    resolve_agent_id
)
from app.main import app

client = TestClient(app)

def test_cli_tools_write_and_read():
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = os.path.join(tmpdir, "test.txt")
        
        # 1. Escribir
        write_res = write_file_content(file_path, "Hola Arzor CLI Agent")
        assert "Éxito" in write_res
        assert os.path.exists(file_path)
        
        # 2. Leer
        read_res = read_file_content(file_path)
        assert read_res == "Hola Arzor CLI Agent"

def test_cli_tools_list():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Crear un subdirectorio y un archivo
        os.makedirs(os.path.join(tmpdir, "subdir"))
        with open(os.path.join(tmpdir, "file.txt"), "w") as f:
            f.write("test")
            
        list_res = list_directory(tmpdir)
        assert "subdir/" in list_res
        assert "file.txt" in list_res

def test_cli_tools_edit():
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = os.path.join(tmpdir, "code.py")
        write_file_content(file_path, "def main():\n    print('Hello')\n")
        
        edit_res = edit_file_content(file_path, "print('Hello')", "print('Arzor')")
        assert "Éxito" in edit_res
        
        new_content = read_file_content(file_path)
        assert "print('Arzor')" in new_content

def test_cli_tools_execute():
    # Probar un comando básico
    res = execute_system_command("echo Hola")
    assert "Hola" in res
    assert "Retorno: 0" in res

def test_agent_step_endpoint_unauthorized():
    # El endpoint debe denegar el acceso si no hay token JWT válido
    response = client.post(
        "/platform/crew/agent-step",
        json={
            "messages": [{"role": "user", "content": "Hola"}],
            "tier": "balanced"
        }
    )
    assert response.status_code == 401

def test_resolve_agent_id_match():
    # Mockear api_get para que devuelva una lista simulada de agentes del usuario
    mock_response = {
        "agents": [
            {"id": "uuid-python-agent", "name": "Dev Python"},
            {"id": "uuid-ops-agent", "name": "Devops Specialist"}
        ]
    }
    with patch("cli.arzor.api_get", return_value=mock_response):
        # 1. Coincidencia por nombre
        agent_id = resolve_agent_id("Dev Python", "http://localhost:8000")
        assert agent_id == "uuid-python-agent"
        
        # 2. Coincidencia insensible a mayúsculas
        agent_id_lower = resolve_agent_id("dev python", "http://localhost:8000")
        assert agent_id_lower == "uuid-python-agent"
        
        # 3. Sin coincidencia: devuelve el string original
        fallback = resolve_agent_id("uuid-directo-1234", "http://localhost:8000")
        assert fallback == "uuid-directo-1234"

def test_get_agents_unauthorized():
    response = client.get("/platform/agents")
    assert response.status_code == 401

def test_get_models_unauthorized():
    response = client.get("/platform/keys/models/available")
    assert response.status_code == 401
