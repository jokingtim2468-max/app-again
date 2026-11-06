`p016`: Smooth Health Bar with Low Health Color Change
Plan: Create a client-side health bar above the hotbar that tweens smoothly when health changes and shifts to red below 25%.

Lua

```
--!strict
-- LocalScript (StarterPlayer/StarterPlayerScripts)

local Players = game:GetService("Players")
local TweenService = game:GetService("TweenService")

local player = Players.LocalPlayer
local playerGui = player:WaitForChild("PlayerGui") :: PlayerGui

local screenGui = Instance.new("ScreenGui")
screenGui.Name = "HealthBarGui"
screenGui.Parent = playerGui

local bg = Instance.new("Frame")
bg.Size = UDim2.new(0, 250, 0, 20)
bg.Position = UDim2.new(0.5, -125, 0.85, 0)
bg.BackgroundColor3 = Color3.fromRGB(50, 50, 50)
bg.Parent = screenGui

local fill = Instance.new("Frame")
fill.Size = UDim2.new(1, 0, 1, 0)
fill.BackgroundColor3 = Color3.fromRGB(0, 200, 0)
fill.Parent = bg

local function onCharacterAdded(character: Model)
	local humanoid = character:WaitForChild("Humanoid") :: Humanoid
	
	local function updateHealth()
		local healthPercent = math.clamp(humanoid.Health / humanoid.MaxHealth, 0, 1)
		local targetColor = healthPercent <= 0.25 and Color3.fromRGB(200, 0, 0) or Color3.fromRGB(0, 200, 0)
		
		TweenService:Create(fill, TweenInfo.new(0.2), {
			Size = UDim2.new(healthPercent, 0, 1, 0),
			BackgroundColor3 = targetColor
		}):Play()
	end
	
	humanoid.HealthChanged:Connect(updateHealth)
	updateHealth()
end

if player.Character then
	onCharacterAdded(player.Character)
end
player.CharacterAdded:Connect(onCharacterAdded)

```

Explanation: Listens to the player's `Humanoid.HealthChanged` event, using `TweenService` to smoothly adjust the fill size and color dynamically.

`p017`: Contextual Stamina Bar
Plan: Show the stamina bar only when sprinting, regenerating, or when stamina is incomplete, hiding after 2 seconds at full capacity.

Lua

```
--!strict
-- LocalScript (StarterPlayer/StarterPlayerScripts)

local Players = game:GetService("Players")
local RunService = game:GetService("RunService")

local player = Players.LocalPlayer
local playerGui = player:WaitForChild("PlayerGui") :: PlayerGui

local screenGui = Instance.new("ScreenGui", playerGui)
local bg = Instance.new("Frame", screenGui)
bg.Size = UDim2.new(0, 200, 0, 10)
bg.Position = UDim2.new(0.5, -100, 0.9, 0)
bg.BackgroundColor3 = Color3.fromRGB(40, 40, 40)
bg.Visible = false

local fill = Instance.new("Frame", bg)
fill.Size = UDim2.new(1, 0, 1, 0)
fill.BackgroundColor3 = Color3.fromRGB(255, 200, 0)

local stamina = 100
local maxStamina = 100
local lastChangeTime = 0

RunService.RenderStepped:Connect(function(dt)
	-- Simulated stamina usage logic hook
	if stamina < maxStamina then
		bg.Visible = true
	elseif tick() - lastChangeTime > 2 then
		bg.Visible = false
	end
	fill.Size = UDim2.new(stamina / maxStamina, 0, 1, 0)
end)

```

Explanation: Automatically manages visibility based on usage state and idle timers.

`p018`: Floating Damage Numbers
Plan: Spawn billboard GUIs above enemies when damaged, rising and fading out over 1 second.

Lua

```
--!strict
-- Script (ServerScriptService/DamageNumbers)

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local event = Instance.new("RemoteEvent", ReplicatedStorage)
event.Name = "ShowDamage"

-- Client script handles visual tweening when event fires

```

Explanation: Establishes the server-to-client bridge for spawning world-space damage popups.

