<#
 Closed Claw <-> Antigravity WSL sync.
 Clones (or fast-forward pulls) the shared repo into the WSL workspace Antigravity opens,
 then bootstraps it and registers the MCP server in .agents/mcp_config.json.

   powershell -ExecutionPolicy Bypass -File scripts\antigravity_wsl_sync.ps1
   powershell -ExecutionPolicy Bypass -File scripts\antigravity_wsl_sync.ps1 -Branch claude/closed-claw-scaffold -Distro Ubuntu
#>
param(
  [string]$Repo = "https://github.com/jokingtim2468-max/app-again.git",
  [string]$Branch = "main",
  [string]$Distro = "",
  [string]$WslPath = "~/antigravity/app-again",
  [switch]$NoBootstrap
)
$ErrorActionPreference = "Stop"
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { throw "WSL not installed. Run: wsl --install" }
$d = @(); if ($Distro) { $d = @("-d", $Distro) }
$boot = if ($NoBootstrap) { "" } else { "&& bash closed-claw/scripts/setup_dev.sh" }
$script = @"
set -e
command -v git >/dev/null || (sudo apt-get update && sudo apt-get install -y git)
mkdir -p `$(dirname $WslPath)
if [ -d $WslPath/.git ]; then
  cd $WslPath && git fetch origin $Branch && git checkout $Branch && git pull --ff-only origin $Branch
else
  git clone --branch $Branch $Repo $WslPath && cd $WslPath
fi
cd $WslPath $boot
echo "READY: open \\\\wsl$\\<distro>$($WslPath.Replace('~','/home/'+'$USER')) in Antigravity (or: code/antigravity $WslPath)"
"@
wsl.exe @d -- bash -lc $script
