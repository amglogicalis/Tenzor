#!/usr/bin/env bash
# setup.sh
# Script de Instalación y Onboarding para Arzor AIs CLI (Linux / macOS)

# Colores ANSI
MAGENTA='\033[1;35m'
CYAN='\033[1;36m'
YELLOW='\033[1;33m'
GREEN='\033[1;32m'
GRAY='\033[0;90m'
RED='\033[1;31m'
NC='\033[0m' # No Color

echo -e ""
echo -e "${MAGENTA}  🔮 Bienvenido al Onboarding de Arzor AIs CLI 🔮${NC}"
echo -e "${GRAY}  ═════════════════════════════════════════════${NC}"
echo -e ""

# 1. Comprobar Python
echo -e "${CYAN}  [1/5] Comprobando entorno de Python...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}  ✗ Error: Python 3 no está instalado o no se encuentra en el PATH.${NC}"
    echo -e "${YELLOW}    Instálalo a través del gestor de paquetes de tu distribución.${NC}"
    exit 1
fi
py_version=$(python3 --version)
echo -e "        Entorno detectado: ${GRAY}$py_version${NC}"

# 2. Crear Entorno Virtual
echo -e "${CYAN}  [2/5] Configurando el entorno virtual (venv)...${NC}"
if [ ! -d "venv" ]; then
    echo -e "        Creando entorno virtual local...${GRAY}${NC}"
    python3 -m venv venv
else
    echo -e "        Entorno virtual local ya existe.${GRAY}${NC}"
fi

# 3. Instalar Dependencias y Empaquetar CLI
echo -e "${CYAN}  [3/5] Instalando dependencias y registrando el CLI...${NC}"
./venv/bin/pip install --upgrade pip -q
./venv/bin/pip install -r requirements.txt -q
# Instalar en el Python global de usuario para registrar arzor
echo -e "        Instalando comando arzor en el sistema de usuario...${GRAY}${NC}"
python3 -m pip install -e . -q --break-system-packages 2>/dev/null || python3 -m pip install -e . -q

# 4. Configurar Variables de Entorno (.env)
echo -e "${CYAN}  [4/5] Configurando archivo de variables de entorno (.env)...${NC}"
if [ ! -f ".env" ]; then
    echo -e "        Creando nuevo archivo .env a partir de la plantilla...${GRAY}${NC}"
    cp .env.example .env
fi

# Preguntar la URL del servidor
default_url="https://tenzor-web.onrender.com"
echo -e ""
echo -e "${YELLOW}        ¿A qué dirección URL de servidor de Arzor deseas conectarte?${NC}"
echo -e "${GRAY}        [Enter para usar producción: $default_url]${NC}"
read -p "        URL del Servidor: " input_url
input_url=$(echo "$input_url" | xargs) # strip whitespace

if [ -z "$input_url" ]; then
    input_url=$default_url
fi

# Guardar la URL en el .env
if grep -q "^ARZOR_URL=" .env; then
    # Reemplazar línea existente
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s|^ARZOR_URL=.*|ARZOR_URL=\"$input_url\"|g" .env
    else
        sed -i "s|^ARZOR_URL=.*|ARZOR_URL=\"$input_url\"|g" .env
    fi
else
    # Concatenar al final
    echo -e "\nARZOR_URL=\"$input_url\"" >> .env
fi
echo -e "        ${GREEN}✔ Servidor configurado: $input_url${NC}"

# 5. Configurar el PATH en Linux/macOS
echo -e ""
echo -e "${CYAN}  [5/5] Configurando el PATH...${NC}"
user_bin="$HOME/.local/bin"
path_updated=false

if [[ ":$PATH:" != *":$user_bin:"* ]]; then
    echo -e "        Añadiendo $user_bin a tu PATH...${GRAY}${NC}"
    
    # Determinar qué shell usa el usuario
    current_shell=$(basename "$SHELL")
    profile_file="$HOME/.bashrc"
    
    if [ "$current_shell" == "zsh" ]; then
        profile_file="$HOME/.zshrc"
    elif [ "$current_shell" == "ksh" ]; then
        profile_file="$HOME/.profile"
    fi
    
    echo -e "\n# Arzor CLI Global Command Path" >> "$profile_file"
    echo -e "export PATH=\"\$HOME/.local/bin:\$PATH\"" >> "$profile_file"
    echo -e "        ${GREEN}✔ PATH actualizado en $profile_file.${NC}"
    path_updated=true
else
    echo -e "        La carpeta de scripts ya se encuentra en tu PATH.${GRAY}${NC}"
fi

# 6. Autenticación Inicial
echo -e ""
echo -e "${GREEN}  🎉 ¡Onboarding del CLI completado con éxito! 🎉${NC}"
echo -e ""

if [ "$path_updated" = true ]; then
    echo -e "${YELLOW}  ⚠️  IMPORTANTE: Ejecuta 'source $profile_file' o abre una nueva terminal${NC}"
    echo -e "${YELLOW}      para que tu shell cargue el nuevo PATH global y puedas escribir 'arzor'.${NC}"
    echo -e ""
fi

echo -e "${CYAN}  🚀 Iniciando login guiado para conectar tu consola al instante...${NC}"
echo -e ""
./venv/bin/python3 cli/arzor.py login
