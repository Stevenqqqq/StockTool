[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Installer,
    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9A-Fa-f]{64}$')]
    [string]$ExpectedSha256,
    [Parameter(Mandatory = $true)]
    [int]$ExpectedSize,
    [switch]$AllowInteractiveInstallerEvidence
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class StockToolInteractiveWindow {
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdcBlt, uint nFlags);
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int command);
    [DllImport("user32.dll")]
    public static extern bool BringWindowToTop(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern IntPtr SetActiveWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")]
    public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extra);
    [DllImport("user32.dll")]
    public static extern bool PostMessage(IntPtr hWnd, uint message, IntPtr wParam, IntPtr lParam);
}
"@

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToUpperInvariant()
}

function Write-Utf8Json([string]$Path, [object]$Value) {
    $json = $Value | ConvertTo-Json -Depth 20
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, ($json + "`n"), $utf8)
}

function Get-ProcessNames {
    return @(Get-Process -Name StockTool,StockToolPayload -ErrorAction SilentlyContinue |
        ForEach-Object { $_.ProcessName + '.exe' })
}

function Get-Listeners {
    $result = @()
    foreach ($line in (netstat -ano -p tcp 2>$null)) {
        $fields = $line -split '\s+'
        if ($fields.Count -ge 4 -and $fields[0].ToUpperInvariant() -eq 'TCP' -and
            $fields[3].ToUpperInvariant() -eq 'LISTENING') {
            $port = ($fields[1] -split ':')[-1]
            if ($port -in @('8501', '8502')) { $result += [int]$port }
        }
    }
    return @($result | Sort-Object -Unique)
}

function Get-UninstallPresent {
    $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{7ABF2B4C-4D79-4E74-B66C-9AF7E9E06568}_is1'
    return Test-Path -LiteralPath $key
}

function Get-Snapshot {
    return [ordered]@{
        captured_utc = [DateTime]::UtcNow.ToString('o')
        processes = @(Get-ProcessNames)
        listeners = @(Get-Listeners)
        default_install_exists = Test-Path -LiteralPath $script:DefaultInstallRoot
        uninstall_entry_present = Get-UninstallPresent
    }
}

function Get-TempCandidates {
    $tempRoot = [System.IO.Path]::GetFullPath($env:TEMP)
    $items = @{}
    foreach ($pattern in @('is-*.tmp', '_setup64.tmp', '_unins.tmp')) {
        foreach ($item in Get-ChildItem -LiteralPath $tempRoot -Filter $pattern -Force -ErrorAction SilentlyContinue) {
            $full = [System.IO.Path]::GetFullPath($item.FullName)
            $items[$full] = [ordered]@{
                path = $full
                is_directory = $item.PSIsContainer
                size_bytes = if ($item.PSIsContainer) { $null } else { [int64]$item.Length }
            }
        }
    }
    return $items
}

function Get-ProcessTree([int[]]$RootPids) {
    $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $known = New-Object 'System.Collections.Generic.HashSet[int]'
    foreach ($rootPidItem in $RootPids) { [void]$known.Add([int]$rootPidItem) }
    $changed = $true
    while ($changed) {
        $changed = $false
        foreach ($item in $all) {
            if ($known.Contains([int]$item.ParentProcessId) -and $known.Add([int]$item.ProcessId)) {
                $changed = $true
            }
        }
    }
    return @($all | Where-Object { $known.Contains([int]$_.ProcessId) } |
        Select-Object @{Name='pid';Expression={[int]$_.ProcessId}},
            @{Name='parent_pid';Expression={[int]$_.ParentProcessId}},
            @{Name='name';Expression={$_.Name}},
            @{Name='command_line';Expression={$_.CommandLine}})
}

