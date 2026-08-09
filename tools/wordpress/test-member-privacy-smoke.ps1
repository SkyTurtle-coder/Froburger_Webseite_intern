param(
    [string]$Domain = "avfroburger.local",
    [int]$Port = 10004
)

$ErrorActionPreference = "Stop"

function Invoke-LocalCurl {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & curl.exe @Arguments
}

function Get-Response {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url,
        [string]$Method = "GET",
        [string[]]$ExtraArguments = @()
    )

    $headerFile = [System.IO.Path]::GetTempFileName()
    $bodyFile = [System.IO.Path]::GetTempFileName()

    try {
        $args = @(
            "-sS",
            "-X", $Method,
            "-D", $headerFile,
            "-o", $bodyFile,
            "--connect-to", "$Domain`:80:127.0.0.1:$Port"
        ) + $ExtraArguments + @($Url)

        Invoke-LocalCurl -Arguments $args | Out-Null
        $headers = Get-Content $headerFile -Raw
        $body = Get-Content $bodyFile -Raw
        return [pscustomobject]@{
            headers = $headers
            body    = $body
        }
    }
    finally {
        Remove-Item $headerFile, $bodyFile -Force -ErrorAction SilentlyContinue
    }
}

function New-Result {
    param(
        [string]$Check,
        [string]$State,
        [string]$Detail
    )

    [pscustomobject]@{
        check  = $Check
        state  = $State
        detail = $Detail
    }
}

$results = @()

$memberUrl = "http://$Domain/mitglieder/"
$aboutUrl = "http://$Domain/ueber-uns/"
$restUrl = "http://$Domain/wp-json/wp/v2/media/480"
$sitemapUrl = "http://$Domain/wp-sitemap.xml"
$legacyUrl = "http://$Domain/wp-content/uploads/avf-members/Foto_farbig.webp"

try {
    $memberResponse = Get-Response -Url $memberUrl
} catch {
    $results += New-Result -Check "Mitgliederseite erreichbar" -State "BLOCKED_BY_ENVIRONMENT" -Detail $_.Exception.Message
    $results | Format-Table -AutoSize
    exit 0
}

if ($memberResponse.body -match "Requirements Not Met|missing the MySQL extension|502 Bad Gateway") {
    $results += New-Result -Check "Mitgliederseite erreichbar" -State "BLOCKED_BY_ENVIRONMENT" -Detail ($memberResponse.body -replace "\s+", " ").Trim()
    $results | Format-Table -AutoSize
    exit 0
}

$results += New-Result -Check "Mitgliederseite Status 200" -State ($(if ($memberResponse.headers -match "^HTTP/.* 200 ") { "PASS" } else { "FAIL" })) -Detail ($memberResponse.headers -replace "`r?`n", " | ")
$results += New-Result -Check "Mitgliederseite X-Robots noindex" -State ($(if ($memberResponse.headers -match "X-Robots-Tag:\s*noindex") { "PASS" } else { "FAIL" })) -Detail ($memberResponse.headers -replace "`r?`n", " | ")
$results += New-Result -Check "Mitgliederseite noimageindex" -State ($(if ($memberResponse.body -match "noimageindex") { "PASS" } else { "FAIL" })) -Detail "robots meta"
$results += New-Result -Check "Mitgliederseite max-image-preview:none" -State ($(if ($memberResponse.body -match "max-image-preview:none") { "PASS" } else { "FAIL" })) -Detail "robots meta"
$results += New-Result -Check "Mitgliederbilder dekorativ" -State ($(if ($memberResponse.body -match 'alt=""\s+aria-hidden="true"') { "PASS" } else { "FAIL" })) -Detail 'alt="" aria-hidden="true"'
$imageMarkup = ([regex]::Matches($memberResponse.body, '<img[^>]+>') | ForEach-Object { $_.Value }) -join "`n"
$results += New-Result -Check "Mitglieder-Bild-URLs ohne Klarname" -State ($(if ($imageMarkup -notmatch "Foto_farbig|thuerlemann|philipp-thuerlemann") { "PASS" } else { "FAIL" })) -Detail "img markup inspected"

$aboutResponse = Get-Response -Url $aboutUrl
$results += New-Result -Check "Normale Seite bleibt indexierbar" -State ($(if ($aboutResponse.headers -notmatch "X-Robots-Tag:\s*noindex" -and $aboutResponse.body -notmatch "noindex") { "PASS" } else { "FAIL" })) -Detail ($aboutResponse.headers -replace "`r?`n", " | ")

