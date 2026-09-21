# Loads .env (KEY=VALUE per line, gitignored) into the process environment,
# then starts the API server. No python-dotenv dependency required.
$envFile = Join-Path $PSScriptRoot ".env"

if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $name, $value = $line.Split("=", 2)
            [System.Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), "Process")
        }
    }
} else {
    Write-Warning ".env not found at $envFile -- GEMINI_API_KEY will not be set."
}

uvicorn netmigrate.api:app --reload
