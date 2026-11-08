param(
    [Parameter(Mandatory = $true)]
    [string]$LocalFile,

    [Parameter(Mandatory = $true)]
    [string]$RemoteRelativePath,

    [string]$RemoteUser = "avfrobur",
    [string]$RemoteHost = "avfrobur.ssh.cloud.hostpoint.ch",
    [string]$RemoteRoot = "/home/avfrobur/www/newton/test",
    [string]$VerifyUrl = "https://test.avfroburger.ch/ueber-uns/"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $LocalFile -PathType Leaf)) {
    throw "LocalFile not found: $LocalFile"
}

$scp = Get-Command scp.exe -ErrorAction SilentlyContinue
$ssh = Get-Command ssh.exe -ErrorAction SilentlyContinue
if (-not $scp -or -not $ssh) {
    throw "OpenSSH tools not found. Expected ssh.exe and scp.exe in PATH."
}

$normalizedRelative = $RemoteRelativePath -replace "\\", "/"
if ([string]::IsNullOrWhiteSpace($normalizedRelative)) {
    throw "RemoteRelativePath must not be empty."
}
if ($normalizedRelative.StartsWith("/")) {
    throw "RemoteRelativePath must be relative to the test WordPress root, not absolute."
}
if ($normalizedRelative -eq "wp-config.php") {
    throw "Refusing to deploy wp-config.php."
}
if ($normalizedRelative.StartsWith("wp-content/uploads/")) {
    throw "Refusing to deploy into wp-content/uploads/."
}

$remoteFile = "$RemoteRoot/$normalizedRelative"
$remoteDir = [System.IO.Path]::GetDirectoryName($normalizedRelative).Replace("\", "/")
if ([string]::IsNullOrWhiteSpace($remoteDir)) {
    $remoteDir = "."
}
$remoteTargetDir = "$RemoteRoot/$remoteDir"

$scpMacArgs = @("-o", "MACs=hmac-sha2-512")
$sshMacArgs = @("-o", "MACs=hmac-sha2-512")

& $ssh.Source @sshMacArgs "$RemoteUser@$RemoteHost" "set -e; test -f '$RemoteRoot/wp-config.php'; mkdir -p '$remoteTargetDir'"
& $scp.Source @scpMacArgs $LocalFile "${RemoteUser}@${RemoteHost}:${remoteTargetDir}/"

$remoteScript = @"
set -euo pipefail
test -f '$remoteFile'
chmod 644 '$remoteFile'
cd '$RemoteRoot'
wp option get home >/dev/null
wp cache flush
wp transient delete --all
if wp help elementor >/dev/null 2>&1; then
  wp elementor flush-css || echo 'Non-fatal: wp elementor flush-css failed'
fi
curl -fsS '${VerifyUrl}?cb='"`$(date +%s)" >/dev/null
curl -I '${VerifyUrl}'
echo 'Single-file deploy verification OK'
"@

& $ssh.Source @sshMacArgs "$RemoteUser@$RemoteHost" $remoteScript
