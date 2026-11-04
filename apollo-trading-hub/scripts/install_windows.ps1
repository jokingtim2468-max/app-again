<#
  Apollo Trading - Windows installer builder.

  Installs what's missing (Git, Node.js LTS, Python 3.12) with winget, downloads/updates the code, builds the
  Apollo Trading setup wizard and runs it. The wizard installs the app with a Desktop shortcut and a Start Menu entry.
  On first launch the app sets up its own Python environment (1-3 minutes, once).

  Run in PowerShell:
    powershell -ExecutionPolicy Bypass -File .\install_windows.ps1
  Options:
    -Branch claude/apollo-trading-hub   (git branch to build)
    -Dir    $HOME\ApolloTrading          (where the code is kept)
    -Silent                              (install without the wizard pages)
#>
param(
  [string]$Branch = "claude/apollo-trading-hub",
  [string]$Dir = "$HOME\ApolloTrading",
  [string]$Repo = "https://github.com/jokingtim2468-max/app-again.git",
  [switch]$Silent
)
$ErrorActionPreference = "Stop"
function Step($t) { Write-Host "`n==> $t" -ForegroundColor Cyan }
function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function RefreshPath {
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
function Need($id, $cmd, $name) {
  if (Have $cmd) { Write-Host "  $name found" -ForegroundColor DarkGray; return }
  if (-not (Have "winget")) { throw "winget is missing. Install 'App Installer' from the Microsoft Store, then run this again." }
  Write-Host "  installing $name..."
  winget install -e --id $id --accept-source-agreements --accept-package-agreements --silent | Out-Host
  RefreshPath
  if (-not (Have $cmd)) { throw "$name installed but '$cmd' isn't on PATH yet. Close this window, open a new PowerShell and run the script again." }
}

Step "Checking tools"
Need "Git.Git" "git" "Git"
Need "OpenJS.NodeJS.LTS" "npm" "Node.js"
$py = (Have "py") -and ((& py -3.12 -c "print(1)" 2>$null) -eq "1")
if (-not $py) { Need "Python.Python.3.12" "py" "Python 3.12" }

Step "Getting the code ($Branch)"
if (Test-Path "$Dir\.git") {
  git -C $Dir fetch origin $Branch
  git -C $Dir checkout $Branch
  git -C $Dir pull --ff-only origin $Branch
} else {
  git clone --branch $Branch $Repo $Dir   # a GitHub sign-in window may open for a private repo
}
$fe = Join-Path $Dir "apollo-trading-hub\frontend"

Step "Building the Apollo Trading installer (a few minutes the first time)"
Push-Location $fe
try {
  if (Test-Path "package-lock.json") { npm ci --no-audit --no-fund } else { npm install --no-audit --no-fund }
  if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
  npm run dist:win
  if ($LASTEXITCODE -ne 0) { throw "building the installer failed" }
} finally { Pop-Location }

$setup = Get-ChildItem (Join-Path $fe "release") -Filter "Apollo-Trading-Setup-*.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $setup) { throw "installer not found in $fe\release" }

Step "Running the setup wizard: $($setup.Name)"
if ($Silent) { Start-Process $setup.FullName -ArgumentList "/S" -Wait } else { Start-Process $setup.FullName -Wait }

Write-Host "`nDone. Open 'Apollo Trading' from your Desktop or Start Menu." -ForegroundColor Green
Write-Host "Installer kept at: $($setup.FullName)"
Write-Host "Your data (accounts, logs, settings): $env:APPDATA\Apollo Trading"
