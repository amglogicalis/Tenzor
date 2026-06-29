# setup.ps1
# Script de Instalacion y Onboarding para Arzor AIs CLI (Windows PowerShell)

Write-Host ""
Write-Host "  *** Bienvenido al Onboarding de Arzor AIs CLI ***" -ForegroundColor Magenta
Write-Host "  =================================================" -ForegroundColor DarkGray
Write-Host ""

# 1. Comprobar Python
Write-Host "  [1/5] Comprobando entorno de Python..." -ForegroundColor Cyan
$pythonPath = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonPath) {
    Write-Host "  Error: Python no esta instalado o no se encuentra en el PATH." -ForegroundColor Red
    Write-Host "  Descargalo de https://www.python.org/ e intentalo de nuevo." -ForegroundColor Yellow
    Exit 1
}
$pyVersion = python --version
Write-Host "        Entorno detectado: $pyVersion" -ForegroundColor Gray

# 2. Crear Entorno Virtual
Write-Host "  [2/5] Configurando el entorno virtual (venv)..." -ForegroundColor Cyan
if (-not (Test-Path "venv")) {
    Write-Host "        Creando entorno virtual local..." -ForegroundColor Gray
    python -m venv venv
} else {
    Write-Host "        Entorno virtual local ya existe." -ForegroundColor Gray
}

# 3. Instalar Dependencias y Empaquetar CLI
Write-Host "  [3/5] Instalando dependencias y registrando el CLI..." -ForegroundColor Cyan
& .\venv\Scripts\python.exe -m pip install --upgrade pip -q
& .\venv\Scripts\python.exe -m pip install -r requirements.txt -q
# Instalar en el Python global de usuario para el comando global
Write-Host "        Instalando comando arzor en el sistema de usuario..." -ForegroundColor Gray
python -m pip install -e . -q

# 4. Configurar Variables de Entorno (.env)
Write-Host "  [4/5] Configurando archivo de variables de entorno (.env)..." -ForegroundColor Cyan
if (-not (Test-Path ".env")) {
    Write-Host "        Creando nuevo archivo .env a partir de la plantilla..." -ForegroundColor Gray
    Copy-Item ".env.example" ".env"
}

# Preguntar la URL del servidor
$defaultUrl = "https://tenzor-web.onrender.com"
Write-Host ""
Write-Host "        A que direccion URL de servidor de Arzor deseas conectarte?" -ForegroundColor Yellow
Write-Host "        [Enter para usar produccion: $defaultUrl]" -ForegroundColor DarkGray
$inputUrl = Read-Host "        URL del Servidor"
$inputUrl = $inputUrl.Trim()
if ($inputUrl -eq "") {
    $inputUrl = $defaultUrl
}

# Guardar la URL en el .env
$envContent = Get-Content ".env"
$urlConfigured = $false
for ($i = 0; $i -lt $envContent.Count; $i++) {
    if ($envContent[$i].Trim().StartsWith("ARZOR_URL=")) {
        $envContent[$i] = 'ARZOR_URL="' + $inputUrl + '"'
        $urlConfigured = $true
        break
    }
}
if (-not $urlConfigured) {
    $envContent += 'ARZOR_URL="' + $inputUrl + '"'
}
$envContent | Set-Content ".env"
Write-Host "        Servidor configurado: $inputUrl" -ForegroundColor Green

# 5. Configurar el PATH de Windows de forma automatica
Write-Host ""
Write-Host "  [5/5] Configurando el PATH de Windows..." -ForegroundColor Cyan

# Obtener ruta de Scripts del usuario
$userProfile = $env:USERPROFILE
$pyMajorMinor = python -c "import sys; print(f'{sys.version_info.major}{sys.version_info.minor}')"
$scriptsPath = $userProfile + '\AppData\Roaming\Python\Python' + $pyMajorMinor + '\Scripts'

if (-not (Test-Path $scriptsPath)) {
    # Fallback si no existe la carpeta especifica de roaming de la version, buscar la de sistema
    $scriptsPath = 'C:\Python' + $pyMajorMinor + '\Scripts'
}

# Comprobar si ya esta en el PATH
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -notlike ("*" + $scriptsPath + "*")) {
    Write-Host "        Agregando $scriptsPath a tu PATH de usuario de Windows..." -ForegroundColor Gray
    $newPath = $userPath + ';' + $scriptsPath
    [Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
    Write-Host "        PATH de usuario actualizado con exito." -ForegroundColor Green
    $pathUpdated = $true
} else {
    Write-Host "        La carpeta de scripts ya esta en tu PATH de Windows." -ForegroundColor Gray
    $pathUpdated = $false
}

# 6. Autenticacion Inicial
Write-Host ""
Write-Host "  *** Onboarding del CLI completado con exito! ***" -ForegroundColor Green
Write-Host ""

if ($pathUpdated) {
    Write-Host "  IMPORTANTE: Cierra esta consola de PowerShell y abre una ventana nueva" -ForegroundColor Yellow
    Write-Host "  para que Windows cargue el nuevo PATH global y puedas escribir 'arzor'." -ForegroundColor Yellow
    Write-Host ""
}

Write-Host "  Iniciando login guiado para conectar tu consola al instante..." -ForegroundColor Cyan
Write-Host ""
& .\venv\Scripts\python.exe cli/arzor.py login
