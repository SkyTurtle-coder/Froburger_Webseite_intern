# Read-only diagnosis. Does not deploy, restart services or read settings/secrets.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$key = Join-Path $env:USERPROFILE '.ssh/id_ed25519'
if (-not (Test-Path -LiteralPath $key -PathType Leaf)) { throw "SSH-Schluessel fehlt: $key" }
$allowed = @('config/urls.py', 'core/context_processors.py', 'templates/base.html', 'templates/partials/navigation_links.html')
$remoteCommand = "bash -c 'set -o pipefail; sudo -n tar -czf - -C /srv/avf-intern/app config/urls.py core/context_processors.py templates/base.html templates/partials/navigation_links.html | base64 -w0'"
Write-Host 'Lese die vier betroffenen Serverdateien. Keine Installation und kein Neustart.'
# Base64 avoids Windows PowerShell 5 corrupting binary SSH output through redirection.
$encoded = & 'C:/Windows/System32/OpenSSH/ssh.exe' -o ConnectTimeout=15 -i $key debian@179.237.81.250 $remoteCommand
if ($LASTEXITCODE -ne 0) { throw 'Serverdateien konnten nicht gelesen werden. Es wurde nichts installiert.' }
$bytes = [Convert]::FromBase64String(($encoded -join ''))
if ($bytes.Length -eq 0) { throw 'Leere Antwort vom Server.' }
$destination = Join-Path $root ('data/forum-server-review/' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $destination | Out-Null
$archive = Join-Path $destination 'server-files.tar.gz'
[IO.File]::WriteAllBytes($archive, $bytes)
$entries = @(& tar -tzf $archive)
if ($LASTEXITCODE -ne 0) { throw 'Serverarchiv konnte nicht geprueft werden.' }
if ($entries.Count -ne $allowed.Count) { throw 'Unerwarteter Archivinhalt; nicht entpackt.' }
foreach ($entry in $entries) {
    if ($allowed -notcontains $entry) { throw 'Unerwarteter Dateipfad im Archiv; nicht entpackt.' }
}
& tar -xzf $archive -C $destination
if ($LASTEXITCODE -ne 0) { throw 'Serverarchiv konnte nicht entpackt werden.' }
Write-Host "Serverdateien lokal gespeichert: $destination"
Write-Host 'Diagnose abgeschlossen. Diese Ausgabe im Chat senden; die Dateien liegen bereits im gemeinsamen Arbeitsverzeichnis.'
