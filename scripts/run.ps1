# Ortak ortam giriş noktası: bu projenin süreçleri için D sürücüsü yollarını ayarlar, sistem geneli ortam değişkenlerini değiştirmez.
# Kullanım: .\scripts\run.ps1 <command...>
# Örnek:  .\scripts\run.ps1 uv run litlib doctor

$ErrorActionPreference = "Stop"

[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$ProjectRoot = Split-Path -Parent $PSScriptRoot
if ($env:LITLIB_RUNTIME_ROOT) {
    $RuntimeRoot = $env:LITLIB_RUNTIME_ROOT
} elseif ((Split-Path -Qualifier $ProjectRoot) -eq "D:\") {
    $RuntimeRoot = "D:\LitLibRuntime"
} else {
    $RuntimeRoot = Join-Path $ProjectRoot ".litlib-runtime"
}
$env:LITLIB_RUNTIME_ROOT = $RuntimeRoot

# Çalışma zamanı dizinlerini oluştur (yoksa)
$rtDirs = @(
    "$RuntimeRoot\tmp",
    "$RuntimeRoot\cache",
    "$RuntimeRoot\models",
    "$RuntimeRoot\chrome\profile",
    "$RuntimeRoot\chrome\cache",
    "$RuntimeRoot\chrome\downloads",
    "$RuntimeRoot\backups"
)
foreach ($d in $rtDirs) {
    if (-not (Test-Path -LiteralPath $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
}

# Süreç düzeyinde ortam değişkenleri (yalnız bu çağrı için)
$env:TEMP = "$RuntimeRoot\tmp"
$env:TMP = "$RuntimeRoot\tmp"
$env:UV_CACHE_DIR = "$RuntimeRoot\cache\uv"
$env:PIP_CACHE_DIR = "$RuntimeRoot\cache\pip"
$env:XDG_CACHE_HOME = "$RuntimeRoot\cache"
$env:HF_HOME = "$RuntimeRoot\cache\huggingface"
$env:TORCH_HOME = "$RuntimeRoot\cache\torch"
$env:NODE_COMPILE_CACHE = "$RuntimeRoot\cache\node"
$env:npm_config_cache = "$RuntimeRoot\cache\npm"
$env:PYTHONPYCACHEPREFIX = "$RuntimeRoot\cache\python"

# Proje içindeki venv önceliklidir
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $VenvPython) {
    $env:PATH = "$(Split-Path $VenvPython);" + $env:PATH
}

# Kalan komutu çalıştır
if ($args.Count -gt 0) {
    if ($args.Count -eq 1) {
        & $args[0]
    } else {
        & $args[0] $args[1..($args.Count - 1)]
    }
    exit $LASTEXITCODE
}
