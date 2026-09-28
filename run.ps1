<#
.SYNOPSIS
    Levanta el backend Appalta2 en local (Windows / PowerShell).

.DESCRIPTION
    1. Crea el entorno virtual (venv) si no existe e instala requirements.txt.
    2. Verifica que exista el archivo .env con DATABASE_URL.
    3. Si la base de datos no existe, la crea y ejecuta sql/*.sql en orden.
    4. Inicia uvicorn con app.main:app.

.EXAMPLE
    .\run.ps1
    .\run.ps1 -Port 8080 -NoReload
    .\run.ps1 -SkipDb          # no toca PostgreSQL
    .\run.ps1 -InstallDeps     # fuerza pip install -r requirements.txt
#>
param(
    [string]$BindHost = "0.0.0.0",
    [int]$Port = 8000,
    [switch]$NoReload,
    [switch]$SkipDb,
    [switch]$InstallDeps
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------
# 1. Entorno virtual y dependencias
# ---------------------------------------------------------------
$venvPython = Join-Path $PSScriptRoot "venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Step "Creando entorno virtual en .\venv"
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3.11 -m venv venv }
    else { python -m venv venv }
    if (-not (Test-Path $venvPython)) { Fail "No se pudo crear el venv. Instala Python 3.10+." }
    $InstallDeps = $true
}

if ($InstallDeps) {
    Write-Step "Instalando dependencias (requirements.txt)"
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { Fail "Fallo pip install." }
}

# ---------------------------------------------------------------
# 2. Archivo .env
# ---------------------------------------------------------------
if (-not (Test-Path ".env")) {
    Fail "No existe .env. Crea uno con al menos DATABASE_URL, BACKEND_URL y MAIL_*."
}

$envVars = @{}
Get-Content ".env" | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
        $envVars[$Matches[1]] = $Matches[2].Trim('"', "'")
    }
}
if (-not $envVars["DATABASE_URL"]) { Fail "DATABASE_URL no esta definida en .env." }

# ---------------------------------------------------------------
# 3. Base de datos (crear + migrar si no existe)
# ---------------------------------------------------------------
if (-not $SkipDb) {
    # postgresql+psycopg2://user:pass@host:port/dbname
    $pattern = '^postgres(?:ql)?(?:\+\w+)?://([^:/@]+)(?::([^@]*))?@([^:/]+)(?::(\d+))?/([^?]+)'
    if ($envVars["DATABASE_URL"] -notmatch $pattern) { Fail "No se pudo interpretar DATABASE_URL." }
    $dbUser = [uri]::UnescapeDataString($Matches[1])
    $dbPass = [uri]::UnescapeDataString($Matches[2])
    $dbHost = $Matches[3]
    $dbPort = if ($Matches[4]) { $Matches[4] } else { "5432" }
    $dbName = $Matches[5]

    $psql = (Get-Command psql -ErrorAction SilentlyContinue).Source
    if (-not $psql) {
        $psql = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\psql.exe" -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
    }

    if (-not $psql) {
        Write-Host "AVISO: psql no encontrado; se omite la verificacion de la base de datos." -ForegroundColor Yellow
    }
    else {
        $env:PGPASSWORD = $dbPass
        $env:PGCLIENTENCODING = "UTF8"
        $connArgs = @("-h", $dbHost, "-p", $dbPort, "-U", $dbUser)

        Write-Step "Verificando PostgreSQL en ${dbHost}:${dbPort}"
        $exists = & $psql @connArgs -d postgres -Atc "SELECT 1 FROM pg_database WHERE datname = '$dbName'"
        if ($LASTEXITCODE -ne 0) {
            Fail "No se pudo conectar a PostgreSQL. Revisa que el servicio este activo y el usuario/clave de DATABASE_URL."
        }

        if ($exists -ne "1") {
            Write-Step "Creando base de datos '$dbName'"
            & $psql @connArgs -d postgres -v ON_ERROR_STOP=1 -qc "CREATE DATABASE `"$dbName`" ENCODING 'UTF8' TEMPLATE template0"
            if ($LASTEXITCODE -ne 0) { Fail "No se pudo crear la base de datos." }

            Get-ChildItem "sql\*.sql" | Sort-Object Name | ForEach-Object {
                Write-Step "Ejecutando $($_.Name)"
                & $psql @connArgs -d $dbName -v ON_ERROR_STOP=1 -q -1 -f $_.FullName
                if ($LASTEXITCODE -ne 0) { Fail "Fallo el script $($_.Name)." }
            }
        }
        else {
            Write-Host "    Base de datos '$dbName' ya existe." -ForegroundColor DarkGray
        }

        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    }
}

# ---------------------------------------------------------------
# 4. Iniciar la API
# ---------------------------------------------------------------
$uvicornArgs = @("-m", "uvicorn", "app.main:app", "--host", $BindHost, "--port", $Port)
if (-not $NoReload) { $uvicornArgs += "--reload" }

Write-Step "Iniciando API en http://localhost:$Port  (docs: http://localhost:$Port/docs)"
& $venvPython @uvicornArgs
