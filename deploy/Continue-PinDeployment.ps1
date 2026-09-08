param(
    [ValidatePattern('\Aavf-pin-[0-9]{8}-[0-9]{6}\z')]
    [string]$Release = 'avf-pin-20260909-003225',
    [switch]$Deploy
)

# Continues an already uploaded release. No dependence on previous SSH sessions.
$ErrorActionPreference = 'Stop'
function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe fehlgeschlagen (Exit $LASTEXITCODE). Deployment gestoppt." }
}
$sshKey = Join-Path $env:USERPROFILE '.ssh/id_ed25519'
$backendTarget = 'debian@179.237.81.250'
$wordpressTarget = 'avfroburger-hostpoint'
$wpStage = "/home/avfrobur/deploy-tmp/$Release"
$scripts = Join-Path $PSScriptRoot 'pin'
foreach ($name in @('wordpress-prepare.sh', 'backend-install.sh', 'wordpress-install.sh')) {
    if (-not (Test-Path -LiteralPath (Join-Path $scripts $name) -PathType Leaf)) {
        throw "Deployment-Skript fehlt: $name"
    }
}
if (-not $Deploy) {
    Write-Host "Release: $Release"
    Write-Host 'Geprueft werden nur SSH-Zugang, Pakete und Serverpfade.'
    Invoke-Checked ssh @('-i', $sshKey, $backendTarget,
        "test -s /tmp/$Release-intern.tar.gz && test -f /srv/avf-intern/app/manage.py && systemctl is-active avf-intern && echo BACKEND_OK")
    Invoke-Checked ssh @($wordpressTarget,
        "test -s $wpStage/public.tar.gz && test -f /home/avfrobur/www/gamma.avfroburger.ch/wp-config.php && echo WORDPRESS_OK")
    Write-Host 'Vorpruefung erfolgreich. Fuer die Auslieferung denselben Befehl mit -Deploy ausfuehren.'
    return
}

# Upload scripts as files: avoids multiline clipboard corruption and lost shell variables.
$uploadRoot = Join-Path $env:TEMP ('avf-pin-scripts-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $uploadRoot | Out-Null
foreach ($name in @('wordpress-prepare.sh', 'backend-install.sh', 'wordpress-install.sh')) {
    $content = [System.IO.File]::ReadAllText((Join-Path $scripts $name)).Replace("`r`n", "`n")
    [System.IO.File]::WriteAllText((Join-Path $uploadRoot $name), $content, (New-Object System.Text.UTF8Encoding($false)))
}
Invoke-Checked scp @('-i', $sshKey, (Join-Path $uploadRoot 'backend-install.sh'), "${backendTarget}:/tmp/$Release-backend-install.sh")
Invoke-Checked scp @((Join-Path $uploadRoot 'wordpress-prepare.sh'), (Join-Path $uploadRoot 'wordpress-install.sh'), "${wordpressTarget}:$wpStage/")
Write-Host 'WordPress: Paket pruefen, Backup und Wartungsfenster.'
Invoke-Checked ssh @($wordpressTarget, "bash $wpStage/wordpress-prepare.sh $Release")
Write-Host 'Django: Backup, Migration und Neustart.'
Invoke-Checked ssh @('-i', $sshKey, $backendTarget, "bash /tmp/$Release-backend-install.sh $Release")
Write-Host 'WordPress: PIN-Formular aktivieren und pruefen.'
Invoke-Checked ssh @($wordpressTarget, "bash $wpStage/wordpress-install.sh $Release")
Write-Host "Deployment $Release erfolgreich abgeschlossen."
