param([switch]$Deploy)

$ErrorActionPreference = 'Stop'
function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe fehlgeschlagen (Exit $LASTEXITCODE)." }
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$commit = '4b670eca0e3149bc411965e05d783fba8bdb2dd9'
$release = 'avf-email-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
$packageDir = Join-Path $env:TEMP $release
New-Item -ItemType Directory -Path $packageDir | Out-Null
$archive = Join-Path $packageDir 'email.tar.gz'
Invoke-Checked git @('-C', $projectRoot, 'archive', '--format=tar.gz', "--output=$archive", $commit, '--', 'accounts/forms.py', 'accounts/admin.py', 'templates/accounts/profile_form.html')
$installer = Join-Path $packageDir 'install.sh'
$source = [System.IO.File]::ReadAllText((Join-Path $PSScriptRoot 'profile-email-install.sh')).Replace("`r`n", "`n")
[System.IO.File]::WriteAllText($installer, $source, (New-Object System.Text.UTF8Encoding($false)))
$archiveHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "Paket aus Commit ${commit}: $archive"
if (-not $Deploy) {
    Write-Host 'Nur vorbereitet. Mit -Deploy werden Upload und Installation ausgefuehrt.'
    return
}

$sshKey = Join-Path $env:USERPROFILE '.ssh/id_ed25519'
if (-not (Test-Path -LiteralPath $sshKey -PathType Leaf)) { throw "SSH-Schluessel fehlt: $sshKey" }
$target = 'debian@179.237.81.250'
Invoke-Checked scp @('-i', $sshKey, $archive, "${target}:/tmp/$release.tar.gz")
Invoke-Checked scp @('-i', $sshKey, $installer, "${target}:/tmp/$release-install.sh")
Invoke-Checked ssh @('-t', '-i', $sshKey, $target, "bash /tmp/$release-install.sh $release $archiveHash")
Write-Host "Deployment $release erfolgreich abgeschlossen."
