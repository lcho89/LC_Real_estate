# fetch_ura_data.ps1
# Fetches URA private residential transaction data and saves as ura_data.js
# Usage: .\fetch_ura_data.ps1 -Key YOUR_KEY -Token YOUR_TOKEN

param(
    [string]$Key   = "",
    [string]$Token = "",
    [string]$Out   = "ura_data.js"
)

if (-not $Key)   { $Key   = Read-Host "URA Access Key" }
if (-not $Token) { $Token = Read-Host "Daily Token" }

$BASE_URL = "https://eservice.ura.gov.sg/uraDataService/invokeUraDS/v1"
$SQM_TO_SQFT = 10.7639

$SALE_TYPE = @{ "1"="New Sale"; "2"="Sub-sale"; "3"="Resale" }
$PROP_INCLUDE = @("Condominium","Apartment","Executive Condominium")

function Get-Bedroom($areaSqm) {
    $sqft = $areaSqm * $SQM_TO_SQFT
    if ($sqft -le 430)  { return "Studio" }
    if ($sqft -le 650)  { return "1-Bedroom" }
    if ($sqft -le 970)  { return "2-Bedroom" }
    if ($sqft -le 1300) { return "3-Bedroom" }
    if ($sqft -le 2000) { return "4-Bedroom" }
    if ($sqft -le 2800) { return "5-Bedroom" }
    return "Penthouse"
}

function Get-SizeBand($sqft) {
    if ($sqft -lt 500)  { return "< 500" }
    if ($sqft -lt 600)  { return "500-600" }
    if ($sqft -lt 700)  { return "600-700" }
    if ($sqft -lt 800)  { return "700-800" }
    if ($sqft -lt 900)  { return "800-900" }
    if ($sqft -lt 1000) { return "900-1,000" }
    if ($sqft -lt 1200) { return "1,000-1,200" }
    if ($sqft -lt 1500) { return "1,200-1,500" }
    return "> 1,500"
}

function Get-Tenure($raw) {
    if (-not $raw) { return @("Unknown","Unknown") }
    $s = $raw.Trim()
    if ($s.ToLower() -eq "freehold") { return @("Freehold","Freehold") }
    return @("Leasehold", $s)
}

function Get-ContractDate($d) {
    if (-not $d -or $d.Length -ne 4) { return $null }
    $mm = [int]$d.Substring(0,2)
    $yy = [int]$d.Substring(2,2)
    if ($mm -lt 1 -or $mm -gt 12) { return $null }
    return @{ year = 2000 + $yy; month = $mm }
}

function Format-ProjectName($raw) {
    $words = (Get-Culture).TextInfo.ToTitleCase($raw.ToLower()) -split ' '
    $small = @("At","Of","In","On","By","The","And","Or","A")
    $out = @()
    for ($i = 0; $i -lt $words.Count; $i++) {
        if ($i -gt 0 -and $small -contains $words[$i]) { $out += $words[$i].ToLower() }
        else { $out += $words[$i] }
    }
    return $out -join " "
}

$headers = @{ "AccessKey" = $Key; "Token" = $Token }
$BATCH_LABELS = @{ 1="Districts 01-07"; 2="Districts 08-14"; 3="Districts 15-21"; 4="Districts 22+" }
$allRecords = [System.Collections.Generic.List[object]]::new()

Write-Host ""
Write-Host "============================================================"
Write-Host "  URA Transaction Data Fetcher"
Write-Host "============================================================"
Write-Host ""

for ($batch = 1; $batch -le 4; $batch++) {
    $label = $BATCH_LABELS[$batch]
    Write-Host "  Fetching batch $batch/4  ($label) ... " -NoNewline
    try {
        $resp = Invoke-RestMethod -Uri "$BASE_URL`?service=PMI_Resi_Transaction&batch=$batch" `
                                  -Headers $headers -TimeoutSec 60
        if ($resp.Status -ne "Success") {
            Write-Host "API error: $($resp.Message)"
            continue
        }
        $count = 0
        foreach ($proj in $resp.Result) {
            if (-not $proj.project) { continue }
            $projName = Format-ProjectName $proj.project
            $tenure   = Get-Tenure $proj.tenure
            foreach ($tx in $proj.transaction) {
                if ($PROP_INCLUDE -notcontains $tx.propertyType) { continue }
                $areaSqm = [double]($tx.area   -replace '[^\d.]','')
                $price   = [double]($tx.price  -replace '[^\d.]','')
                if ($areaSqm -le 0 -or $price -le 0) { continue }
                $areaSqft = [math]::Round($areaSqm * $SQM_TO_SQFT)
                $psf      = [math]::Round($price / $areaSqft)
                $dt = Get-ContractDate $tx.contractDate
                if (-not $dt) { continue }
                $district = "D" + ([string]$tx.district).PadLeft(2,'0')
                $saleType = if ($SALE_TYPE.ContainsKey($tx.typeOfSale)) { $SALE_TYPE[$tx.typeOfSale] } else { "Unknown" }
                $allRecords.Add([PSCustomObject]@{
                    project          = $projName
                    district         = $district
                    tenureType       = $tenure[0]
                    tenure           = $tenure[1]
                    bedroomType      = Get-Bedroom $areaSqm
                    sizeBand         = Get-SizeBand $areaSqft
                    size             = $areaSqft
                    psf              = $psf
                    transactionValue = [math]::Round($price / 1000) * 1000
                    year             = $dt.year
                    month            = $dt.month
                    marketSegment    = $proj.marketSegment
                    propertyType     = $tx.propertyType
                    floorRange       = $tx.floorRange
                    saleType         = $saleType
                })
                $count++
            }
        }
        Write-Host "$count records"
    } catch {
        Write-Host "Error: $_"
    }
}

Write-Host ""
if ($allRecords.Count -eq 0) {
    Write-Host "  No records fetched. Check your Access Key and Token."
    exit 1
}

$years    = $allRecords | ForEach-Object { $_.year }    | Sort-Object -Unique
$projects = $allRecords | ForEach-Object { $_.project } | Sort-Object -Unique

Write-Host "  Total records : $($allRecords.Count.ToString('N0'))"
Write-Host "  Years         : $($years[0])-$($years[-1])"
Write-Host "  Projects      : $($projects.Count) unique"
Write-Host ""

# Build compact columnar JSON
$cols = @("project","district","tenureType","tenure","bedroomType","sizeBand",
          "size","psf","transactionValue","year","month",
          "marketSegment","propertyType","floorRange","saleType")

$rows = $allRecords | ForEach-Object {
    $r = $_
    ,($cols | ForEach-Object { $r.$_ })
}

$compact = [PSCustomObject]@{ cols = $cols; rows = $rows }
$json    = $compact | ConvertTo-Json -Depth 4 -Compress
$date    = (Get-Date).ToString("yyyy-MM-dd")

$content = "// URA Real Data — $date — $($allRecords.Count) records`nwindow.URA_DATA=$json;`n"
Set-Content -Path $Out -Value $content -Encoding UTF8

Write-Host "  Saved $($allRecords.Count.ToString('N0')) records -> $Out"
Write-Host ""
Write-Host "  Place '$Out' in the same folder as index.html and refresh."
Write-Host ""
