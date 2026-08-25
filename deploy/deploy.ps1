param(
    [string]$HostName = "179.237.81.250",
    [string]$SshUser = "debian",
    [string]$SshKeyPath = "C:\Users\phili\.ssh\id_ed25519",
    [string]$RemoteAppDir = "/srv/avf-intern/app",
    [string]$RemoteOwner = "avfapp:avfapp"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$expectedRemoteAppDir = "/srv/avf-intern/app"
if ([string]::IsNullOrWhiteSpace($RemoteAppDir) -or $RemoteAppDir -ne $expectedRemoteAppDir) {
    throw "RemoteAppDir must exactly match the approved application directory: $expectedRemoteAppDir"
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$remoteBackupDir = "/srv/avf-intern/backups/app-$timestamp"
$remoteArchivePath = "/tmp/avf-intern-app-$timestamp.tar"
$sshTarget = "$SshUser@$HostName"
$sshArgs = @("-i", $SshKeyPath)
$includePaths = @(
    "accounts",
    "config",
    "core",
    "deploy",
    "documents",
    "events",
    "static",
    "templates",
    "tools",
    ".env.example",
    ".env.production.example",
    "manage.py",
    "README.md",
    "requirements.txt"
)

Write-Host "Erstelle Remote-Backup unter $remoteBackupDir"
& ssh @sshArgs $sshTarget "sudo mkdir -p '$remoteBackupDir'; if [ -d '$RemoteAppDir' ]; then sudo cp -a '$RemoteAppDir/.' '$remoteBackupDir/'; fi"

$rsync = Get-Command rsync -ErrorAction SilentlyContinue
if ($rsync) {
    Write-Host "Synchronisiere mit rsync"
    & $rsync.Source -az --delete-delay --backup --backup-dir="$remoteBackupDir" `
        -e "ssh -i `"$SshKeyPath`"" `
        --delete `
        @($includePaths | ForEach-Object { "--include=$_"; if (Test-Path (Join-Path $projectRoot $_) -PathType Container) { "--include=$_/**" } }) `
        --exclude="*" `
        "$projectRoot/" `
        "${sshTarget}:$RemoteAppDir/"
} else {
    Write-Host "rsync nicht gefunden; verwende temporaren Tarball plus scp"
    $localArchivePath = Join-Path $env:TEMP "avf-intern-app-$timestamp.tar"
    if (Test-Path $localArchivePath) {
        Remove-Item -LiteralPath $localArchivePath -Force
    }
    & tar -cf $localArchivePath -C $projectRoot @includePaths
    & scp @sshArgs $localArchivePath "${sshTarget}:$remoteArchivePath"
    & ssh @sshArgs $sshTarget "set -eu; test '$RemoteAppDir' = '$expectedRemoteAppDir'; test -d '$RemoteAppDir'; sudo find '$RemoteAppDir' -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +; sudo tar -xf '$remoteArchivePath' -C '$RemoteAppDir'; sudo rm -f '$remoteArchivePath'"
    Remove-Item -LiteralPath $localArchivePath -Force
}

& ssh @sshArgs $sshTarget "sudo chown -R $RemoteOwner '$RemoteAppDir'"
Write-Host "Quellcodeuebertragung abgeschlossen"
