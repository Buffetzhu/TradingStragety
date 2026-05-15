#!/usr/bin/env pwsh
# 用途：检查项目是否满足标准目录骨架
# 参数：-Root <项目根目录>（可选，默认当前目录）
# 输出：逐行输出缺失项；无输出表示完整
# 退出码：0=结构完整，1=存在缺失项，2=执行出错
# Known Issues: 若传入的 Root 不存在会直接报错并退出。

param(
    [string]$Root = "."
)

$ErrorActionPreference = "Stop"

try {
    $rootPath = (Resolve-Path $Root).Path
    $requiredDirs = @("playbooks", "scripts", "src", "tests", ".tmp", "config", "data", "output")

    $missing = @()
    foreach ($dir in $requiredDirs) {
        $path = Join-Path $rootPath $dir
        if (-not (Test-Path $path)) {
            $missing += "MISSING_DIR $dir"
        }
    }

    foreach ($line in $missing) {
        Write-Output $line
    }

    if ($missing.Count -gt 0) {
        exit 1
    }

    exit 0
} catch {
    Write-Error $_
    exit 2
}