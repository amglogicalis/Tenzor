import os
import sys
import tempfile
import pytest
from fastapi.testclient import TestClient

# Añadir la raíz del proyecto y cli/ al path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from cli.arzor import (
    list_directory,
    read_file_content,
    write_file_content,
    edit_file_content,
    execute_system_command
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