$tokenMatch = [regex]::Match($memberResponse.body, 'member-media/([a-f0-9]{32})/')
if (-not $tokenMatch.Success) {
    $results += New-Result -Check "Mitgliederseite rendert Token-Bild" -State "SKIPPED" -Detail "Kein aktives Token-Bild im HTML gefunden"
} else {
    $token = $tokenMatch.Groups[1].Value
    $tokenUrl = "http://$Domain/member-media/$token/"
    $tokenHead = Get-Response -Url $tokenUrl -Method "HEAD"
    $tokenGet = Get-Response -Url $tokenUrl

    $results += New-Result -Check "Token-HEAD Status 200" -State ($(if ($tokenHead.headers -match "^HTTP/.* 200 ") { "PASS" } else { "FAIL" })) -Detail ($tokenHead.headers -replace "`r?`n", " | ")
    $results += New-Result -Check "Token-GET Status 200" -State ($(if ($tokenGet.headers -match "^HTTP/.* 200 ") { "PASS" } else { "FAIL" })) -Detail ($tokenGet.headers -replace "`r?`n", " | ")
    $results += New-Result -Check "Token liefert noindex/noimageindex" -State ($(if ($tokenHead.headers -match "X-Robots-Tag:\s*noindex,\s*noimageindex") { "PASS" } else { "FAIL" })) -Detail ($tokenHead.headers -replace "`r?`n", " | ")
    $results += New-Result -Check "Token liefert nosniff" -State ($(if ($tokenHead.headers -match "X-Content-Type-Options:\s*nosniff") { "PASS" } else { "FAIL" })) -Detail ($tokenHead.headers -replace "`r?`n", " | ")
    $results += New-Result -Check "Token liefert Cache-Control" -State ($(if ($tokenHead.headers -match "Cache-Control:\s*public,\s*max-age=86400") { "PASS" } else { "FAIL" })) -Detail ($tokenHead.headers -replace "`r?`n", " | ")
    $results += New-Result -Check "Token liefert ETag" -State ($(if ($tokenHead.headers -match "ETag:\s*") { "PASS" } else { "FAIL" })) -Detail ($tokenHead.headers -replace "`r?`n", " | ")
    $results += New-Result -Check "Token liefert Last-Modified" -State ($(if ($tokenHead.headers -match "Last-Modified:\s*") { "PASS" } else { "FAIL" })) -Detail ($tokenHead.headers -replace "`r?`n", " | ")
    $results += New-Result -Check "Token hat keinen Redirect" -State ($(if ($tokenHead.headers -notmatch "^Location:") { "PASS" } else { "FAIL" })) -Detail ($tokenHead.headers -replace "`r?`n", " | ")

    $etagMatch = [regex]::Match($tokenHead.headers, 'ETag:\s*(".*?")')
    if ($etagMatch.Success) {
        $etag = $etagMatch.Groups[1].Value
        $conditional = Get-Response -Url $tokenUrl -Method "HEAD" -ExtraArguments @("-H", "If-None-Match: $etag")
        $results += New-Result -Check "Token beantwortet If-None-Match" -State ($(if ($conditional.headers -match "^HTTP/.* 304 ") { "PASS" } else { "FAIL" })) -Detail ($conditional.headers -replace "`r?`n", " | ")
    } else {
        $results += New-Result -Check "Token beantwortet If-None-Match" -State "SKIPPED" -Detail "Kein ETag fuer Test gefunden"
    }
}

$invalidResponse = Get-Response -Url ("http://$Domain/member-media/invalidtoken123456789012/")
$results += New-Result -Check "Ungueltiger Token liefert 404" -State ($(if ($invalidResponse.headers -match "^HTTP/.* 404 ") { "PASS" } else { "FAIL" })) -Detail ($invalidResponse.headers -replace "`r?`n", " | ")
$results += New-Result -Check "Ungueltiger Token hat keinen Redirect" -State ($(if ($invalidResponse.headers -notmatch "^Location:") { "PASS" } else { "FAIL" })) -Detail ($invalidResponse.headers -replace "`r?`n", " | ")

$legacyResponse = Get-Response -Url $legacyUrl -Method "HEAD"
$results += New-Result -Check "Alte direkte Datei ist nicht mehr 200" -State ($(if ($legacyResponse.headers -match "^HTTP/.* (404|410) ") { "PASS" } else { "FAIL" })) -Detail ($legacyResponse.headers -replace "`r?`n", " | ")
$results += New-Result -Check "Alte direkte Datei leakt keinen Redirect" -State ($(if ($legacyResponse.headers -notmatch "^Location:") { "PASS" } else { "FAIL" })) -Detail ($legacyResponse.headers -replace "`r?`n", " | ")

$restResponse = Get-Response -Url $restUrl
$results += New-Result -Check "REST verschweigt Originaldateinamen" -State ($(if ($restResponse.body -notmatch "Foto_farbig|member-media-private|/media/public/members/") { "PASS" } else { "FAIL" })) -Detail "REST body inspected"
$results += New-Result -Check "REST zeigt keine Registry" -State ($(if ($restResponse.body -notmatch "by_source|by_legacy|storage_name|content_hash") { "PASS" } else { "FAIL" })) -Detail "REST body inspected"

$sitemapResponse = Get-Response -Url $sitemapUrl
$results += New-Result -Check "Sitemap enthaelt keine Mitgliederseite" -State ($(if ($sitemapResponse.body -notmatch "/mitglieder/") { "PASS" } else { "FAIL" })) -Detail $sitemapUrl
$results += New-Result -Check "Sitemap enthaelt keine Token-Bilder" -State ($(if ($sitemapResponse.body -notmatch "/member-media/") { "PASS" } else { "FAIL" })) -Detail $sitemapUrl
$results += New-Result -Check "Sitemap enthaelt keine alte Bild-URL" -State ($(if ($sitemapResponse.body -notmatch "/wp-content/uploads/avf-members/") { "PASS" } else { "FAIL" })) -Detail $sitemapUrl

$results | Format-Table -AutoSize
