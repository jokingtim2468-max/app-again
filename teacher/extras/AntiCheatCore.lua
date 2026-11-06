--!strict
-- ModuleScript (ServerScriptService/AntiCheatCore)
-- Server-authoritative anti-cheat + live patching toolkit for Roblox.
--
-- HONEST SCOPE: nothing can make cheating literally impossible, because the client is
-- always in the player's hands. This module makes cheating useless instead of invisible:
--   1. Secure remotes   - schema validation, rate limits, strikes (SecureRemote)
--   2. Movement checks  - speed / teleport / fly / noclip, with rubber-banding
--   3. Flag gating      - reward code asks AntiCheat.IsTrusted(player) before granting anything
--   4. Live patching    - thresholds and kill-switches are hot-updated from a DataStore config and a
--                         MessagingService channel, so you can tighten rules without restarting servers
--   5. Bans             - persisted, and broadcast to every running server
--
-- USAGE (from a Script):
--   local AC = require(game.ServerScriptService.AntiCheatCore)
--   AC.Start()
--   AC.SecureRemote("BuyItem", {"string", "number"}, function(player, itemId, qty) ... end)
--   if AC.IsTrusted(player) then grantCoins(player) end

local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local DataStoreService = game:GetService("DataStoreService")
local MessagingService = game:GetService("MessagingService")

export type Config = {
	version: number,
	maxSpeed: number,          -- studs/second the server will tolerate (walk speed + margin)
	maxVerticalSpeed: number,  -- upward studs/second without a jump/launch
	teleportDistance: number,  -- single-step distance that counts as a teleport
	maxRemotePerSecond: number,
	strikeLimitKick: number,
	strikeLimitBan: number,
	banOnLimit: boolean,
	movementChecks: boolean,
}

local DEFAULT_CONFIG: Config = {
	version = 1, maxSpeed = 40, maxVerticalSpeed = 70, teleportDistance = 60,
	maxRemotePerSecond = 20, strikeLimitKick = 6, strikeLimitBan = 12, banOnLimit = true, movementChecks = true,
}

local AntiCheat = {}
local config: Config = table.clone(DEFAULT_CONFIG)

local configStore = DataStoreService:GetDataStore("AntiCheatConfig_v1")
local banStore = DataStoreService:GetDataStore("AntiCheatBans_v1")
local CHANNEL = "AntiCheatBroadcast"

type PlayerState = {
	strikes: number,
	lastPosition: Vector3?,
	lastTime: number,
	graceUntil: number,
	remoteCount: number,
	remoteWindow: number,
}
local states: {[Player]: PlayerState} = {}
local trustedOverrides: {[Player]: boolean} = {}

local function retry<T>(fn: () -> T): (boolean, T?)
	for attempt = 1, 4 do
		local ok, result = pcall(fn)
		if ok then
			return true, result
		end
		task.wait(attempt)
	end
	return false, nil
end

local function log(player: Player?, reason: string)
	warn(string.format("[AntiCheat] %s: %s", player and player.Name or "server", reason))
end

-- Live patching ---------------------------------------------------------------------------------

local function applyConfig(incoming: any)
	if type(incoming) ~= "table" then
		return
	end
	if type(incoming.version) ~= "number" or incoming.version <= config.version then
		return -- only ever move forward; ignore stale or malformed patches
	end
	for key, default in DEFAULT_CONFIG do
		local value = incoming[key]
		if type(value) == type(default) then
			(config :: any)[key] = value
		end
	end
	log(nil, "config patched to version " .. tostring(config.version))
end

-- Publish a patch: AntiCheat.PublishConfig({version = 2, maxSpeed = 32}) from a trusted admin tool.
function AntiCheat.PublishConfig(patch: {[string]: any})
	local merged: any = table.clone(config)
	for key, value in patch do
		merged[key] = value
	end
	merged.version = (patch.version :: number?) or config.version + 1
	retry(function()
		configStore:SetAsync("current", merged)
		return true
	end)
	pcall(function()
		MessagingService:PublishAsync(CHANNEL, {kind = "config", config = merged})
	end)
	applyConfig(merged)
end

-- Strikes and punishment -----------------------------------------------------------------------

function AntiCheat.IsTrusted(player: Player): boolean
	local state = states[player]
	return state ~= nil and state.strikes < 3 and trustedOverrides[player] ~= false
end

local function ban(userId: number, reason: string)
	retry(function()
		banStore:SetAsync(tostring(userId), {reason = reason, time = os.time()})
		return true
	end)
	pcall(function()
		MessagingService:PublishAsync(CHANNEL, {kind = "ban", userId = userId})
	end)
end

local function strike(player: Player, reason: string, weight: number?)
	local state = states[player]
	if not state then
		return
	end
	state.strikes += weight or 1
	log(player, string.format("%s (strikes %d)", reason, state.strikes))
	if config.banOnLimit and state.strikes >= config.strikeLimitBan then
		ban(player.UserId, reason)
		player:Kick("Banned for exploiting.")
	elseif state.strikes >= config.strikeLimitKick then
		player:Kick("Kicked: suspicious activity detected.")
	end
end
AntiCheat.Strike = strike

-- Secure remotes ------------------------------------------------------------------------------

