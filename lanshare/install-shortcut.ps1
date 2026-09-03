<#
    デスクトップにショートカットを2つ作成する。

      1. 「LANファイル共有」(.lnk)      … サーバを起動する(start-server.bat)
      2. 「LANファイル共有を開く」(.url) … このPCのIPアドレス入りURLをブラウザで開く
                                            例: http://192.168.1.23:8765/

    使い方:
      install-shortcut.bat をダブルクリック(推奨)
      PowerShellから:   .\install-shortcut.ps1
      ポートを変える:   .\install-shortcut.ps1 -Port 8080
      IPを指定する:     .\install-shortcut.ps1 -Address 192.168.1.23
      削除する:         .\install-shortcut.ps1 -Remove

    IPアドレスは実行した時点のものを埋め込む。ルーターからの割り当てが変わったときは
    もう一度実行すれば URL が更新される(古いショートカットは日時つきで退避する)。
#>
[CmdletBinding()]
param(
    [switch]$Remove,
    [string]$Name = 'LANファイル共有',
    [string]$UrlName = 'LANファイル共有を開く',
    [int]$Port = 8765,
    [string]$Address
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
$link    = Join-Path $desktop ($Name + '.lnk')
$urlLink = Join-Path $desktop ($UrlName + '.url')

function Get-LanAddress {
    <# LAN側のIPv4アドレスを、既定ゲートウェイを持つ接続を優先して列挙する #>
    $found = @()
    try {
        $configs = Get-NetIPConfiguration -ErrorAction Stop |
            Where-Object { $_.IPv4Address -and $_.IPv4DefaultGateway } |
            Sort-Object { $_.IPv4DefaultGateway.RouteMetric }
        foreach ($config in $configs) {
            foreach ($entry in @($config.IPv4Address)) { $found += $entry.IPAddress }
        }
    } catch {
        # Get-NetIPConfiguration が使えない環境は下のDNS経由で拾う
    }
    try {
        $host4 = [System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName())
        foreach ($entry in $host4) {
            if ($entry.AddressFamily -eq 'InterNetwork') { $found += $entry.IPAddressToString }
        }
    } catch {
    }
    $found |
        Where-Object { $_ -and -not $_.StartsWith('127.') -and -not $_.StartsWith('169.254.') } |
        Select-Object -Unique
}

function Backup-Existing {
    <# 既存のショートカットを上書きせず、日時つきで退避してから作り直す #>
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $backupDir = Join-Path $here '_shortcut-backup'
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    $item   = Get-Item -LiteralPath $Path
    $stamp  = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backup = Join-Path $backupDir ('{0}.{1}{2}' -f $item.BaseName, $stamp, $item.Extension)
    Copy-Item -LiteralPath $Path -Destination $backup -Force
    Write-Host "既存のショートカットをバックアップしました: $backup"
}

# --- 削除 ---
if ($Remove) {
    $targets = @($link, $urlLink) | Where-Object { Test-Path -LiteralPath $_ }
    if ($targets.Count -eq 0) {
        Write-Host 'デスクトップにショートカットは見つかりませんでした。'
        return
    }
    Write-Host ''
    Write-Host 'この操作でPC上の次のファイルを削除します。'
    $targets | ForEach-Object { Write-Host "  $_" }
    Write-Host '削除されるのはデスクトップのショートカットだけです。'
    Write-Host '共有フォルダの中身やアプリ本体は消えません。'
    $answer = Read-Host '削除しますか? (y/N)'
    if ($answer -notmatch '^[yY]') {
        Write-Host '中止しました。何も削除していません。'
        return
    }
    foreach ($item in $targets) {
        Remove-Item -LiteralPath $item -Force
        Write-Host "削除しました: $item"
    }
    return
}

# --- 作成 ---
if (-not (Test-Path -LiteralPath $target)) {
    throw "起動用スクリプトが見つかりません: $target"
}

# 1. サーバ起動用のショートカット
Backup-Existing -Path $link
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

# 2. このPCのIPアドレス入りURLのショートカット
$addresses = @(Get-LanAddress)
$reachable = $true
if ($Address) {
    $primary = $Address
} elseif ($addresses.Count -gt 0) {
    $primary = $addresses[0]
} else {
    $primary = '127.0.0.1'
    $reachable = $false
    Write-Warning 'LAN側のIPアドレスを判定できませんでした。127.0.0.1 を使います。'
    Write-Warning 'Wi-Fiに接続してから実行し直すか、-Address 192.168.x.x で指定してください。'
}
$url = 'http://{0}:{1}/' -f $primary, $Port

# .url ファイルはANSIとして読まれるため、非ASCIIのパスは短い名前(8.3形式)に置き換える
$iconPath = $icon
if ($iconPath -match '[^\x00-\x7F]') {
    try {
        $fso = New-Object -ComObject Scripting.FileSystemObject
        $iconPath = $fso.GetFile($icon).ShortPath
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($fso)
    } catch {
        $iconPath = $null
    }
}
$lines = @('[InternetShortcut]', "URL=$url")
if ($iconPath -and (Test-Path -LiteralPath $icon) -and ($iconPath -notmatch '[^\x00-\x7F]')) {
    $lines += "IconFile=$iconPath"
    $lines += 'IconIndex=0'
}
Backup-Existing -Path $urlLink
Set-Content -LiteralPath $urlLink -Value $lines -Encoding ASCII

Write-Host ''
Write-Host 'デスクトップにショートカットを作成しました。'
Write-Host ''
Write-Host "  [1] $link"
Write-Host "      → サーバを起動する($target)"
Write-Host "  [2] $urlLink"
Write-Host "      → $url をブラウザで開く"
Write-Host ''
if ($addresses.Count -gt 1) {
    Write-Host ('このPCで見つかったIPアドレス: ' + ($addresses -join ', '))
    Write-Host '別のアドレスを使う場合は -Address で指定して実行し直してください。'
    Write-Host ''
}
if ($reachable) {
    Write-Host "iPhoneのSafariに入力するURLも同じ $url です。"
} else {
    Write-Host '127.0.0.1 はこのPC専用のアドレスで、iPhoneからは開けません。'
    Write-Host 'Wi-Fiに接続してから install-shortcut.bat を実行し直してください。'
}
Write-Host 'まず [1] でサーバを起動し、そのあとに [2] を開いてください。'
Write-Host 'IPアドレスが変わったときは install-shortcut.bat を実行し直すとURLが更新されます。'
Write-Host ''
Write-Host '削除するときは remove-shortcut.bat を実行してください。'
