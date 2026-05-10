# Singapore Condo Price Tracker

Interactive dashboard for analysing Singapore private residential property transactions using data from the URA Data Service API.

**Live demo:** https://singaporeproperty20-26.netlify.app

---

## What it shows

- PSF price trends (2020–2026) by bedroom type
- Freehold vs Leasehold price comparison
- Transaction volume by tenure, district, and bedroom
- Top projects by average PSF
- Filters: district, bedroom type, size band, year, month, tenure, project

---

## Files

| File | Description |
|------|-------------|
| `index.html` | Main dashboard — open this in a browser |
| `dashboards/sg-condo-dashboard.html` | Alternate version of the dashboard |
| `dashboards/price-gap-dashboard.html` | Price gap / lease decay analysis dashboard |
| `fetch_ura_data.py` | Python script to pull fresh data from URA API |
| `fetch_ura_data.ps1` | PowerShell script to pull fresh data (Windows, no Python needed) |
| `ura_data.js` | *(not in repo — generated locally, see below)* |

---

## How to load real data

The dashboard ships with synthetic sample data. To load ~126,000 real URA transactions:

### Step 1 — Register for a free URA API key

1. Go to https://eservice.ura.gov.sg/maps/api/
2. Click **Get Access** and register for a free account
3. You will receive an **Access Key** by email

### Step 2 — Generate a daily token

The URA API requires a fresh token each day. Generate one with:

**PowerShell (Windows):**
```powershell
(Invoke-WebRequest -Uri "https://eservice.ura.gov.sg/uraDataService/insertNewToken/v1" -Headers @{"AccessKey"="YOUR_ACCESS_KEY"}).Content
```

**curl (Mac/Linux):**
```bash
curl "https://eservice.ura.gov.sg/uraDataService/insertNewToken/v1" -H "AccessKey: YOUR_ACCESS_KEY"
```

The response looks like: `{"Status":"Success","Message":"","Result":"YOUR_TOKEN_HERE"}` — copy the full `Result` value including any trailing characters.

> **Important:** Copy the token carefully — PowerShell output can truncate it. Use `.Content` not `Select-Object -ExpandProperty Content` to avoid truncation.

### Step 3 — Fetch the data

#### Option A — PowerShell (Windows, no Python required)

```powershell
cd "C:\path\to\LC_Real_estate"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\fetch_ura_data.ps1 -Key YOUR_ACCESS_KEY -Token "YOUR_DAILY_TOKEN"
```

#### Option B — Python

```bash
pip install requests
python fetch_ura_data.py --key YOUR_ACCESS_KEY --token YOUR_DAILY_TOKEN
```

#### Option C — Inline PowerShell (no script file needed)

If neither `fetch_ura_data.ps1` nor Python is available, paste this entire block into PowerShell (replace the key/token values):

