# r_monitor 打包脚本
# 生成单目录(onedir)版 Windows 桌面程序，并包含 scapy（npcap 抓包）。
# 用法（在项目根目录执行）：
#   powershell -ExecutionPolicy Bypass -File .\build.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# 生成 exe 图标与版本资源（纯标准库，无第三方依赖）
Write-Host "==> 生成程序图标"
python tools\generate_icon.py

Write-Host "==> 生成 exe 版本资源"
python tools\generate_version_info.py

Write-Host "==> 安装/升级 PyInstaller"
python -m pip install --upgrade pyinstaller

# spec 已开启 upx=True；PyInstaller 需要能在 PATH 中找到 upx.exe。
# winget 安装的 UPX 可能未加入 PATH，这里自动探测其目录并临时加入 PATH。
$upxPath = $null
$upxCmd = Get-Command upx -ErrorAction SilentlyContinue
if ($upxCmd) { $upxPath = $upxCmd.Source }
if (-not $upxPath) {
    $upxExe = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Directory -Filter 'UPX.UPX_*' -ErrorAction SilentlyContinue |
        ForEach-Object { Get-ChildItem $_.FullName -Recurse -Filter 'upx.exe' -File -ErrorAction SilentlyContinue } |
        Select-Object -First 1
    if ($upxExe) {
        $env:PATH = "$(Split-Path $upxExe.FullName);$env:PATH"
        $upxPath = $upxExe.FullName
    }
}
if ($upxPath) {
    Write-Host "==> 使用 UPX：$upxPath"
} else {
    Write-Warning "未检测到 upx.exe，本次打包将跳过 UPX 压缩（体积会偏大）。可执行 'winget install upx.UPX' 安装。"
}

Write-Host "==> 打包（onedir + 无控制台 + 精简 scapy + UPX + 裁剪未用 Qt 模块）"
python -m PyInstaller --noconfirm --clean r_monitor.spec

Write-Host ""
Write-Host "==> 完成"
Write-Host "    主程序：dist\r_monitor\r_monitor.exe"
