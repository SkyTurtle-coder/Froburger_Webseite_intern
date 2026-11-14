param([switch]$Deploy)
$ErrorActionPreference = 'Stop'
function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe fehlgeschlagen (Exit $LASTEXITCODE)." }
}
$repo = Split-Path -Parent $PSScriptRoot
$commit = '27a4df7'
$baseline = '7aee997d49b8d3e5bfd2beffe8ab0ae9061a3a01'
$release = 'avf-member-signup-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
$package = Join-Path $env:TEMP $release
$remote = "/tmp/$release"
New-Item -ItemType Directory -Path $package | Out-Null
$files = @('events/models.py', 'events/views.py', 'events/public_views.py', 'templates/events/public_event_detail.html')
$additions = @('events/member_signup.py', 'events/migrations/0012_member_signup_policy.py')
Invoke-Checked git (@('-C', $repo, '-c', 'core.autocrlf=false', 'archive', '--format=tar.gz', "--output=$package/new.tar.gz", $commit, '--') + $files + $additions)
Invoke-Checked git (@('-C', $repo, '-c', 'core.autocrlf=false', 'archive', '--format=tar.gz', "--output=$package/base.tar.gz", $baseline, '--') + $files)
$source = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'member-signup-install.sh')).Replace("`r`n", "`n")
[IO.File]::WriteAllText("$package/install.sh", $source, (New-Object System.Text.UTF8Encoding($false)))
$newHash = (Get-FileHash "$package/new.tar.gz" -Algorithm SHA256).Hash.ToLowerInvariant()
$baseHash = (Get-FileHash "$package/base.tar.gz" -Algorithm SHA256).Hash.ToLowerInvariant()
$scriptHash = (Get-FileHash "$package/install.sh" -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "Paket aus Commit ${commit}: $package"
if (-not $Deploy) { Write-Host 'Nur vorbereitet. Mit -Deploy installieren; danach WordPress deployen.'; return }
$key = Join-Path $env:USERPROFILE '.ssh/id_ed25519'
$target = 'debian@179.237.81.250'
Invoke-Checked ssh @('-i', $key, $target, "umask 077; mkdir '$remote'")
Invoke-Checked scp @('-i', $key, "$package/new.tar.gz", "$package/base.tar.gz", "$package/install.sh", "${target}:$remote/")
$command = 'python3 -c ''import hashlib,sys; sys.exit(hashlib.sha256(open(sys.argv[1], chr(114)+chr(98)).read()).hexdigest() != sys.argv[2])'' ''{0}/install.sh'' ''{1}'' && bash ''{0}/install.sh'' ''{2}'' ''{3}'' ''{4}''' -f $remote, $scriptHash, $release, $newHash, $baseHash
Invoke-Checked ssh @('-t', '-i', $key, $target, $command)
Write-Host 'Backend installiert. Jetzt das WordPress-Update ausfuehren.'
