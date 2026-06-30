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

def test_save_token_to_env_mocked():
    from cli.arzor import save_token_to_env
    # Mockear el filesystem para simular la actualización del .env
    with patch("os.path.exists", return_value=True), \
         patch("builtins.open") as mock_open:
        
        mock_file = mock_open.return_value.__enter__.return_value
        mock_file.readlines.return_value = ["ARZOR_URL=https://web.com\n", "ARZOR_TOKEN=old_token\n"]
        
        save_token_to_env("super_new_token")
        
        # Verificar que se llamó a writelines con la línea actualizada
        mock_file.writelines.assert_called_once()
        written_lines = mock_file.writelines.call_args[0][0]
        assert 'ARZOR_TOKEN="super_new_token"\n' in written_lines

def test_is_coding_model_filter():
    from cli.arzor import is_coding_model
    # 1. Aceptados (whitelist o palabras clave)
    assert is_coding_model("gemini-2.0-flash", "google") is True
    assert is_coding_model("claude-3-5-sonnet-20241022", "anthropic") is True
    assert is_coding_model("qwen-2.5-coder-7b", "openrouter") is True
    assert is_coding_model("llama-3.3-70b-instruct", "watsonx") is True
    
    # 2. Filtrados (conversacionales pequeños sin instruct ni coder)
    assert is_coding_model("llama-3-8b", "watsonx") is False
    assert is_coding_model("gemma-2b", "groq") is False

def test_cli_subparsers_registration():
    from unittest.mock import ANY
    with patch("sys.argv", ["arzor", "debate"]), \
         patch("cli.arzor.cmd_round_table") as mock_rt:
        try:
            from cli.arzor import main
            main()
        except SystemExit:
            pass
        mock_rt.assert_called_once()

def test_cli_team_registration():
    from unittest.mock import ANY
    with patch("sys.argv", ["arzor", "team", "Crea", "un", "archivo", "--agents", "Backend"]), \
         patch("cli.arzor.cmd_team_collaboration") as mock_team:
        try:
            from cli.arzor import main
            main()
        except SystemExit:
            pass
        mock_team.assert_called_once_with("Crea un archivo", "Backend", ANY, ANY)

def test_cli_whoami_registration():
    with patch("sys.argv", ["arzor", "whoami"]), \
         patch("cli.arzor.cmd_whoami") as mock_whoami:
        try:
            from cli.arzor import main
            main()
        except SystemExit:
            pass
        mock_whoami.assert_called_once()

def test_cli_register_registration():
    with patch("sys.argv", ["arzor", "register"]), \
         patch("cli.arzor.cmd_register") as mock_register:
        try:
            from cli.arzor import main
            main()
        except SystemExit:
            pass
        mock_register.assert_called_once()

def test_cli_logout_registration():
    with patch("sys.argv", ["arzor", "logout"]), \
         patch("cli.arzor.cmd_logout") as mock_logout:
        try:
            from cli.arzor import main
            main()
        except SystemExit:
            pass
        mock_logout.assert_called_once()

def test_cli_status_registration():
    with patch("sys.argv", ["arzor", "status"]), \
         patch("cli.arzor.cmd_status") as mock_status:
        try:
            from cli.arzor import main
            main()
        except SystemExit:
            pass
        mock_status.assert_called_once()

def test_cli_update_registration():
    with patch("sys.argv", ["arzor", "update"]), \
         patch("cli.arzor.cmd_update") as mock_update:
        try:
            from cli.arzor import main
            main()
        except SystemExit:
            pass
        mock_update.assert_called_once()

def test_cli_clean_registration():
    with patch("sys.argv", ["arzor", "clean"]), \
         patch("cli.arzor.cmd_clean") as mock_clean:
        try:
            from cli.arzor import main
            main()
        except SystemExit:
            pass
        mock_clean.assert_called_once()

def test_cli_test_agent_registration():
    from unittest.mock import ANY
    with patch("sys.argv", ["arzor", "test-agent", "Dev Python"]), \
         patch("cli.arzor.cmd_test_agent") as mock_test:
        try:
            from cli.arzor import main
            main()
        except SystemExit:
            pass
        mock_test.assert_called_once_with("Dev Python", ANY)

def test_cli_plan_registration():
    from unittest.mock import ANY
    with patch("sys.argv", ["arzor", "plan", "Crea", "un", "test"]), \
         patch("cli.arzor.run_agent_loop") as mock_loop:
        try:
            from cli.arzor import main
            main()
        except SystemExit:
            pass
        mock_loop.assert_called_once_with(
            task="Crea un test",
            tier=ANY,
            auto_confirm=ANY,
            agent_id=ANY,
            base_url=ANY,
            dry_run=True,
            max_steps=ANY
        )

def test_read_file_lines_physical_tool(tmp_path):
    import os
    from cli.arzor import read_file_lines
    test_file = tmp_path / "test_read.py"
    content = (
        "import sys\n"
        "class MyClass:\n"
        "    def hello(self):\n"
        "        print('hello')\n"
        "def main():\n"
        "    pass\n"
    )
    test_file.write_text(content, encoding="utf-8")
    
    # Leer líneas 2 a 4
    res = read_file_lines(str(test_file), 2, 4)
    assert "[SKELETON ESTRUCTURAL DEL ARCHIVO" in res
    assert "class MyClass" in res
    assert "def hello" in res
    assert "2: class MyClass:" in res
    assert "3:     def hello(self):" in res

def test_write_file_patch_physical_tool(tmp_path):
    import os
    from cli.arzor import write_file_patch
    test_file = tmp_path / "test_patch.py"
    test_file.write_text("linea1\nlinea2\nlinea3\n", encoding="utf-8")
    
    # Parche unificado simple
    patch_str = (
        "@@ -1,3 +1,3 @@\n"
        " linea1\n"
        "-linea2\n"
        "+linea2_modificada\n"
        " linea3\n"
    )
    
    res = write_file_patch(str(test_file), patch_str)
    assert "Éxito: Parche aplicado correctamente" in res
    assert test_file.read_text(encoding="utf-8") == "linea1\nlinea2_modificada\nlinea3\n"

def test_search_codebase_physical_tool():
    from cli.arzor import search_codebase
    # Buscar una query que sabemos que existe en el repo, por ejemplo "def run_agent_loop"
    res = search_codebase("def run_agent_loop")
    assert "arzor.py" in res
    assert "run_agent_loop" in res

def test_manage_scratchpad_physical_tool(tmp_path):
    import os
    from unittest.mock import patch
    from cli.arzor import manage_scratchpad
    
    scratch_file = tmp_path / ".arzor_scratchpad.json"
    with patch("os.path.dirname", return_value=str(tmp_path)):
        # Escribir en scratchpad
        res_w = manage_scratchpad("write", "mi memoria temporal")
        assert "Éxito" in res_w
        assert os.path.exists(str(scratch_file))
        
        # Leer de scratchpad
        res_r = manage_scratchpad("read")
        assert "mi memoria temporal" in res_r

def test_cli_max_steps_argparse():
    from unittest.mock import ANY
    with patch("sys.argv", ["arzor", "plan", "Crea", "un", "test", "--max-steps", "15"]), \
         patch("cli.arzor.run_agent_loop") as mock_loop:
        try:
            from cli.arzor import main
            main()
        except SystemExit:
            pass
        mock_loop.assert_called_once_with(
            task="Crea un test",
            tier=ANY,
            auto_confirm=ANY,
            agent_id=ANY,
            base_url=ANY,
            dry_run=True,
            max_steps=15
        )
