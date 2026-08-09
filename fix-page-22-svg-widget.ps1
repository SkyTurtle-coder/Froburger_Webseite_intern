$ErrorActionPreference = 'Stop'

$mysql = 'C:\Users\phili\AppData\Local\Programs\Local\resources\extraResources\lightning-services\mysql-8.4.0\bin\win64\bin\mysql.exe'
$dbArgs = @('--protocol=tcp', '-h', '127.0.0.1', '-P', '10005', '-u', 'root', '-proot', 'local', '--batch', '--raw', '-N')
$postId = 22
$widgetId = '11760c9'
$targetAttachmentId = 103
$targetUrl = 'http://avfroburger.local/wp-content/uploads/2026/07/Schild.svg'
$liveJsonPath = Join-Path $PSScriptRoot 'post-22-elementor-data-live.json'
$backupPath = Join-Path $PSScriptRoot 'post-22-elementor-data-backup-before-svg-fix.json'
$sqlPath = Join-Path $PSScriptRoot 'post-22-svg-fix.sql'

if (-not (Test-Path $liveJsonPath)) {
	throw "Missing source file: $liveJsonPath"
}

$raw = Get-Content -Raw -Path $liveJsonPath
Set-Content -Path $backupPath -Value $raw -NoNewline

$oldBlock = '"id":"11760c9","elType":"widget","settings":{"svg":{"$$type":"svg-src","value":{"id":{"$$type":"image-attachment-id","value":17},"url":{"$$type":"url","value":"http:\/\/avfroburger.local\/wp-content\/uploads\/2026\/07\/Zirkel.svg"}}},"link":{"$$type":"link","value":{"isTargetBlank":null}}},"elements":[],"widgetType":"e-svg"'
$newBlock = '"id":"11760c9","elType":"widget","settings":{"svg":{"$$type":"svg-src","value":{"id":{"$$type":"image-attachment-id","value":103},"url":{"$$type":"url","value":"http:\/\/avfroburger.local\/wp-content\/uploads\/2026\/07\/Schild.svg"}}},"link":{"$$type":"link","value":{"isTargetBlank":null}}},"elements":[],"widgetType":"e-svg"'

$matchCount = 0
$offset = 0
while ($true) {
	$index = $raw.IndexOf($oldBlock, $offset, [System.StringComparison]::Ordinal)
	if ($index -lt 0) {
		break
	}

	$matchCount++
	$offset = $index + $oldBlock.Length
}
if ($matchCount -ne 1) {
	throw "Expected exactly 1 widget match for $widgetId, got $matchCount."
}

$updatedJson = $raw.Replace($oldBlock, $newBlock)
$updated = $updatedJson -ne $raw
if (-not $updated) {
	throw "Replacement did not change the exported Elementor JSON."
}

$escapedJson = $updatedJson.Replace('\', '\\').Replace("'", "''")
$sql = "UPDATE wp_postmeta SET meta_value='$escapedJson' WHERE post_id=$postId AND meta_key='_elementor_data';"
Set-Content -Path $sqlPath -Value $sql -NoNewline
Get-Content -Raw -Path $sqlPath | & $mysql @dbArgs | Out-Null
Set-Content -Path $liveJsonPath -Value $updatedJson -NoNewline

Write-Output "Updated widget $widgetId on post $postId to attachment $targetAttachmentId"
Write-Output "Backup: $backupPath"
