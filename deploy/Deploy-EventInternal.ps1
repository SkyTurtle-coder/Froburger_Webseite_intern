param([switch]$Deploy)
$ErrorActionPreference = 'Stop'
function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe fehlgeschlagen (Exit $LASTEXITCODE)." }
}
$repo = Split-Path -Parent $PSScriptRoot
$commit = '09e5040d34bc66000ec0b7af455b97c14be15a1a'
$previous = 'f3b3ae0234ce0c758ba71726b8470bb22bfdb182'
$release = 'avf-event-internal-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
$package = Join-Path $env:TEMP $release
$remote = "/tmp/$release"
New-Item -ItemType Directory -Path $package | Out-Null
$files = @('events/models.py', 'events/forms.py', 'events/views.py', 'events/public_views.py', 'events/admin.py', 'templates/events/event_list.html', 'templates/events/public_event_detail.html')
$migration = 'events/migrations/0011_event_is_internal.py'
Invoke-Checked git (@('-C', $repo, '-c', 'core.autocrlf=false', 'archive', '--format=tar.gz', "--output=$package/new.tar.gz", $commit, '--') + $files + @($migration))
Invoke-Checked git (@('-C', $repo, '-c', 'core.autocrlf=false', 'archive', '--format=tar.gz', "--output=$package/base.tar.gz", "$previous^", '--') + $files)
Invoke-Checked git (@('-C', $repo, '-c', 'core.autocrlf=false', 'archive', '--format=tar.gz', "--output=$package/previous.tar.gz", $previous, '--') + $files)
$previousHash = (Get-FileHash "$package/previous.tar.gz" -Algorithm SHA256).Hash.ToLowerInvariant()
$source = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'event-internal-install.sh')).Replace("`r`n", "`n")
[IO.File]::WriteAllText("$package/install.sh", $source, (New-Object System.Text.UTF8Encoding($false)))
$newHash = (Get-FileHash "$package/new.tar.gz" -Algorithm SHA256).Hash.ToLowerInvariant()
$baseHash = (Get-FileHash "$package/base.tar.gz" -Algorithm SHA256).Hash.ToLowerInvariant()
$scriptHash = (Get-FileHash "$package/install.sh" -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "Paket aus Commit ${commit}: $package"
if (-not $Deploy) { Write-Host 'Nur vorbereitet. Mit -Deploy auf dem Produktionsserver installieren.'; return }
$key = Join-Path $env:USERPROFILE '.ssh/id_ed25519'
$target = 'debian@179.237.81.250'
Invoke-Checked ssh @('-i', $key, $target, "umask 077; mkdir '$remote'")
Invoke-Checked scp @('-i', $key, "$package/new.tar.gz", "$package/base.tar.gz", "$package/previous.tar.gz", "$package/install.sh", "${target}:$remote/")
# Debian production host: use Python, not platform-dependent sha256sum options.
$command = 'python3 -c ''import hashlib,sys; sys.exit(hashlib.sha256(open(sys.argv[1], chr(114)+chr(98)).read()).hexdigest() != sys.argv[2])'' ''{0}/install.sh'' ''{1}'' && bash ''{0}/install.sh'' ''{2}'' ''{3}'' ''{4}'' ''{5}''' -f $remote, $scriptHash, $release, $newHash, $baseHash, $previousHash
Invoke-Checked ssh @('-t', '-i', $key, $target, $command)
Write-Host 'Anlass-Erweiterung erfolgreich installiert.'