function Get-LogCreatedTempPaths([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return @() }
    $paths = @()
    $lines = $null
    for ($attempt = 0; $attempt -lt 10 -and $null -eq $lines; $attempt++) {
        try {
            $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete)
            try {
                $reader = New-Object System.IO.StreamReader($stream)
                try { $lines = @($reader.ReadToEnd() -split "`r?`n") } finally { $reader.Dispose() }
            } finally { $stream.Dispose() }
        } catch [System.IO.IOException] {
            Start-Sleep -Milliseconds 200
        }
    }
    foreach ($line in @($lines)) {
        if ($line -match 'Created temporary directory:\s*(?<path>[^\r\n]+)$') {
            try { $paths += [System.IO.Path]::GetFullPath($Matches['path'].Trim()) } catch { }
        }
    }
    return @($paths | Sort-Object -Unique)
}

function Get-ProcessTreeTempPaths([object[]]$Tree) {
    $paths = @()
    foreach ($item in @($Tree)) {
        $commandLine = [string]$item.command_line
        foreach ($match in [regex]::Matches($commandLine, '(?i)([A-Z]:\\[^"\s]*?is-[^\\\s"]+\.tmp)')) {
            try { $paths += [System.IO.Path]::GetFullPath($match.Groups[1].Value) } catch { }
        }
    }
    return @($paths | Sort-Object -Unique)
}

function Test-OwnedTempPath([string]$Path, [System.Collections.IDictionary]$Ownership) {
    if ($null -eq $Ownership -or -not $Ownership.Contains($Path)) { return $false }
    $tempRoot = [System.IO.Path]::GetFullPath($env:TEMP).TrimEnd('\') + '\'
    $full = [System.IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase)) { return $false }
    $name = [System.IO.Path]::GetFileName($full)
    if ($name -notmatch '^is-[^\\/]+\.tmp$' -and $name -notmatch '^_(setup64|unins)\.tmp$') { return $false }
    $item = Get-Item -LiteralPath $full -Force -ErrorAction SilentlyContinue
    if ($null -ne $item -and $item.LinkType) { return $false }
    return $true
}

function Get-Window([int]$ProcessId) {
    $condition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ProcessIdProperty, $ProcessId)
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    return $root.FindFirst([System.Windows.Automation.TreeScope]::Subtree, $condition)
}

function Get-Names([System.Windows.Automation.AutomationElement]$Element) {
    $items = @()
    $all = $Element.FindAll(
        [System.Windows.Automation.TreeScope]::Descendants,
        [System.Windows.Automation.Condition]::TrueCondition)
    foreach ($item in $all) {
        $value = $null
        try {
            $pattern = $item.GetCurrentPattern(
                [System.Windows.Automation.ValuePattern]::Pattern)
            $value = $pattern.Current.Value
        } catch { }
        $items += [ordered]@{
            name = $item.Current.Name
            automation_id = $item.Current.AutomationId
            control_type = $item.Current.ControlType.ProgrammaticName
            value = $value
        }
    }
    return $items
}

function Find-Button([System.Windows.Automation.AutomationElement]$Element, [string[]]$Names) {
    $buttons = $Element.FindAll(
        [System.Windows.Automation.TreeScope]::Descendants,
        [System.Windows.Automation.Condition]::TrueCondition)
    foreach ($button in $buttons) {
        foreach ($name in $Names) {
            if ($button.Current.Name -like "*$name*") { return $button }
        }
    }
    return $null
}

function Find-ProcessNamedElement([int]$ProcessId, [string[]]$Names) {
    $condition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ProcessIdProperty, $ProcessId)
    $root = [System.Windows.Automation.AutomationElement]::RootElement.FindFirst(
        [System.Windows.Automation.TreeScope]::Subtree, $condition)
    if ($null -eq $root) { return $null }
    $all = $root.FindAll(
        [System.Windows.Automation.TreeScope]::Descendants,
        [System.Windows.Automation.Condition]::TrueCondition)
    foreach ($item in $all) {
        foreach ($name in $Names) {
            if ($item.Current.Name -like "*$name*") { return $item }
        }
    }
    return $null
}

