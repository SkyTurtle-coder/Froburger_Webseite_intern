param([switch]$Deploy)

$ErrorActionPreference = 'Stop'
function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe fehlgeschlagen (Exit $LASTEXITCODE). Deployment gestoppt." }
}
$root = Split-Path -Parent $PSScriptRoot
$commit = (git -C $root rev-parse 'feature/forum^{commit}').Trim()
if ($LASTEXITCODE -ne 0) { throw 'Der lokale Branch feature/forum fehlt.' }
$baseline = '337c194'
$release = 'avf-forum-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
$package = Join-Path $env:TEMP $release
New-Item -ItemType Directory -Path $package | Out-Null
$shared = @('config/settings.py', 'config/urls.py', 'core/context_processors.py', 'templates/base.html', 'templates/partials/navigation_links.html')
$files = $shared + @('forum', 'templates/forum', 'static/forum', 'static/vendor/pdfjs')
$archive = Join-Path $package 'forum.tar.gz'
$before = Join-Path $package 'baseline.tar.gz'
Invoke-Checked git (@('-C', $root, 'archive', '--format=tar.gz', "--output=$archive", $commit, '--') + $files)
Invoke-Checked git (@('-C', $root, 'archive', '--format=tar.gz', "--output=$before", $baseline, '--') + $shared)
$script = Join-Path $package 'install.sh'
$source = [System.IO.File]::ReadAllText((Join-Path $PSScriptRoot 'forum-install.sh')).Replace("`r`n", "`n")
[System.IO.File]::WriteAllText($script, $source, (New-Object System.Text.UTF8Encoding($false)))
$hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
$beforeHash = (Get-FileHash -LiteralPath $before -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "Forum-Paket aus Commit ${commit}: $archive"
if (-not $Deploy) {
    Write-Host 'Nur vorbereitet. Mit -Deploy folgen Upload, Backup, Forum-Migration und Neustart.'
    return
}
$key = Join-Path $env:USERPROFILE '.ssh/id_ed25519'
if (-not (Test-Path -LiteralPath $key -PathType Leaf)) { throw "SSH-Schluessel fehlt: $key" }
$target = 'debian@179.237.81.250'
Invoke-Checked ssh @('-i', $key, $target, "umask 077; mkdir /tmp/$release")
Invoke-Checked scp @('-i', $key, $archive, $before, $script, "${target}:/tmp/$release/")
Invoke-Checked ssh @('-t', '-i', $key, $target, "bash /tmp/$release/install.sh $release $hash $beforeHash")
Write-Host "Forum-Deployment $release erfolgreich."