-- schema is a list of Luau type names ("string", "number", "boolean", "Instance", "table", "any").
function AntiCheat.SecureRemote(name: string, schema: {string}, handler: (Player, ...any) -> ()): RemoteEvent
	local remote = Instance.new("RemoteEvent")
	remote.Name = name
	remote.Parent = ReplicatedStorage
	remote.OnServerEvent:Connect(function(player: Player, ...: unknown)
		local state = states[player]
		if not state then
			return
		end
		local now = os.clock()
		if now - state.remoteWindow >= 1 then
			state.remoteWindow, state.remoteCount = now, 0
		end
		state.remoteCount += 1
		if state.remoteCount > config.maxRemotePerSecond then
			strike(player, "remote flood on " .. name, 2)
			return
		end
		local args = table.pack(...)
		if args.n ~= #schema then
			strike(player, "wrong argument count on " .. name)
			return
		end
		for index, expected in schema do
			local value = args[index]
			local actual = typeof(value)
			if expected ~= "any" and actual ~= expected then
				strike(player, string.format("bad arg %d on %s (%s)", index, name, actual))
				return
			end
			if actual == "number" and (value ~= value or math.abs(value :: number) == math.huge) then
				strike(player, "NaN or infinite number on " .. name)
				return
			end
		end
		handler(player, table.unpack(args, 1, args.n))
	end)
	return remote
end

-- Call this whenever legitimate code teleports or launches a player (spawn, checkpoint, vehicle).
function AntiCheat.Grace(player: Player, seconds: number)
	local state = states[player]
	if state then
		state.graceUntil = os.clock() + seconds
		state.lastPosition = nil
	end
end

-- Movement checks -------------------------------------------------------------------------------

local function checkMovement(player: Player, state: PlayerState, now: number)
	local character = player.Character
	local root = character and character:FindFirstChild("HumanoidRootPart")
	local humanoid = character and character:FindFirstChildOfClass("Humanoid")
	if not root or not root:IsA("BasePart") or not humanoid or humanoid.Health <= 0 then
		state.lastPosition = nil
		return
	end
	local position = root.Position
	local last = state.lastPosition
	local dt = now - state.lastTime
	state.lastPosition, state.lastTime = position, now
	if not last or dt <= 0 or now < state.graceUntil or humanoid.Sit then
		return
	end

	local delta = position - last
	local horizontal = Vector3.new(delta.X, 0, delta.Z).Magnitude / dt
	local allowed = math.max(config.maxSpeed, humanoid.WalkSpeed * 1.5)

	if delta.Magnitude > config.teleportDistance and dt < 1 then
		strike(player, "teleport " .. math.floor(delta.Magnitude) .. " studs", 3)
		root.CFrame = CFrame.new(last)
	elseif horizontal > allowed then
		strike(player, string.format("speed %.0f > %.0f", horizontal, allowed))
		root.CFrame = CFrame.new(last)
	elseif delta.Y / dt > config.maxVerticalSpeed and humanoid.FloorMaterial == Enum.Material.Air then
		strike(player, "vertical speed / fly")
		root.CFrame = CFrame.new(last)
	elseif delta.Magnitude > 1 then
		local params = RaycastParams.new()
		params.FilterType = Enum.RaycastFilterType.Exclude
		params.FilterDescendantsInstances = {character :: Instance}
		local hit = workspace:Raycast(last, delta, params)
		if hit and hit.Instance.CanCollide and hit.Instance.Transparency < 1 and delta.Magnitude > 6 then
			strike(player, "noclip through " .. hit.Instance.Name)
			root.CFrame = CFrame.new(last)
		end
	end
end

-- Lifecycle -------------------------------------------------------------------------------------

local started = false
function AntiCheat.Start()
	if started then
		return
	end
	started = true

	local ok, stored = retry(function()
		return configStore:GetAsync("current")
	end)
	if ok then
		applyConfig(stored)
	end
	pcall(function()
		MessagingService:SubscribeAsync(CHANNEL, function(message)
			local data: any = message.Data
			if type(data) ~= "table" then
				return
			end
			if data.kind == "config" then
				applyConfig(data.config)
			elseif data.kind == "ban" and type(data.userId) == "number" then
				local target = Players:GetPlayerByUserId(data.userId)
				if target then
					target:Kick("Banned for exploiting.")
				end
			end
		end)
	end)

	Players.PlayerAdded:Connect(function(player: Player)
		local isBanned, record = retry(function()
			return banStore:GetAsync(tostring(player.UserId))
		end)
		if isBanned and record then
			player:Kick("You are banned for exploiting.")
			return
		end
		states[player] = {strikes = 0, lastPosition = nil, lastTime = os.clock(), graceUntil = os.clock() + 5,
			remoteCount = 0, remoteWindow = os.clock()}
		player.CharacterAdded:Connect(function()
			AntiCheat.Grace(player, 3)
		end)
	end)
	Players.PlayerRemoving:Connect(function(player: Player)
		states[player] = nil
		trustedOverrides[player] = nil
	end)

	RunService.Heartbeat:Connect(function()
		if not config.movementChecks then
			return
		end
		local now = os.clock()
		for player, state in states do
			if now - state.lastTime >= 0.25 then
				checkMovement(player, state, now)
			end
		end
	end)
end

return AntiCheat
