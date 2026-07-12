# Score any city on demand (~$0.20). Usage: .\check_city.ps1 "Moses Lake" WA
foreach ($n in "DATAFORSEO_LOGIN","DATAFORSEO_PASSWORD","SUPABASE_DB_URL") {
  $v = [Environment]::GetEnvironmentVariable($n, "User")
  if ($v) { Set-Item -Path "Env:$n" -Value $v }
}
$env:PYTHONIOENCODING = "utf-8"
py "$PSScriptRoot\check_city.py" @args
