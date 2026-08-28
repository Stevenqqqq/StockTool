[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$LedgerPath,
    [Parameter(Mandatory = $true)]
    [string]$OutputPath,
    # Explicit test-only seam; production uses the live process query by default.
    [ValidateSet('system', 'test-related-process', 'test-none')]
    [string]$ProcessDetectionMode = 'system'
)

$ErrorActionPreference = 'Stop'

function Get-Snapshot {
    $tempRoot = [System.IO.Path]::GetFullPath($env:TEMP)
    $items = @{}
    foreach ($candidate in Get-ChildItem -LiteralPath $tempRoot -Force -ErrorAction SilentlyContinue) {
        if (-not ($candidate.Name.StartsWith('is-') -and $candidate.Name.EndsWith('.tmp'))) { continue }
        $full = [System.IO.Path]::GetFullPath($candidate.FullName)
        $items[$full] = [ordered]@{
            path = $full
            is_directory = $candidate.PSIsContainer
            size_bytes = if ($candidate.PSIsContainer) { $null } else { [int64]$candidate.Length }
        }
    }
    return $items
}

function Write-Utf8Json([string]$Path, [object]$Value) {
    $json = $Value | ConvertTo-Json -Depth 30
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, ($json + "`n"), $utf8)
}

function Get-RelatedProcesses([string]$Mode) {
    if ($Mode -eq 'test-related-process') {
        return @([pscustomobject]@{ Name = 'StockTool.exe'; ProcessId = 4242 })
    }
    if ($Mode -eq 'test-none') {
        return @()
    }
    return @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match 'StockTool|StockToolPayload|StockTool-Setup' })
}

$ledger = Get-Content -LiteralPath $LedgerPath -Raw | ConvertFrom-Json
$tempRoot = [System.IO.Path]::GetFullPath($env:TEMP).TrimEnd('\') + '\'
$before = Get-Snapshot
$owned = @($ledger.owned_residuals | Where-Object { $_.status -eq 'owned' } | ForEach-Object { $_.path })
$removed = @()
$errors = @()
$processes = @(Get-RelatedProcesses $ProcessDetectionMode)
if ($processes.Count -gt 0) {
    # Fail closed before the first Remove-Item. Existing owned bytes are never touched.
    $errors += 'related installer or StockTool process exists'
}

if ($processes.Count -eq 0) {
foreach ($rawPath in $owned) {
    try {
        $full = [System.IO.Path]::GetFullPath([string]$rawPath)
        if (-not $full.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw 'target escapes TEMP'
        }
        $name = [System.IO.Path]::GetFileName($full)
        if (-not ($name.StartsWith('is-') -and $name.EndsWith('.tmp'))) {
            throw 'target is not an is-*.tmp directory'
        }
        $item = Get-Item -LiteralPath $full -Force -ErrorAction SilentlyContinue
        if ($null -ne $item -and $item.LinkType) { throw 'target is a reparse point' }
        if (Test-Path -LiteralPath $full) {
            Remove-Item -LiteralPath $full -Recurse -Force -ErrorAction Stop
            if (Test-Path -LiteralPath $full) { throw 'target remained after removal' }
            $removed += $full
        }
    } catch {
        $errors += "${rawPath}: $($_.Exception.Message)"
    }
}
}

$after = Get-Snapshot
$remainingOwned = @($owned | Where-Object { Test-Path -LiteralPath $_ })
$result = [ordered]@{
    schema_version = 1
    ledger_path = [System.IO.Path]::GetFullPath($LedgerPath)
    captured_before_utc = [DateTime]::UtcNow.ToString('o')
    owned_targets = $owned
    before = $before
    removed = $removed
    after = $after
    remaining_owned = $remainingOwned
    errors = $errors
    passed = ($errors.Count -eq 0 -and $remainingOwned.Count -eq 0)
}
Write-Utf8Json $OutputPath $result
if (-not $result.passed) { exit 1 }
exit 0
