# Run ONLY inside a fresh disposable Windows Sandbox/VM, never on the development host.
[CmdletBinding()]
param([string]$InputRoot = 'C:\StockToolInput', [string]$OutputRoot = 'C:\StockToolEvidence', [switch]$ReviewBeforeUninstall)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$manifest = Get-Content -LiteralPath (Join-Path $InputRoot 'delivery.json') -Raw | ConvertFrom-Json
$machine = Get-CimInstance Win32_ComputerSystem
if ($env:COMPUTERNAME -eq $manifest.prohibited_host -or
    ($env:USERNAME -ne 'WDAGUtilityAccount' -and $machine.Model -notmatch 'Virtual|VMware|KVM|QEMU')) {
    throw 'Refusing lifecycle execution outside a disposable Windows Sandbox/VM.'
}
$program = Join-Path $env:LOCALAPPDATA 'Programs\StockTool'
$data = Join-Path $env:LOCALAPPDATA 'StockTool'
$uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{7ABF2B4C-4D79-4E74-B66C-9AF7E9E06568}_is1'
$desktop = Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) '股票分析工具.lnk'
$startLink = Join-Path ([Environment]::GetFolderPath('Programs')) 'StockTool.lnk'
foreach ($path in @($program,$data,$uninstallKey,$desktop,$startLink)) {
    if (Test-Path -LiteralPath $path) { throw "Fresh guest required; existing state at $path" }
}
if ($env:STOCK_TOOL_USER_DATA_DIR) { throw 'Guest must use default per-user data path.' }
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
$events = [System.Collections.Generic.List[object]]::new()
$result = [ordered]@{status='running'; version='1.4.3'; events=$events; ui_content_verified=$false}
function Hash([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash }
function Event([string]$Name, $Details) { $events.Add([ordered]@{name=$Name;utc=[DateTime]::UtcNow.ToString('o');details=$Details}) }
function Check-Artifact([string]$Name, [string]$Expected) {
    $path = Join-Path $InputRoot $Name
    if ((Hash $path) -ne $Expected) { throw "Artifact hash mismatch: $Name" }
    return $path
}
function Install([string]$Exe, [string]$Label) {
    $log = Join-Path $OutputRoot "$Label.log"
    $p = Start-Process -FilePath $Exe -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',"/LOG=`"$log`"") -WindowStyle Hidden -Wait -PassThru
    Event $Label @{exit_code=$p.ExitCode}
    if ($p.ExitCode -ne 0) { throw "$Label failed" }
}
function Stop-Owned {
    Get-Process -Name StockTool,StockToolPayload -ErrorAction SilentlyContinue | Where-Object {
        $_.Path -and $_.Path.StartsWith($program+'\',[StringComparison]::OrdinalIgnoreCase)
    } | Stop-Process -Force
}
function Check-Version([string]$Expected) {
    $reported = (& (Join-Path $program 'StockTool.exe') --version | Out-String).Trim()
    $authority = Get-Content (Join-Path $program 'current-version.json') -Raw | ConvertFrom-Json
    if ($reported -ne $Expected -or $authority.version -ne $Expected) { throw 'Version authority mismatch' }
    Event 'version' @{reported=$reported;authority=$authority}
}
function Check-Links {
    $shell = New-Object -ComObject WScript.Shell
    foreach ($path in @($desktop,$startLink)) {
        if (-not (Test-Path -LiteralPath $path)) { throw "Missing shortcut: $path" }
        $link = $shell.CreateShortcut($path)
        if ($link.TargetPath -ne (Join-Path $program 'StockTool.exe') -or $link.Arguments -ne '' -or $link.WorkingDirectory -ne $program) { throw "Incorrect shortcut: $path" }
        Event 'shortcut' @{path=$path;target=$link.TargetPath;working_directory=$link.WorkingDirectory}
    }
}
$seedHashes = @{}
function Check-Data([string]$Label) {
    foreach ($relative in $seedHashes.Keys) {
        if ((Hash (Join-Path $data $relative)) -ne $seedHashes[$relative]) { throw "Seed changed: $relative" }
    }
    $cipher = Get-Content (Join-Path $data 'secrets\groq-key.dpapi') -Raw
    $secure = ConvertTo-SecureString $cipher
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        if ([Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) -ne 'SYNTHETIC-NOT-A-REAL-GROQ-KEY') { throw 'DPAPI preservation failed' }
    } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
    Event $Label @{protected_file_count=$seedHashes.Count;changed=0;dummy_dpapi_readable=$true}
}
function Launch-Link([string]$Path, [string]$Label) {
    if (@(Get-NetTCPConnection -State Listen -LocalPort 8501,8502 -ErrorAction SilentlyContinue).Count) { throw 'Ports already occupied before launch' }
    $env:STOCK_TOOL_NO_BROWSER='1'
    Start-Process -FilePath $Path -WindowStyle Hidden
    try {
        $ok=$false; $deadline=[DateTime]::UtcNow.AddSeconds(60)
        while ([DateTime]::UtcNow -lt $deadline) {
            try {
                $r=Invoke-WebRequest 'http://127.0.0.1:8501/_stcore/health' -UseBasicParsing -TimeoutSec 2
                if ($r.StatusCode -eq 200 -and $r.Content.Trim() -eq 'ok') {$ok=$true;break}
            } catch {}
            Start-Sleep -Milliseconds 500
        }
        if (-not $ok) { throw 'Stable entry did not become healthy' }
        $expected = Join-Path $program 'versions\1.4.3\StockToolPayload.exe'
        $owned = @(Get-Process -Name StockToolPayload -ErrorAction SilentlyContinue | Where-Object {$_.Path -eq $expected})
        if ($owned.Count -eq 0) { throw 'Shortcut did not launch the new payload' }
        Event $Label @{health='200/ok';payload=$expected;process_count=$owned.Count}
    } finally { Stop-Owned }
    Start-Sleep -Seconds 2
    if (@(Get-NetTCPConnection -State Listen -LocalPort 8501,8502 -ErrorAction SilentlyContinue).Count) { throw 'Listener survived process cleanup' }
    Check-Data "$Label-data"
}
try {
    $old = Check-Artifact 'baseline-1.4.2.exe' $manifest.baseline_sha256
    $new = Check-Artifact 'StockTool-Setup-1.4.3-internal-test.exe' $manifest.installer_sha256
    foreach ($fixture in $manifest.fixture_hashes.PSObject.Properties) {
        [void](Check-Artifact $fixture.Name $fixture.Value)
    }
    Install $old 'install-baseline'
    Check-Version '1.4.2'
    New-Item -ItemType Directory -Path $data -Force | Out-Null
    Copy-Item -Path (Join-Path $InputRoot 'fixtures\*') -Destination $data -Recurse
    New-Item -ItemType Directory -Path (Join-Path $data 'secrets') -Force | Out-Null
    ConvertTo-SecureString 'SYNTHETIC-NOT-A-REAL-GROQ-KEY' -AsPlainText -Force | ConvertFrom-SecureString | Set-Content (Join-Path $data 'secrets\groq-key.dpapi') -Encoding UTF8
    Get-ChildItem -LiteralPath $data -Recurse -File | ForEach-Object {
        $seedHashes[$_.FullName.Substring($data.Length+1)] = Hash $_.FullName
    }
    # Reproduce the existing preview shortcut without accessing any host preview.
    $shell = New-Object -ComObject WScript.Shell
    $link=$shell.CreateShortcut($desktop)
    $link.TargetPath=Join-Path $env:LOCALAPPDATA 'StockToolCandidates\company-depth-preview\LaunchPreview.vbs'
    $link.Save()
    Install $new 'upgrade-v143'
    Check-Version '1.4.3'
    if ((Hash (Join-Path $program 'StockTool.exe')) -ne $manifest.stable_exe_sha256 -or
        (Hash (Join-Path $program 'versions\1.4.3\StockToolPayload.exe')) -ne $manifest.payload_exe_sha256) { throw 'Installed binary mismatch' }
    $installedPayload = Join-Path $program 'versions\1.4.3'
    $expectedFiles = @($manifest.payload_hashes.PSObject.Properties)
    if (@(Get-ChildItem -LiteralPath $installedPayload -Recurse -File).Count -ne $expectedFiles.Count) { throw 'Installed payload file count mismatch' }
    foreach ($entry in $expectedFiles) {
        if ((Hash (Join-Path $installedPayload $entry.Name)) -ne $entry.Value) { throw "Installed payload hash mismatch: $($entry.Name)" }
    }
    Event 'installed-payload-integrity' @{files=$expectedFiles.Count; changed=0}
    Check-Links
    Check-Data 'after-upgrade'
    Launch-Link $desktop 'desktop-first-launch'
    Launch-Link $startLink 'start-menu-restart'
    if ($ReviewBeforeUninstall) {
        Write-Host 'Guest-only review: open the installed desktop shortcut and inspect the synthetic portfolio/research. Record UI evidence separately.'
        if ((Read-Host 'Type CONTINUE to stop the guest app and verify uninstall') -ne 'CONTINUE') { throw 'Manual guest review did not continue to uninstall' }
        Stop-Owned
        Check-Data 'after-manual-review'
    }
    Install (Join-Path $program 'unins000.exe') 'uninstall-v143'
    foreach ($path in @((Join-Path $program 'StockTool.exe'),(Join-Path $program 'versions'),(Join-Path $program 'current-version.json'),$desktop,$startLink,$uninstallKey)) {
        if (Test-Path -LiteralPath $path) { throw "Uninstall left product artifact: $path" }
    }
    Check-Data 'after-uninstall'
    $result.status='passed'
} catch {
    $result.status='failed'; $result['error']=$_.Exception.Message
} finally {
    Stop-Owned
    $result | ConvertTo-Json -Depth 12 | Set-Content (Join-Path $OutputRoot 'lifecycle-result.json') -Encoding UTF8
}
if ($result.status -ne 'passed') { exit 1 }
