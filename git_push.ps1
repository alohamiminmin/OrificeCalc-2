# ============================================================
# OrificeCalc-2 git push スクリプト
# このファイルを OrificeCalc-2 と同じ階層に置いて実行してください
# 実行方法: 右クリック → "PowerShellで実行"
# ============================================================

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$repoDir = Join-Path $PSScriptRoot "OrificeCalc-2"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  OrificeCalc-2 git push" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# リポジトリ確認
if (-not (Test-Path "$repoDir\.git")) {
    Write-Host "[ERROR] リポジトリが見つかりません: $repoDir" -ForegroundColor Red
    Write-Host "このスクリプトを OrificeCalc-2 フォルダの親フォルダに置いてください"
    Read-Host "Enterで終了"
    exit 1
}

Set-Location $repoDir

# [1] 状態確認
Write-Host "[1/4] 現在の状態を確認中..." -ForegroundColor Yellow
git status --short
Write-Host ""

# [2] ステージング
Write-Host "[2/4] 変更をステージング中..." -ForegroundColor Yellow
git add -A
Write-Host ""

# [3] コミット
Write-Host "[3/4] コミット中..." -ForegroundColor Yellow
$staged = git diff --cached --name-only
if (-not $staged) {
    Write-Host "変更なし、コミットをスキップします" -ForegroundColor Gray
} else {
    git commit -m "ローカル変更をpush"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] コミット失敗" -ForegroundColor Red
        Read-Host "Enterで終了"
        exit 1
    }
}
Write-Host ""

# [4] push
Write-Host "[4/4] pushしています..." -ForegroundColor Yellow
git push origin main
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] push失敗" -ForegroundColor Red
    Write-Host "GitHub認証情報を確認してください"
    Read-Host "Enterで終了"
    exit 1
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  push完了！" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Read-Host "Enterで終了"
