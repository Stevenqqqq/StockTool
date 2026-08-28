[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$CurrentInstaller,
    [Parameter(Mandatory = $true)][string]$CurrentManifest,
    [Parameter(Mandatory = $true)][string]$RollbackInstaller,
    [Parameter(Mandatory = $true)][string]$CurrentStaging,
    [Parameter(Mandatory = $true)][string]$IsccPath,
    [switch]$AllowHostLifecycleTest,
    [ValidatePattern('^sprint19(?:\.1(?:\.1(?:\.2(?:\.1(?:\.1)?)?)?)?)?$')][string]$CandidateRootName = "sprint19.1",
    [string]$LifecycleRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$AppId = "{7ABF2B4C-4D79-4E74-B66C-9AF7E9E06568}"
$UninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\${AppId}_is1"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$CurrentArtifactRoot = Join-Path $ProjectRoot (Join-Path "artifacts" $CandidateRootName)
$RollbackArtifactRoot = Join-Path $ProjectRoot "artifacts\sprint18.2.2"
$CurrentStagingRoot = Join-Path $ProjectRoot (Join-Path "release" "staging-$CandidateRootName\StockTool")
if ([string]::IsNullOrWhiteSpace($LifecycleRoot)) {
    $LifecycleRoot = Join-Path $CurrentArtifactRoot "lifecycle"
}
$LifecycleRoot = [IO.Path]::GetFullPath($LifecycleRoot)
$Events = [System.Collections.Generic.List[object]]::new()
$Result = [ordered]@{ schema_version = 3; started_utc = [DateTime]::UtcNow.ToString("o"); status = "not-started"; artifacts = @{}; commands = $Events; snapshots = @(); cleanup = @{} }
$OriginalNoBrowser = $env:STOCK_TOOL_NO_BROWSER
$OriginalUserData = $env:STOCK_TOOL_USER_DATA_DIR
$Owned = $false
$Failure = $null
$Program = $null
$Sentinel = $null

function Test-WithinRoot([string]$Path, [string]$Root) {
    $candidate = [IO.Path]::GetFullPath($Path)
    $base = [IO.Path]::GetFullPath($Root).TrimEnd([IO.Path]::DirectorySeparatorChar)
    return $candidate.Equals($base, [StringComparison]::OrdinalIgnoreCase) -or $candidate.StartsWith($base + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
}
function Add-Event([string]$Name, [hashtable]$Data = @{}) { $Events.Add([ordered]@{ name=$Name; at_utc=[DateTime]::UtcNow.ToString("o"); data=$Data }) }
function Get-Sha256([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToUpperInvariant() }
function Get-ArtifactMetadata([string]$Path) { [ordered]@{ path=[IO.Path]::GetFullPath($Path); size_bytes=[int64](Get-Item -LiteralPath $Path).Length; sha256=Get-Sha256 $Path } }
function Read-AuthorityJson([string]$Path) { [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8) }
function Get-StockToolProcesses { @(Get-Process -Name StockTool -ErrorAction SilentlyContinue) }
function Get-Listeners { @(Get-NetTCPConnection -State Listen -LocalPort 8501,8502 -ErrorAction SilentlyContinue) }
function Assert-Preflight {
    if (-not $AllowHostLifecycleTest) { throw "Refusing host lifecycle execution without -AllowHostLifecycleTest." }
    if (-not (Test-WithinRoot $LifecycleRoot $CurrentArtifactRoot)) { throw "LifecycleRoot must be inside the selected candidate artifact root." }
    foreach ($item in $CurrentInstaller, $CurrentManifest, $RollbackInstaller, $CurrentStaging, $IsccPath) { if (-not (Test-Path -LiteralPath $item)) { throw "Required lifecycle input is missing: $item" } }
    if (-not (Test-WithinRoot $CurrentInstaller $CurrentArtifactRoot)) { throw "Current installer must be an isolated selected-candidate artifact." }
    if (-not (Test-WithinRoot $CurrentManifest $CurrentArtifactRoot)) { throw "Current manifest must be an isolated selected-candidate artifact." }
    if (-not (Test-WithinRoot $RollbackInstaller $RollbackArtifactRoot)) { throw "Rollback installer must be the preserved Sprint 18.2.2 rollback artifact." }
    if (-not (Test-WithinRoot $CurrentStaging $CurrentStagingRoot)) { throw "Current staging must be the isolated selected-candidate staging layout." }
    if (Test-Path -LiteralPath $UninstallKey) { throw "Fixed AppId already has an uninstall entry." }
    if (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA "Programs\StockTool")) { throw "Default StockTool install directory exists." }
    if (@(Get-StockToolProcesses).Count -ne 0 -or @(Get-Listeners).Count -ne 0) { throw "StockTool process or 8501/8502 listener is active." }
}
function Invoke-Inno([string]$Name, [string]$Executable, [string[]]$Arguments, [string]$LogPath, [switch]$ExpectFailure) {
    $started = [DateTime]::UtcNow
    $process = Start-Process -FilePath $Executable -ArgumentList @($Arguments + "/LOG=$LogPath") -Wait -PassThru
    Add-Event $Name @{ command=@($Executable)+$Arguments+"/LOG=$LogPath"; exit_code=$process.ExitCode; started_utc=$started.ToString("o"); completed_utc=[DateTime]::UtcNow.ToString("o"); log=$LogPath }
    if ($ExpectFailure) { if ($process.ExitCode -eq 0) { throw "$Name unexpectedly succeeded." }; return }
    if ($process.ExitCode -ne 0) { throw "$Name failed with exit code $($process.ExitCode)." }
}
function Assert-StableVersion([string]$ProgramRoot, [string]$ExpectedVersion) {
    $stable = Join-Path $ProgramRoot "StockTool.exe"
    if (-not (Test-Path -LiteralPath $stable -PathType Leaf)) { throw "Stable entry is missing." }
    $reported = (& $stable --version | Select-Object -First 1).Trim()
    $authority = Join-Path $ProgramRoot "current-version.json"
    $snapshot = Read-AuthorityJson $authority
    Add-Event "stable-version-$ExpectedVersion" @{ stable_entry=$stable; reported_version=$reported; authority_json=$snapshot }
    if ($reported -ne $ExpectedVersion) { throw "Stable entry did not launch $ExpectedVersion." }
    return $stable
}
function Invoke-StableHealth([string]$StableEntry, [string]$ExpectedVersion) {
    $process = Start-Process -FilePath $StableEntry -PassThru
    try {
        $deadline = [DateTime]::UtcNow.AddSeconds(45); $health = $null
        while ([DateTime]::UtcNow -lt $deadline) {
            foreach ($port in 8501,8502) { try { $response=Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$port/_stcore/health" -TimeoutSec 2; if($response.StatusCode -eq 200 -and $response.Content.Trim() -eq "ok") { $health=@{port=$port;status=200;body="ok"}; break } } catch {} }
            if ($null -ne $health) { break }; Start-Sleep -Milliseconds 500
        }
        Add-Event "stable-health-$ExpectedVersion" @{ process_id=$process.Id; health=$health }
        if ($null -eq $health) { throw "Stable entry health did not return 200/ok for $ExpectedVersion." }
    } finally {
        if (-not $process.HasExited) { & taskkill /PID $process.Id /T /F | Out-Null }
        Start-Sleep -Seconds 2
        if (@(Get-Listeners).Count -ne 0) { throw "Stable-entry health cleanup left a listener." }
    }
}
function Add-Snapshot([string]$Name, [string]$ProgramRoot) {
    $authority = Join-Path $ProgramRoot "current-version.json"
    $versions = Join-Path $ProgramRoot "versions"
    $snapshot = [ordered]@{ name=$Name; at_utc=[DateTime]::UtcNow.ToString("o"); authority=if(Test-Path $authority){Read-AuthorityJson $authority}else{$null}; directories=@(Get-ChildItem -LiteralPath $versions -Directory -ErrorAction SilentlyContinue | ForEach-Object { $_.Name }) }
    $Result.snapshots += $snapshot
}
function Build-PostCopyFixture([string]$OutputDirectory) {
    $OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
    $source = Join-Path $ProjectRoot "installer\StockTool.iss"
    $compile = Start-Process -FilePath $IsccPath -ArgumentList @("/DMyAppVersion=1.2.2", "/DMyStageDir=$CurrentStaging", "/DMyOutputDir=$OutputDirectory", "/DMyDisableShellIntegration=1", "/DMyFailAfterPayloadCopy=1", $source) -Wait -PassThru
    if ($compile.ExitCode -ne 0) { throw "Post-copy interruption fixture compilation failed." }
    $artifact = Join-Path $OutputDirectory "StockTool-Setup-1.2.2-internal-test.exe"
    if (-not (Test-Path -LiteralPath $artifact -PathType Leaf)) { throw "Post-copy interruption fixture is missing." }
    return $artifact
}

try {
    Assert-Preflight
    $Manifest = ConvertFrom-Json ([IO.File]::ReadAllText($CurrentManifest, [Text.Encoding]::UTF8))
    $StableArtifact = Join-Path $CurrentStaging "StockTool.exe"
    $PayloadArtifact = Join-Path $CurrentStaging "Payload\StockToolPayload.exe"
    $Result.artifacts = [ordered]@{ installer=Get-ArtifactMetadata $CurrentInstaller; stable=Get-ArtifactMetadata $StableArtifact; payload=Get-ArtifactMetadata $PayloadArtifact; rollback_installer=Get-ArtifactMetadata $RollbackInstaller; manifest_path=[IO.Path]::GetFullPath($CurrentManifest) }
    if ($Manifest.sha256 -ne $Result.artifacts.installer.sha256 -or $Manifest.size_bytes -ne $Result.artifacts.installer.size_bytes) { throw "Current installer does not match its manifest." }
    if ($Manifest.staging.stable_entry.sha256 -ne $Result.artifacts.stable.sha256 -or $Manifest.staging.payload.sha256 -ne $Result.artifacts.payload.sha256) { throw "Manifest staging hashes do not match current candidate artifacts." }
    New-Item -ItemType Directory -Path $LifecycleRoot -Force | Out-Null
    $Logs=Join-Path $LifecycleRoot "inno-logs"; $Program=Join-Path $LifecycleRoot "program"; $UserData=Join-Path $LifecycleRoot "user-data"
    New-Item -ItemType Directory -Path $Logs,$UserData -Force | Out-Null
    $Owned=$true; $env:STOCK_TOOL_NO_BROWSER="1"; $env:STOCK_TOOL_USER_DATA_DIR=$UserData
    $Sentinel=Join-Path $UserData "lifecycle-sentinel.txt"; "Sprint 19.1 isolated sentinel" | Set-Content $Sentinel -NoNewline -Encoding utf8; $SentinelHash=Get-Sha256 $Sentinel
    Invoke-Inno "first-install-1.2.1" $RollbackInstaller @("/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/SP-","/DIR=$Program") (Join-Path $Logs "first-install-1.2.1.log")
    $stable=Assert-StableVersion $Program "1.2.1"; Invoke-StableHealth $stable "1.2.1"; Add-Snapshot "first-1.2.1" $Program
    $fixture=Build-PostCopyFixture (Join-Path $LifecycleRoot "post-copy-fixture")
    Invoke-Inno "post-copy-pre-switch-interruption" $fixture @("/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/SP-","/DIR=$Program") (Join-Path $Logs "post-copy-pre-switch-interruption.log")
    Add-Snapshot "interrupted-1.2.2-not-current" $Program
    $interruptionLog = Read-AuthorityJson (Join-Path $Logs "post-copy-pre-switch-interruption.log")
    $interruptedAuthority = Read-AuthorityJson (Join-Path $Program "current-version.json") | ConvertFrom-Json
    if ($interruptedAuthority.version -ne "1.2.1" -or -not (Test-Path -LiteralPath (Join-Path $Program "versions\1.2.2\StockToolPayload.exe"))) { throw "Post-copy interruption activated 1.2.2 or did not deploy its payload." }
    if ($interruptionLog -notmatch "Synthetic interrupted update after payload copy and before authority switch") { throw "Post-copy interruption marker was not observed in the Inno log." }
    Add-Event "interruption-evidence" @{ expected_interruption_observed=$true; payload_copy_completed=$true; authority_unchanged=$true }
    $stable=Assert-StableVersion $Program "1.2.1"; Invoke-StableHealth $stable "1.2.1"
    if ((Get-Sha256 $Sentinel) -ne $SentinelHash) { throw "Post-copy interruption changed user-data sentinel." }
    Invoke-Inno "upgrade-1.2.2" $CurrentInstaller @("/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/SP-","/DIR=$Program") (Join-Path $Logs "upgrade-1.2.2.log")
    $stable=Assert-StableVersion $Program "1.2.2"; Invoke-StableHealth $stable "1.2.2"; Add-Snapshot "upgraded-1.2.2" $Program
    Invoke-Inno "repair-1.2.2" $CurrentInstaller @("/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/SP-","/DIR=$Program") (Join-Path $Logs "repair-1.2.2.log")
    $stable=Assert-StableVersion $Program "1.2.2"
    & $stable --activate-version 1.2.1; if($LASTEXITCODE -ne 0){throw "Production rollback authority activation failed."}
    $stable=Assert-StableVersion $Program "1.2.1"; Invoke-StableHealth $stable "1.2.1"; Add-Snapshot "rolled-back-1.2.1" $Program
    Invoke-Inno "upgrade-again-1.2.2" $CurrentInstaller @("/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/SP-","/DIR=$Program") (Join-Path $Logs "upgrade-again-1.2.2.log")
    $stable=Assert-StableVersion $Program "1.2.2"; Add-Snapshot "upgraded-again-1.2.2" $Program
    $uninstaller=Join-Path $Program "unins000.exe"; Invoke-Inno "uninstall" $uninstaller @("/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/SP-") (Join-Path $Logs "uninstall.log")
    if ((Get-Sha256 $Sentinel) -ne $SentinelHash) { throw "Uninstall changed user-data sentinel." }
    $Result.status="passed"
} catch { $Failure=$_.Exception.Message; $Result.status="failed"; $Result.failure=$Failure } finally {
    $env:STOCK_TOOL_NO_BROWSER=$OriginalNoBrowser; $env:STOCK_TOOL_USER_DATA_DIR=$OriginalUserData
    if($Owned){ Get-StockToolProcesses|Stop-Process -Force -ErrorAction SilentlyContinue; if(Test-Path $UninstallKey){Remove-Item $UninstallKey -Force -ErrorAction SilentlyContinue}; if($null -ne $Program){Remove-Item -LiteralPath $Program -Recurse -Force -ErrorAction SilentlyContinue} }
    $Result.cleanup=[ordered]@{registry_absent= -not(Test-Path $UninstallKey); stocktool_process_count=@(Get-StockToolProcesses).Count; listener_count_8501_8502=@(Get-Listeners).Count; program_directory_absent=($null -eq $Program -or -not(Test-Path $Program)); user_data_sentinel_exists=($null -ne $Sentinel -and (Test-Path $Sentinel))}; $Result.completed_utc=[DateTime]::UtcNow.ToString("o")
    if(Test-Path $LifecycleRoot){
        $resultPath=Join-Path $LifecycleRoot "lifecycle-result.json"
        $serialized=$Result|ConvertTo-Json -Depth 8
        if($serialized.Length -ge 1MB){throw "Lifecycle result exceeds the 1 MB evidence limit."}
        [IO.File]::WriteAllText($resultPath,$serialized,[Text.Encoding]::UTF8)
        $validated=ConvertFrom-Json ([IO.File]::ReadAllText($resultPath,[Text.Encoding]::UTF8))
        if($null -eq $validated.status -or $null -eq $validated.commands -or $null -eq $validated.snapshots -or $null -eq $validated.cleanup -or $null -eq $validated.completed_utc){throw "Lifecycle result schema validation failed."}
    }
}
if($null -ne $Failure){Write-Error $Failure; exit 1}; exit 0
