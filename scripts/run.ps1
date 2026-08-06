# 统一环境入口：为本项目进程设置 D 盘路径，不修改系统全局环境变量。
# 用法: .\scripts\run.ps1 <command...>
# 例:  .\scripts\run.ps1 uv run litlib doctor

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

# 创建运行时目录（如不存在）
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

# 进程级环境变量（仅本次调用）
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

# 项目内 venv 优先
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $VenvPython) {
    $env:PATH = "$(Split-Path $VenvPython);" + $env:PATH
}

# 执行剩余命令
if ($args.Count -gt 0) {
    if ($args.Count -eq 1) {
        & $args[0]
    } else {
        & $args[0] $args[1..($args.Count - 1)]
    }
    exit $LASTEXITCODE
}
