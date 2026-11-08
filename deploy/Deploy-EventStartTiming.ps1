param([switch]$Deploy)
$ErrorActionPreference = 'Stop'
function Run-Native {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe fehlgeschlagen (Exit $LASTEXITCODE). Bitte Ausgabe pruefen." }
}
$intern = Split-Path -Parent $PSScriptRoot
$public = Join-Path (Split-Path -Parent $intern) 'public'
$release = 'avf-timing-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
$package = Join-Path $env:TEMP $release
New-Item -ItemType Directory -Path $package | Out-Null
$internFiles = @('events/models.py', 'events/forms.py', 'events/admin.py', 'events/public_views.py', 'templates/events/event_list.html', 'templates/events/public_event_detail.html', 'templates/core/dashboard.html')
$migration = 'events/migrations/0010_event_start_timing.py'
$publicFiles = @('class-avf-events-api-client.php', 'class-avf-events-view-helpers.php', 'class-avf-events-list-shortcode.php', 'class-avf-upcoming-events-shortcode.php', 'class-avf-event-detail-shortcode.php') | ForEach-Object { "wp-content/plugins/avf-events-integration/includes/$_" }
Run-Native git (@('-C', $intern, '-c', 'core.autocrlf=false', 'archive', '--format=tar.gz', "--output=$package/backend.tar.gz", '1e8d5ca', '--') + $internFiles + @($migration))
Run-Native git (@('-C', $intern, '-c', 'core.autocrlf=false', 'archive', '--format=tar.gz', "--output=$package/backend-base.tar.gz", '1e8d5ca^', '--') + $internFiles)
Run-Native git (@('-C', $public, '-c', 'core.autocrlf=false', 'archive', '--format=tar.gz', "--output=$package/wordpress.tar.gz", 'a6153d3', '--') + $publicFiles)
Run-Native git (@('-C', $public, '-c', 'core.autocrlf=false', 'archive', '--format=tar.gz', "--output=$package/wordpress-base.tar.gz", 'a6153d3^', '--') + $publicFiles)
foreach ($name in @('backend', 'wordpress')) {
    $source = [IO.File]::ReadAllText((Join-Path $PSScriptRoot "timing-$name.sh")).Replace("`r`n", "`n")
    [IO.File]::WriteAllText((Join-Path $package "$name.sh"), $source, (New-Object System.Text.UTF8Encoding($false)))
}
Write-Host "Pakete vorbereitet: $package"
Write-Host 'Django: 1e8d5ca; WordPress: a6153d3'
if (-not $Deploy) { Write-Host 'Mit -Deploy werden beide Server aktualisiert.'; return }
$key = Join-Path $env:USERPROFILE '.ssh/id_ed25519'
$backend = 'debian@179.237.81.250'
$wp = 'avfroburger-hostpoint'
$wpStage = "/home/avfrobur/deploy-tmp/$release"
Run-Native ssh @('-i', $key, $backend, "umask 077; mkdir /tmp/$release")
Run-Native ssh @($wp, "umask 077; mkdir -p $wpStage")
Run-Native scp @('-i', $key, "$package/backend.tar.gz", "$package/backend-base.tar.gz", "$package/backend.sh", "${backend}:/tmp/$release/")
Run-Native scp @("$package/wordpress.tar.gz", "$package/wordpress-base.tar.gz", "$package/wordpress.sh", "${wp}:$wpStage/")
$backendHash = (Get-FileHash "$package/backend.tar.gz" -Algorithm SHA256).Hash.ToLowerInvariant()
$backendBaseHash = (Get-FileHash "$package/backend-base.tar.gz" -Algorithm SHA256).Hash.ToLowerInvariant()
$wpHash = (Get-FileHash "$package/wordpress.tar.gz" -Algorithm SHA256).Hash.ToLowerInvariant()
$wpBaseHash = (Get-FileHash "$package/wordpress-base.tar.gz" -Algorithm SHA256).Hash.ToLowerInvariant()
# Check WordPress first so a missing login or divergent plugin blocks before Django changes.
Run-Native ssh @($wp, "bash $wpStage/wordpress.sh $release $wpHash $wpBaseHash check")
Run-Native ssh @('-t', '-i', $key, $backend, "bash /tmp/$release/backend.sh $release $backendHash $backendBaseHash")
Run-Native ssh @($wp, "bash $wpStage/wordpress.sh $release $wpHash $wpBaseHash install")
Write-Host 'Deployment erfolgreich. Im internen Anlassformular jetzt die Zeitangabe s.t. oder c.t. auswaehlen.'