function Invoke-Button([System.Windows.Automation.AutomationElement]$Button) {
    try {
        $invoke = $Button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
        $invoke.Invoke()
    } catch {
        if ($Button.Current.Name -match 'Cancel|取消') {
            [System.Windows.Forms.SendKeys]::SendWait('{ESC}')
        } else {
            [System.Windows.Forms.SendKeys]::SendWait('%n')
        }
    }
}

function Click-Element([System.Windows.Automation.AutomationElement]$Element, [IntPtr]$WindowHandle) {
    [StockToolInteractiveWindow]::ShowWindow($WindowHandle, 5) | Out-Null
    [StockToolInteractiveWindow]::BringWindowToTop($WindowHandle) | Out-Null
    [StockToolInteractiveWindow]::SetActiveWindow($WindowHandle) | Out-Null
    [StockToolInteractiveWindow]::SetForegroundWindow($WindowHandle) | Out-Null
    $rect = $Element.Current.BoundingRectangle
    $x = [int]($rect.X + ($rect.Width / 2))
    $y = [int]($rect.Y + ($rect.Height / 2))
    [StockToolInteractiveWindow]::SetCursorPos($x, $y) | Out-Null
    [StockToolInteractiveWindow]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
    [StockToolInteractiveWindow]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
}

if (-not $AllowInteractiveInstallerEvidence) {
    throw 'refusing interactive installer evidence without explicit opt-in'
}

$installerPath = [System.IO.Path]::GetFullPath($Installer)
$outputPath = [System.IO.Path]::GetFullPath($OutputRoot)
$workspaceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$artifactPrefix = [System.IO.Path]::GetFullPath((Join-Path $workspaceRoot 'artifacts\sprint30.2.1'))
if (-not $outputPath.StartsWith($artifactPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'interactive output must be inside artifacts/sprint30.2.1'
}
$script:DefaultInstallRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $env:LOCALAPPDATA 'Programs\StockTool'))
if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
    throw 'installer is not a regular file'
}
if ((Get-Item -LiteralPath $installerPath).LinkType) {
    throw 'installer must not be a reparse point'
}
if ((Get-Item -LiteralPath $installerPath).Length -ne $ExpectedSize) {
    throw 'installer size does not match expected hash binding'
}
$actualInstallerHash = Get-Sha256 $installerPath
if ($actualInstallerHash -ne $ExpectedSha256.ToUpperInvariant()) {
    throw 'installer SHA-256 does not match expected hash binding'
}
$before = Get-Snapshot
if ($before.processes.Count -ne 0 -or $before.listeners.Count -ne 0 -or
    $before.default_install_exists -or $before.uninstall_entry_present) {
    throw 'interactive installer preflight is not clean'
}