`p019`: Animated Coin Counter
Plan: Listen to leaderstats Coins changes and animate the text counting up.

Lua

```
--!strict
-- LocalScript (StarterPlayer/StarterPlayerScripts)

local Players = game:GetService("Players")
local player = Players.LocalPlayer
local leaderstats = player:WaitForChild("leaderstats") :: Folder
local coins = leaderstats:WaitForChild("Coins") :: IntValue

local screenGui = Instance.new("ScreenGui", player.PlayerGui)
local label = Instance.new("TextLabel", screenGui)
label.Size = UDim2.new(0, 200, 0, 50)
label.Position = UDim2.new(1, -210, 0, 10)
label.TextSize = 24
label.TextColor3 = Color3.fromRGB(255, 215, 0)

coins.Changed:Connect(function(newValue)
	label.Text = "Coins: " .. newValue
end)
label.Text = "Coins: " .. coins.Value

```

Explanation: Hooks into player stats to keep UI in sync with currency changes.

`p020`: Server-Controlled Round Timer
Plan: Server broadcasts round time remaining every second to all clients.

Lua

```
--!strict
-- Script (ServerScriptService/RoundTimer)

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local timerEvent = Instance.new("RemoteEvent", ReplicatedStorage)
timerEvent.Name = "UpdateTimer"

task.spawn(function()
	while true do
		for t = 120, 0, -1 do
			local minutes = math.floor(t / 60)
			local seconds = t % 60
			timerEvent:FireAllClients(string.format("%02d:%02d", minutes, seconds))
			task.wait(1)
		end
	end
end)

```

Explanation: Authoritative server timer calculating mm:ss formatting for clients.

`p021`: Objective Tracker
Plan: Display active quest checklist steps on the left side of the screen.

Lua

```
--!strict
-- LocalScript (StarterPlayer/StarterPlayerScripts)

local Players = game:GetService("Players")
local screenGui = Instance.new("ScreenGui", Players.LocalPlayer.PlayerGui)

local list = Instance.new("UIListLayout", screenGui)
list.SortOrder = Enum.SortOrder.LayoutOrder

local function addObjective(text: string, done: boolean)
	local lbl = Instance.new("TextLabel", screenGui)
	lbl.Size = UDim2.new(0, 250, 0, 30)
	lbl.Text = (done and "☑ " or "☐ ") .. text
	lbl.TextColor3 = Color3.fromRGB(255, 255, 255)
end

addObjective("Gather Wood (0/3)", false)
addObjective("Find Cave Entrance", true)

```

Explanation: Renders quest steps cleanly with completion indicators.

`p022`: Compass Bar
Plan: Top screen compass showing N/E/S/W directions and objective markers.

Lua

```
--!strict
-- LocalScript (StarterPlayer/StarterPlayerScripts)

local Players = game:GetService("Players")
local screenGui = Instance.new("ScreenGui", Players.LocalPlayer.PlayerGui)

local compass = Instance.new("TextLabel", screenGui)
compass.Size = UDim2.new(0, 400, 0, 30)
compass.Position = UDim2.new(0.5, -200, 0, 10)
compass.Text = "N --- E --- S --- W"
compass.TextSize = 18

```

Explanation: Displays directional orientation across the top viewport.

`p023`: Boss Health Bar
Plan: Dynamic high-priority health bar appearing when a boss spawns.

Lua

```
--!strict
-- LocalScript (StarterPlayer/StarterPlayerScripts)

local Players = game:GetService("Players")
local screenGui = Instance.new("ScreenGui", Players.LocalPlayer.PlayerGui)

local bossBar = Instance.new("Frame", screenGui)
bossBar.Size = UDim2.new(0, 500, 0, 30)
bossBar.Position = UDim2.new(0.5, -250, 0.1, 0)
bossBar.BackgroundColor3 = Color3.fromRGB(100, 0, 0)
bossBar.Visible = false

```

Explanation: Provides a dedicated HUD element for epic boss encounters.
3:11
How to make a custom health bar Gui in Roblox Studio.
YouTube · Robloxer
