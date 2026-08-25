param(
    [string]$SourceDir = "C:\Users\phili\Local Sites\av-froburger\app\public",
    [string]$RemoteUser = "avfrobur",
    [string]$RemoteHost = "avfrobur.ssh.cloud.hostpoint.ch",
    [string]$RemoteTmpDir = "/home/avfrobur/deploy-tmp",
    [string]$RemoteTargetDir = "/home/avfrobur/www/newton/test",
    [string]$VerifyUrl = "https://test.avfroburger.ch/mitglieder/",
    [string[]]$ChangedFiles = @(),
    [switch]$FullMirror,
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"

$expectedRemoteHost = "avfrobur.ssh.cloud.hostpoint.ch"
$expectedRemoteTmpDir = "/home/avfrobur/deploy-tmp"
$expectedRemoteTargetDir = "/home/avfrobur/www/newton/test"
$expectedVerifyUrl = "https://test.avfroburger.ch/mitglieder/"

function Assert-TestDeployTarget {
    if ($RemoteHost -cne $expectedRemoteHost -or
        $RemoteTmpDir -cne $expectedRemoteTmpDir -or
        $RemoteTargetDir -cne $expectedRemoteTargetDir -or
        $VerifyUrl -cne $expectedVerifyUrl) {
        throw "Refusing deployment: the configured destination is not the approved test target."
    }
}

function Get-ChangedFileRelativePath {
    param([string]$ChangedFile)

    $sourceRoot = [System.IO.Path]::GetFullPath($SourceDir).TrimEnd([char]'\', [char]'/')
    $filePath = [System.IO.Path]::GetFullPath($ChangedFile)
    $sourcePrefix = $sourceRoot + [System.IO.Path]::DirectorySeparatorChar

    if (-not $filePath.StartsWith($sourcePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "ChangedFiles entries must be inside SourceDir: $ChangedFile"
    }
    if (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) {
        throw "Changed file not found: $ChangedFile"
    }

    return $filePath.Substring($sourcePrefix.Length).Replace('\', '/')
}

if (-not (Test-Path -LiteralPath $SourceDir -PathType Container)) {
    throw "SourceDir not found: $SourceDir"
}

$scp = Get-Command scp.exe -ErrorAction SilentlyContinue
$ssh = Get-Command ssh.exe -ErrorAction SilentlyContinue
if (-not $scp -or -not $ssh) {
    throw "OpenSSH tools not found. Expected ssh.exe and scp.exe in PATH."
}

Assert-TestDeployTarget

$stagingRoot = Join-Path $env:TEMP ("avf-test-deploy-" + [guid]::NewGuid().ToString("N"))
$stagingPublic = Join-Path $stagingRoot "public"

$excludeDirs = @(
    ".git",
    ".claude",
    "wp-content\\uploads",
    "wp-content\\upgrade",
    "wp-content\\cache",
    "wp-content\\backups-dup-lite"
)
$excludeFiles = @(
    "wp-config.php",
    "local-xdebuginfo.php"
)

if (-not $FullMirror) {
    if ($ChangedFiles.Count -eq 0) {
        throw "Minimal deploy requires at least one -ChangedFiles entry. Use -FullMirror only for an explicitly approved full sync."
    }

    $singleFileScript = Join-Path $PSScriptRoot "deploy-test-file.ps1"
    if (-not (Test-Path -LiteralPath $singleFileScript -PathType Leaf)) {
        throw "Minimal deploy helper not found: $singleFileScript"
    }

    foreach ($changedFile in $ChangedFiles) {
        $relativePath = Get-ChangedFileRelativePath $changedFile
        if ($relativePath -in $excludeFiles -or ($excludeDirs | Where-Object { $relativePath.StartsWith($_.Replace('\\', '/') + '/', [System.StringComparison]::OrdinalIgnoreCase) })) {
            throw "Refusing to deploy excluded path: $relativePath"
        }

        if ($WhatIf) {
            Write-Host "WhatIf: would minimally deploy $relativePath to $RemoteTargetDir/$relativePath"
            continue
        }

        & $singleFileScript `
            -LocalFile $changedFile `
            -RemoteUser $RemoteUser `
            -RemoteHost $RemoteHost `
            -RemoteRoot $RemoteTargetDir `
            -RemoteRelativePath $relativePath `
            -VerifyUrl $VerifyUrl
    }

    return
}

if ($WhatIf) {
    Write-Host "WhatIf: would mirror $SourceDir to $RemoteTargetDir with rsync --delete after applying the existing excludes."
    return
}

try {
    New-Item -ItemType Directory -Path $stagingPublic -Force | Out-Null

    $robocopyArgs = @(
        $SourceDir,
        $stagingPublic,
        "/MIR",
        "/R:1",
        "/W:1",
        "/NFL",
        "/NDL",
        "/NJH",
        "/NJS",
        "/XF"
    ) + $excludeFiles + @(
        "/XD"
    ) + ($excludeDirs | ForEach-Object { Join-Path $SourceDir $_ })

    & robocopy @robocopyArgs | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy failed with exit code $LASTEXITCODE"
    }

    $remoteStageDir = "$RemoteTmpDir/public"
    $scpMacArgs = @("-o", "MACs=hmac-sha2-512")
    $sshMacArgs = @("-o", "MACs=hmac-sha2-512")

    & $ssh.Source @sshMacArgs "$RemoteUser@$RemoteHost" "mkdir -p '$RemoteTmpDir' && rm -rf '$remoteStageDir'"
    & $scp.Source @scpMacArgs -r $stagingPublic "${RemoteUser}@${RemoteHost}:${RemoteTmpDir}/"

    $remoteScript = @"
set -euo pipefail
mkdir -p '$RemoteTmpDir' '$RemoteTargetDir'
test -f '$RemoteTargetDir/wp-config.php'
test -d '$remoteStageDir'
rsync -a --delete \
  --exclude 'wp-config.php' \
  --exclude 'wp-content/uploads/' \
  --exclude 'wp-content/upgrade/' \
  --exclude 'wp-content/cache/' \
  --exclude 'wp-content/backups-dup-lite/' \
  '$remoteStageDir/' '$RemoteTargetDir/'
find '$RemoteTargetDir' -type d -exec chmod 755 {} +
find '$RemoteTargetDir' -type f -exec chmod 644 {} +
chmod 640 '$RemoteTargetDir/wp-config.php'
cd '$RemoteTargetDir'
wp cache flush
wp transient delete --all
if wp help elementor >/dev/null 2>&1; then
  wp elementor flush-css
else
  echo 'Skipping wp elementor flush-css: command not available'
fi
curl -fsS '${VerifyUrl}?cb='"`$(date +%s)" >/dev/null
echo 'Deploy verification OK'
"@

    & $ssh.Source @sshMacArgs "$RemoteUser@$RemoteHost" $remoteScript
}
finally {
    if (Test-Path -LiteralPath $stagingRoot) {
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force
    }
}
