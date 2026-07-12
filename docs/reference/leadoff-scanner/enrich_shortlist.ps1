# Fine-pass enrichment (RD + review velocity + trend) for a shortlist CSV.
# Usage: .\enrich_shortlist.ps1 shortlist.csv
foreach ($n in "DATAFORSEO_LOGIN","DATAFORSEO_PASSWORD","SUPABASE_DB_URL") {
  $v = [Environment]::GetEnvironmentVariable($n, "User")
  if ($v) { Set-Item -Path "Env:$n" -Value $v }
}
$env:PYTHONIOENCODING = "utf-8"
py "$PSScriptRoot\enrich_shortlist.py" @args