New-Item -ItemType Directory -Force -Path $outputPath | Out-Null
$sessionId = 'interactive-destination-' + ([Guid]::NewGuid().ToString('N').Substring(0, 16))
$logPath = Join-Path $outputPath 'installer-interactive.log'
$command = [ordered]@{
    session_id = $sessionId
    prepared_utc = [DateTime]::UtcNow.ToString('o')
    executable = $installerPath
    argv = @('/LOG=' + $logPath)
    installer_sha256 = $actualInstallerHash
    installer_size_bytes = $ExpectedSize
    mode = 'interactive-destination-only'
}
$process = $null
$ownedPids = @()
$uiProcess = $null
$tempBefore = Get-TempCandidates
$result = [ordered]@{
    schema_version = 1
    status = 'failed'
    session_id = $sessionId
    candidate_installer = [ordered]@{
        path = $installerPath
        size_bytes = $ExpectedSize
        sha256 = $actualInstallerHash
    }
    expected_default_path_template = '%LOCALAPPDATA%\\Programs\\StockTool'
    expected_default_path = $script:DefaultInstallRoot
    command = $command
    preflight = $before
    temp_manifest_before = $tempBefore
    ownership_ledger = [ordered]@{
        session_id = $sessionId
        pre_launch_manifest = $tempBefore
        process_roots = @()
        process_tree = @()
        owned_temp_paths = @{}
        cleanup_attempts = @()
    }
}
try {
    $launchUtc = [DateTime]::UtcNow
    $process = Start-Process -FilePath $installerPath -ArgumentList $command.argv -PassThru -WorkingDirectory (Split-Path $installerPath)
    $ownedPids += $process.Id
    $result.ownership_ledger.process_roots = @([int]$process.Id)
    $result.launch = [ordered]@{ started_utc = $launchUtc.ToString('o'); pid = $process.Id }
    $window = $null
    for ($i = 0; $i -lt 60 -and $null -eq $window; $i++) {
        Start-Sleep -Milliseconds 250
        $uiProcess = Get-Process -ErrorAction SilentlyContinue |
            Where-Object { $_.ProcessName -like ($process.Name + '*') -and $_.MainWindowHandle -ne 0 } |
            Select-Object -First 1
        if ($null -ne $uiProcess) {
            $ownedPids += $uiProcess.Id
            $result.ownership_ledger.process_roots = @($ownedPids | Select-Object -Unique | ForEach-Object {[int]$_})
            $window = Get-Window $uiProcess.Id
        }
    }
    if ($null -eq $window) { throw 'installer window was not discoverable' }
    $result.ownership_ledger.process_tree = @(Get-ProcessTree $ownedPids)
    $afterLaunch = Get-TempCandidates
    $result.ownership_ledger.temp_manifest_after_launch = $afterLaunch
    foreach ($path in @(Get-LogCreatedTempPaths $logPath)) {
        if (-not $tempBefore.ContainsKey($path)) {
            $result.ownership_ledger.owned_temp_paths[$path] = [ordered]@{
                path = $path
                ownership_basis = @('absent_pre_launch', 'installer_log_created_directory', 'session_process_tree_recorded')
            }
        }
    }
    $windowHandle = [IntPtr]$window.Current.NativeWindowHandle
    if ($windowHandle -eq [IntPtr]::Zero) { throw 'installer window has no native handle' }
    $destination = $null
    for ($i = 0; $i -lt 60 -and $null -eq $destination; $i++) {
        if ($i -gt 0) { Start-Sleep -Milliseconds 250 }
        $names = Get-Names $window
        if ($names | Where-Object { $_.name -match 'Destination Location|Select Destination|選擇目的地|安裝位置' }) {
            $destination = $names
        }
        if ($null -eq $destination -and $i -eq 0) {
            $next = Find-Button $window @('Next', '下一步')
            if ($null -eq $next) { throw 'installer Next button was not discoverable' }
            Invoke-Button $next
        }
    }
    if ($null -eq $destination) { throw 'Destination Location page was not discoverable' }
    $controlsPath = Join-Path $outputPath 'destination-ui-controls.json'
    Write-Utf8Json $controlsPath $destination
    $edit = $destination | Where-Object {
        (($_.value -and ([System.IO.Path]::GetFullPath($_.value) -ieq $script:DefaultInstallRoot)) -or
            $_.name -ieq $script:DefaultInstallRoot)
    } | Select-Object -First 1
    if ($null -eq $edit) { throw 'Destination path control did not equal expected default path' }
    $rect = $window.Current.BoundingRectangle
    if ($rect.Width -le 0 -or $rect.Height -le 0) { throw 'installer window has no visible bounds' }
    [StockToolInteractiveWindow]::ShowWindow($windowHandle, 5) | Out-Null
    [StockToolInteractiveWindow]::BringWindowToTop($windowHandle) | Out-Null
    [StockToolInteractiveWindow]::SetActiveWindow($windowHandle) | Out-Null
    [StockToolInteractiveWindow]::SetForegroundWindow($windowHandle) | Out-Null
    Start-Sleep -Milliseconds 300
    $bitmap = New-Object System.Drawing.Bitmap([int]$rect.Width, [int]$rect.Height)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $windowHdc = $graphics.GetHdc()
    try {
        $printed = [StockToolInteractiveWindow]::PrintWindow($windowHandle, $windowHdc, 0)
    } finally {
        $graphics.ReleaseHdc($windowHdc)
    }
    if (-not $printed) {
        $graphics.CopyFromScreen([int]$rect.X, [int]$rect.Y, 0, 0, $bitmap.Size)
    }
    $pngPath = Join-Path $outputPath 'destination.png'
    $bitmap.Save($pngPath, [System.Drawing.Imaging.ImageFormat]::Png)
    $graphics.Dispose(); $bitmap.Dispose()
    $result.destination = [ordered]@{
        observed_path = $edit.value
        expected_path = $script:DefaultInstallRoot
        path_matches = $true
        screenshot = [ordered]@{ path = 'destination.png'; size_bytes = (Get-Item $pngPath).Length; sha256 = (Get-Sha256 $pngPath) }
        ui_controls = 'destination-ui-controls.json'
    }
    $cancel = Find-Button $window @('Cancel', '取消')
    if ($null -eq $cancel) { throw 'installer Cancel button was not discoverable' }
    $cancelUtc = [DateTime]::UtcNow
    Invoke-Button $cancel
    if ($null -ne $uiProcess) {
        Click-Element $cancel $windowHandle
    }
    if ($null -ne $uiProcess) {
        for ($i = 0; $i -lt 20; $i++) {
            Start-Sleep -Milliseconds 250
            $confirm = Find-ProcessNamedElement $uiProcess.Id @('Yes', '是', '確定')
            if ($null -ne $confirm) {
                Invoke-Button $confirm
                Click-Element $confirm $windowHandle
                break
            }
        }
    }
    Start-Sleep -Milliseconds 500
    $uiExited = $true
    if ($null -ne $uiProcess) {
        $uiProcess.Refresh()
        $uiExited = $uiProcess.HasExited
    }
    $process.Refresh()
    if (-not $uiExited -or -not $process.HasExited) {
        if ($null -ne $uiProcess) {
            [StockToolInteractiveWindow]::SetForegroundWindow($windowHandle) | Out-Null
        }
        [System.Windows.Forms.SendKeys]::SendWait('%c')
        [System.Windows.Forms.SendKeys]::SendWait('{ESC}')
        [System.Windows.Forms.SendKeys]::SendWait('%{F4}')
        if ($null -ne $uiProcess -and -not $uiProcess.HasExited) {
            $uiProcess.WaitForExit(15000)
        }
    }
    if ($null -ne $uiProcess) { $uiProcess.Refresh() }
    $uiExited = ($null -eq $uiProcess -or $uiProcess.HasExited)
    $cancelMethod = 'invoke-and-mouse'
    if (-not $uiExited -and $null -ne $uiProcess) {
        $uiProcess.CloseMainWindow() | Out-Null
        $uiProcess.WaitForExit(5000)
        $uiProcess.Refresh()
        $uiExited = $uiProcess.HasExited
        $cancelMethod = 'invoke-mouse-close-main-window'
    }
    if (-not $uiExited -and $null -ne $uiProcess) {
        [StockToolInteractiveWindow]::PostMessage($windowHandle, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
        $uiProcess.WaitForExit(5000)
        $uiProcess.Refresh()
        $uiExited = $uiProcess.HasExited
        $cancelMethod = 'invoke-mouse-wm_close-fallback'
    }
    if (-not $uiExited) { throw 'installer UI did not exit after Cancel' }
    $process.Refresh()
    $result.cancel = [ordered]@{
        clicked_utc = $cancelUtc.ToString('o')
        exit_code = if ($process.HasExited) { $process.ExitCode } else { $null }
        ui_exit_observed = $uiExited
        method = $cancelMethod
    }
    if ($null -ne $uiProcess) { $result.launch.ui_pid = $uiProcess.Id }
    $result.status = 'passed'
} finally {
    $cleanupErrors = @()
    $result.ownership_ledger.process_tree_before_cleanup = @(Get-ProcessTree $ownedPids)
    $processEvidence = @($result.ownership_ledger.process_tree) + @($result.ownership_ledger.process_tree_before_cleanup)
    foreach ($path in @(Get-ProcessTreeTempPaths $processEvidence)) {
        if (-not $tempBefore.ContainsKey($path) -and -not $result.ownership_ledger.owned_temp_paths.Contains($path)) {
            $result.ownership_ledger.owned_temp_paths[$path] = [ordered]@{
                path = $path
                ownership_basis = @('absent_pre_launch', 'session_process_tree_recorded')
            }
        }
    }
    foreach ($ownedPid in @($ownedPids | Select-Object -Unique)) {
        try {
            cmd.exe /d /c "taskkill /PID $ownedPid /T /F >nul 2>&1" | Out-Null
            $result.ownership_ledger.cleanup_attempts += [ordered]@{ type = 'process_tree'; root_pid = [int]$ownedPid; result = 'requested' }
        } catch {
            $cleanupErrors += "process cleanup failed for PID $ownedPid"
        }
    }
    $result.ownership_ledger.process_tree_after_cleanup = @(Get-ProcessTree $ownedPids)
    $tempAfter = Get-TempCandidates
    $logPaths = @(Get-LogCreatedTempPaths $logPath)
    foreach ($path in $logPaths) {
        if (-not $tempBefore.ContainsKey($path) -and -not $result.ownership_ledger.owned_temp_paths.Contains($path)) {
            $result.ownership_ledger.owned_temp_paths[$path] = [ordered]@{
                path = $path
                ownership_basis = @('absent_pre_launch', 'installer_log_created_directory', 'session_process_tree_recorded')
            }
        }
    }
    $removedTemp = @()
    foreach ($path in @($result.ownership_ledger.owned_temp_paths.Keys | Sort-Object)) {
        if (-not (Test-OwnedTempPath $path $result.ownership_ledger.owned_temp_paths)) {
            $cleanupErrors += "ownership validation failed for $path"
            continue
        }
        if (-not (Test-Path -LiteralPath $path)) {
            $result.ownership_ledger.cleanup_attempts += [ordered]@{ type = 'temp'; path = $path; result = 'already_absent' }
            continue
        }
        try {
            Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction Stop
            if (Test-Path -LiteralPath $path) { $cleanupErrors += "owned temp remained after removal: $path" }
            else { $removedTemp += $path; $result.ownership_ledger.cleanup_attempts += [ordered]@{ type = 'temp'; path = $path; result = 'removed' } }
        } catch {
            $cleanupErrors += "owned temp removal failed: $path"
        }
    }
    $result.temp_manifest_after = Get-TempCandidates
    $result.temp_cleanup = [ordered]@{
        owned_candidates = @($result.ownership_ledger.owned_temp_paths.Keys | Sort-Object)
        removed_candidates = @($removedTemp | Sort-Object)
        unowned_candidates_left = @($result.temp_manifest_after.Keys | Where-Object { -not $result.ownership_ledger.owned_temp_paths.Contains($_) } | Sort-Object)
    }
    $result.cleanup = Get-Snapshot
    $result.cleanup_errors = @($cleanupErrors)
    $result.cleanup_verified = ($cleanupErrors.Count -eq 0 -and
        $result.cleanup.processes.Count -eq 0 -and
        $result.cleanup.listeners.Count -eq 0 -and
        -not $result.cleanup.default_install_exists -and
        -not $result.cleanup.uninstall_entry_present -and
        @($result.temp_cleanup.owned_candidates | Where-Object { Test-Path -LiteralPath $_ }).Count -eq 0)
    if ($result.status -eq 'passed' -and -not $result.cleanup_verified) {
        $result.status = 'failed'
    }
    Write-Utf8Json (Join-Path $outputPath 'ownership-ledger.json') $result.ownership_ledger
    Write-Utf8Json (Join-Path $outputPath 'interactive-result.json') $result
}

if ($result.status -ne 'passed') { exit 1 }
exit 0