```powershell
$key="YOUR_ACCESS_KEY"; $tok="YOUR_DAILY_TOKEN"; $h=@{AccessKey=$key;Token=$tok}; $SQM=10.7639; $ST=@{"1"="New Sale";"2"="Sub-sale";"3"="Resale"}; $PI=@("Condominium","Apartment","Executive Condominium"); function BR($a){$s=$a*$SQM;if($s-le 430){"Studio"}elseif($s-le 650){"1-Bedroom"}elseif($s-le 970){"2-Bedroom"}elseif($s-le 1300){"3-Bedroom"}elseif($s-le 2000){"4-Bedroom"}elseif($s-le 2800){"5-Bedroom"}else{"Penthouse"}}; function SB($s){if($s-lt 500){"< 500"}elseif($s-lt 600){"500-600"}elseif($s-lt 700){"600-700"}elseif($s-lt 800){"700-800"}elseif($s-lt 900){"800-900"}elseif($s-lt 1000){"900-1,000"}elseif($s-lt 1200){"1,000-1,200"}elseif($s-lt 1500){"1,200-1,500"}else{"> 1,500"}}; $all=[System.Collections.Generic.List[object]]::new(); 1..4|%{$b=$_; Write-Host "Fetching batch $b/4..."; try{$r=Invoke-RestMethod -Uri "https://eservice.ura.gov.sg/uraDataService/invokeUraDS/v1?service=PMI_Resi_Transaction&batch=$b" -Headers $h -TimeoutSec 60; foreach($p in $r.Result){foreach($t in $p.transaction){if($PI -notcontains $t.propertyType){continue}; $a=[double]($t.area-replace'[^\d.]',''); $pr=[double]($t.price-replace'[^\d.]',''); if($a-le 0-or$pr-le 0){continue}; $sf=[math]::Round($a*$SQM); $cd=$t.contractDate; if(-not$cd-or$cd.Length-ne 4){continue}; $mm=[int]$cd.Substring(0,2); $yy=[int]$cd.Substring(2,2); if($mm-lt 1-or$mm-gt 12){continue}; $all.Add([PSCustomObject]@{project=(Get-Culture).TextInfo.ToTitleCase($p.project.ToLower());district="D"+([string]$t.district).PadLeft(2,'0');tenureType=if($p.tenure-eq"freehold"){"Freehold"}else{"Leasehold"};tenure=$p.tenure;bedroomType=BR $a;sizeBand=SB $sf;size=$sf;psf=[math]::Round($pr/$sf);transactionValue=[math]::Round($pr/1000)*1000;year=2000+$yy;month=$mm;marketSegment=$p.marketSegment;propertyType=$t.propertyType;floorRange=$t.floorRange;saleType=if($ST.ContainsKey($t.typeOfSale)){$ST[$t.typeOfSale]}else{"Unknown"}})}}}catch{Write-Host "Error: $_"}}; Write-Host "Total: $($all.Count) records"; $cols=@("project","district","tenureType","tenure","bedroomType","sizeBand","size","psf","transactionValue","year","month","marketSegment","propertyType","floorRange","saleType"); $rows=$all|%{$r=$_;,($cols|%{$r.$_})}; $json=([PSCustomObject]@{cols=$cols;rows=$rows})|ConvertTo-Json -Depth 4 -Compress; Set-Content -Path "ura_data.js" -Value "// URA Real Data — $((Get-Date).ToString('yyyy-MM-dd')) — $($all.Count) records`nwindow.URA_DATA=$json;`n" -Encoding UTF8; Write-Host "Saved ura_data.js"
```

This saves `ura_data.js` in the current directory.

### Step 4 — Open the dashboard

Place `ura_data.js` in the same folder as `index.html`, then open `index.html` in your browser. The real data loads automatically.

> **Note:** `index.html` must be opened from the same folder as `ura_data.js`. If the dashboard still shows synthetic data, apply the patch below.

#### Fix: dashboard still shows synthetic data after adding ura_data.js

Browsers block `fetch()` calls on local `file://` URLs. If this happens, patch `index.html` to load `ura_data.js` as a script tag instead:

```powershell
(Get-Content "index.html" -Raw) -replace '(<script src="https://cdn\.jsdelivr\.net/npm/chart\.js[^"]*"></script>)', '$1`n  <script src="ura_data.js" onerror="void(0)"></script>' | Set-Content "index.html" -Encoding UTF8
```

Then refresh `index.html` in your browser.

---

## Deploying to Netlify

1. Run the fetch script to generate `ura_data.js`
2. Drag the folder containing both `index.html` and `ura_data.js` onto https://app.netlify.com/drop
3. Share the generated URL — anyone can view it without needing Python or an API key

---

## Known issues & workarounds

| Issue | Cause | Fix |
|-------|-------|-----|
| `python` not found on Windows | Windows Store alias intercepts the command | Use `fetch_ura_data.ps1` or the inline PowerShell block above |
| `git` not found on Windows | Git not installed | Download ZIP from GitHub or use the inline PowerShell block |
| CORS blocked in browser modal | Browsers block cross-origin API calls from `file://` | Use the PowerShell or Python script instead |
| Dashboard shows synthetic data after adding `ura_data.js` | Browser blocks `fetch()` on `file://` URLs | Apply the script-tag patch above |
| Token rejected (HTTP 403) | Token truncated when copying, or token already consumed | Regenerate token; use `.Content` in PowerShell to avoid truncation |

---

## Data source

URA (Urban Redevelopment Authority) — Singapore
https://eservice.ura.gov.sg/maps/api/

Data covers private residential transactions (Condominium, Apartment, Executive Condominium) from 2020 to the current quarter. API registration is free. A new token must be generated each day.
