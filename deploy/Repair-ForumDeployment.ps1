param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('\Aavf-forum-[0-9]{8}-[0-9]{6}\z')]
    [string]$Release
)
$ErrorActionPreference = 'Stop'
$key = Join-Path $env:USERPROFILE '.ssh/id_ed25519'
$target = 'debian@179.237.81.250'
$name = 'avf-forum-repair-' + [guid]::NewGuid().ToString('N') + '.sh'
$localScript = Join-Path $env:TEMP $name
$source = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'forum-repair.sh')).Replace("`r`n", "`n")
[IO.File]::WriteAllText($localScript, $source, (New-Object System.Text.UTF8Encoding($false)))
& scp -i $key $localScript "${target}:/tmp/$name"
if ($LASTEXITCODE -ne 0) { throw 'Reparatur-Skript konnte nicht hochgeladen werden.' }
& ssh -t -i $key $target "bash /tmp/$name $Release"
if ($LASTEXITCODE -ne 0) { throw 'Reparatur fehlgeschlagen. Bitte die vollstaendige Ausgabe pruefen.' }
Write-Host 'Forum-Reparatur erfolgreich. Django-Dienst und Erreichbarkeit geprueft.'
