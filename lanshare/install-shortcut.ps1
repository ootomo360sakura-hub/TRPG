<#
    デスクトップに「LANファイル共有」のショートカットを作成する。

    使い方:
      install-shortcut.bat をダブルクリック(推奨)
      または PowerShell から:  .\install-shortcut.ps1
      削除するとき:            .\install-shortcut.ps1 -Remove

    作成されるショートカットは lanshare\start-server.bat を起動する。
    ダブルクリックするとサーバが立ち上がり、QRコード付きのセットアップ画面が開く。
#>
[CmdletBinding()]
param(
    [switch]$Remove,
    [string]$Name = 'LANファイル共有'
)

$ErrorActionPreference = 'Stop'

$here    = $PSScriptRoot
$repo    = Split-Path -Parent $here
$target  = Join-Path $here 'start-server.bat'
$icon    = Join-Path $here 'assets\lanshare.ico'
$desktop = [Environment]::GetFolderPath('Desktop')

if ([string]::IsNullOrWhiteSpace($desktop)) {
    throw 'デスクトップのフォルダが見つかりませんでした。'
}
$link = Join-Path $desktop ($Name + '.lnk')

# --- 削除 ---
if ($Remove) {
    if (-not (Test-Path -LiteralPath $link)) {
        Write-Host "ショートカットは見つかりませんでした: $link"
        return
    }
    Write-Host ''
    Write-Host 'この操作でPC上の次のファイルを削除します。'
    Write-Host "  $link"
    Write-Host '削除されるのはデスクトップのショートカットだけです。'
    Write-Host '共有フォルダの中身やアプリ本体は消えません。'
    $answer = Read-Host '削除しますか? (y/N)'
    if ($answer -notmatch '^[yY]') {
        Write-Host '中止しました。何も削除していません。'
        return
    }
    Remove-Item -LiteralPath $link -Force
    Write-Host 'ショートカットを削除しました。'
    return
}

# --- 作成 ---
if (-not (Test-Path -LiteralPath $target)) {
    throw "起動用スクリプトが見つかりません: $target"
}

# 既存のショートカットは上書きせず、日時つきでバックアップしてから作り直す
if (Test-Path -LiteralPath $link) {
    $backupDir = Join-Path $here '_shortcut-backup'
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    $stamp  = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backup = Join-Path $backupDir ('{0}.{1}.lnk' -f $Name, $stamp)
    Copy-Item -LiteralPath $link -Destination $backup -Force
    Write-Host "既存のショートカットをバックアップしました: $backup"
}

$shell = New-Object -ComObject WScript.Shell
try {
    $shortcut = $shell.CreateShortcut($link)
    $shortcut.TargetPath       = $target
    $shortcut.WorkingDirectory = $repo
    $shortcut.Description      = 'LAN内でWindows PCとiPhoneのファイルをやり取りする'
    $shortcut.WindowStyle      = 1
    if (Test-Path -LiteralPath $icon) {
        $shortcut.IconLocation = "$icon,0"
    }
    $shortcut.Save()
}
finally {
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($shell)
}

Write-Host ''
Write-Host 'デスクトップにショートカットを作成しました。'
Write-Host "  ショートカット : $link"
Write-Host "  起動するもの   : $target"
Write-Host "  作業フォルダ   : $repo"
Write-Host ''
Write-Host 'ダブルクリックするとサーバが起動し、QRコードのセットアップ画面が開きます。'
Write-Host 'iPhoneでQRを読み取ると、PCの画面は自動でファイル転送画面に切り替わります。'
Write-Host ''
Write-Host '削除するときは remove-shortcut.bat を実行してください。'
