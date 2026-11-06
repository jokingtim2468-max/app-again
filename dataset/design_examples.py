"""Hand-written, parameterized game-design examples: menus, maps, characters, design specs.

Writes data/raw/design.jsonl ({"id","lang","prompt","code","source":"hand-written"}) so verify.py
compiles every C# example and parse-checks Luau, plus data/design_specs.jsonl (prose GDD answers).
Templates use string.Template ($name) because Luau and C# both use braces.
"""
import json, pathlib, random
from string import Template as T

ROOT = pathlib.Path(__file__).resolve().parents[1]
rng = random.Random(11)
GAMES = ["Sky Raiders", "Dungeon Dash", "Neon Racers", "Frost Keep", "Pirate Cove", "Zombie Outpost",
         "Candy Kingdom", "Mech Arena", "Jungle Run", "Star Miners"]
THEMES = {"dark": ("Color3.fromRGB(20, 22, 30)", "Color3.fromRGB(90, 140, 255)", "new Color(0.08f, 0.09f, 0.12f)", "new Color(0.35f, 0.55f, 1f)"),
          "warm": ("Color3.fromRGB(45, 28, 20)", "Color3.fromRGB(255, 170, 60)", "new Color(0.18f, 0.11f, 0.08f)", "new Color(1f, 0.67f, 0.24f)"),
          "candy": ("Color3.fromRGB(255, 230, 245)", "Color3.fromRGB(255, 90, 170)", "new Color(1f, 0.9f, 0.96f)", "new Color(1f, 0.35f, 0.67f)"),
          "forest": ("Color3.fromRGB(18, 35, 24)", "Color3.fromRGB(110, 210, 120)", "new Color(0.07f, 0.14f, 0.09f)", "new Color(0.43f, 0.82f, 0.47f)")}

# ---------------------------------------------------------------- Luau (Roblox)
LUAU = {
"main_menu": ("Create a $theme-themed main menu for my Roblox game \"$game\" with Play, Settings and Quit-style buttons, hover animations, and a title.",
T('''--!strict
-- LocalScript in StarterPlayerScripts: main menu for "$game"
local Players = game:GetService("Players")
local TweenService = game:GetService("TweenService")

local player = Players.LocalPlayer
local BG, ACCENT = $bg, $accent

local gui = Instance.new("ScreenGui")
gui.Name = "MainMenu"
gui.IgnoreGuiInset = true
gui.ResetOnSpawn = false

local backdrop = Instance.new("Frame")
backdrop.Size = UDim2.fromScale(1, 1)
backdrop.BackgroundColor3 = BG
backdrop.Parent = gui

local title = Instance.new("TextLabel")
title.Text = "$game"
title.Font = Enum.Font.GothamBlack
title.TextScaled = true
title.TextColor3 = ACCENT
title.BackgroundTransparency = 1
title.AnchorPoint = Vector2.new(0.5, 0)
title.Position = UDim2.fromScale(0.5, 0.12)
title.Size = UDim2.fromScale(0.6, 0.15)
title.Parent = backdrop

local list = Instance.new("Frame")
list.AnchorPoint = Vector2.new(0.5, 0)
list.Position = UDim2.fromScale(0.5, 0.4)
list.Size = UDim2.fromScale(0.3, 0.4)
list.BackgroundTransparency = 1
list.Parent = backdrop

local layout = Instance.new("UIListLayout")
layout.Padding = UDim.new(0, 12)
layout.HorizontalAlignment = Enum.HorizontalAlignment.Center
layout.Parent = list

local function makeButton(text: string, order: number, onClick: () -> ())
	local button = Instance.new("TextButton")
	button.Text = text
	button.LayoutOrder = order
	button.Font = Enum.Font.GothamBold
	button.TextScaled = true
	button.TextColor3 = Color3.new(1, 1, 1)
	button.BackgroundColor3 = ACCENT
	button.Size = UDim2.new(1, 0, 0, $height)
	button.AutoButtonColor = false
	local corner = Instance.new("UICorner")
	corner.CornerRadius = UDim.new(0, 12)
	corner.Parent = button
	local info = TweenInfo.new(0.15, Enum.EasingStyle.Quad)
	button.MouseEnter:Connect(function()
		TweenService:Create(button, info, { Size = UDim2.new(1.05, 0, 0, $height + 6) }):Play()
	end)
	button.MouseLeave:Connect(function()
		TweenService:Create(button, info, { Size = UDim2.new(1, 0, 0, $height) }):Play()
	end)
	button.Activated:Connect(onClick)
	button.Parent = list
	return button
end

makeButton("Play", 1, function()
	TweenService:Create(backdrop, TweenInfo.new(0.4), { BackgroundTransparency = 1 }):Play()
	task.wait(0.4)
	gui.Enabled = false
end)
makeButton("Settings", 2, function()
	local settings = player.PlayerGui:FindFirstChild("SettingsMenu")
	if settings and settings:IsA("ScreenGui") then
		settings.Enabled = true
	end
end)
makeButton("Credits", 3, function()
	title.Text = "Made with love"
end)

gui.Parent = player:WaitForChild("PlayerGui")
''')),
"shop_menu": ("Build a scrolling shop menu in Roblox for \"$game\" that lists items with prices and fires a RemoteEvent to buy. Theme: $theme.",
T('''--!strict
-- LocalScript: shop UI. Server must validate purchases (never trust the client).
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

type Item = { id: string, name: string, price: number }
local ITEMS: { Item } = {
$items}

local buyRemote = ReplicatedStorage:WaitForChild("BuyItem") :: RemoteEvent
local player = Players.LocalPlayer

local gui = Instance.new("ScreenGui")
gui.Name = "ShopMenu"
gui.Enabled = false
gui.ResetOnSpawn = false

local panel = Instance.new("Frame")
panel.AnchorPoint = Vector2.new(0.5, 0.5)
panel.Position = UDim2.fromScale(0.5, 0.5)
panel.Size = UDim2.fromScale(0.5, 0.6)
panel.BackgroundColor3 = $bg
panel.Parent = gui
Instance.new("UICorner").Parent = panel

local scroll = Instance.new("ScrollingFrame")
scroll.Size = UDim2.new(1, -20, 1, -60)
scroll.Position = UDim2.fromOffset(10, 50)
scroll.BackgroundTransparency = 1
scroll.AutomaticCanvasSize = Enum.AutomaticSize.Y
scroll.CanvasSize = UDim2.new()
scroll.Parent = panel

local grid = Instance.new("UIGridLayout")
grid.CellSize = UDim2.fromOffset($cell, $cell)
grid.CellPadding = UDim2.fromOffset(8, 8)
grid.Parent = scroll

for _, item in ITEMS do
	local card = Instance.new("TextButton")
	card.Text = string.format("%s\\n%d coins", item.name, item.price)
	card.TextWrapped = true
	card.Font = Enum.Font.GothamMedium
	card.TextSize = 16
	card.BackgroundColor3 = $accent
	card.TextColor3 = Color3.new(1, 1, 1)
	card.Activated:Connect(function()
		buyRemote:FireServer(item.id)
	end)
	card.Parent = scroll
end

gui.Parent = player:WaitForChild("PlayerGui")
''')),
"settings_menu": ("Make a Roblox settings menu with a music volume slider-style +/- control and a toggle for $toggle. Use a $theme style.",
T('''--!strict
-- LocalScript: settings menu stored as player Attributes so other scripts can react.
local Players = game:GetService("Players")
local player = Players.LocalPlayer

local gui = Instance.new("ScreenGui")
gui.Name = "SettingsMenu"
gui.Enabled = false
gui.ResetOnSpawn = false

local panel = Instance.new("Frame")
panel.AnchorPoint = Vector2.new(0.5, 0.5)
panel.Position = UDim2.fromScale(0.5, 0.5)
panel.Size = UDim2.fromOffset(360, 220)
panel.BackgroundColor3 = $bg
panel.Parent = gui

local function label(text: string, y: number): TextLabel
	local l = Instance.new("TextLabel")
	l.Text = text
	l.Font = Enum.Font.Gotham
	l.TextSize = 18
	l.TextColor3 = Color3.new(1, 1, 1)
	l.BackgroundTransparency = 1
	l.Position = UDim2.fromOffset(16, y)
	l.Size = UDim2.fromOffset(200, 32)
	l.TextXAlignment = Enum.TextXAlignment.Left
	l.Parent = panel
	return l
end

local function button(text: string, x: number, y: number, onClick: () -> ())
	local b = Instance.new("TextButton")
	b.Text = text
	b.Size = UDim2.fromOffset(40, 32)
	b.Position = UDim2.fromOffset(x, y)
	b.BackgroundColor3 = $accent
	b.TextColor3 = Color3.new(1, 1, 1)
	b.Activated:Connect(onClick)
	b.Parent = panel
	return b
end

local volume = player:GetAttribute("MusicVolume") or $volume
local volumeLabel = label("", 20)
local function refresh()
	volumeLabel.Text = string.format("Music: %d%%", volume)
	player:SetAttribute("MusicVolume", volume)
end
button("-", 230, 20, function() volume = math.max(0, volume - 10); refresh() end)
button("+", 280, 20, function() volume = math.min(100, volume + 10); refresh() end)
refresh()

local enabled = player:GetAttribute("$attr") ~= false
local toggleLabel = label("", 70)
local function refreshToggle()
	toggleLabel.Text = "$toggle: " .. (if enabled then "On" else "Off")
	player:SetAttribute("$attr", enabled)
end
button("Tog", 255, 70, function() enabled = not enabled; refreshToggle() end)
refreshToggle()

button("X", 310, 170, function() gui.Enabled = false end)
gui.Parent = player:WaitForChild("PlayerGui")
''')),
"terrain_map": ("Generate a $size x $size stud procedural $biome map in Roblox using Terrain and noise, with water below height $water.",
T('''--!strict
-- Script in ServerScriptService: procedural $biome terrain.
local Terrain = workspace.Terrain
local SIZE, CELL, SEED = $size, 8, $seed
local WATER = $water

local function heightAt(x: number, z: number): number
	local n = math.noise(x / 120, z / 120, SEED) * 0.7 + math.noise(x / 40, z / 40, SEED + 1) * 0.3
	return math.floor((n + 0.5) * $amp)
end

for x = -SIZE / 2, SIZE / 2 - CELL, CELL do
	for z = -SIZE / 2, SIZE / 2 - CELL, CELL do
		local h = math.max(heightAt(x, z), 4)
		local surface = if h > $peak then Enum.Material.$high else Enum.Material.$low
		Terrain:FillBlock(CFrame.new(x, h / 2, z), Vector3.new(CELL, h, CELL), Enum.Material.$base)
		Terrain:FillBlock(CFrame.new(x, h, z), Vector3.new(CELL, 2, CELL), surface)
		if h < WATER then
			Terrain:FillBlock(CFrame.new(x, (h + WATER) / 2, z), Vector3.new(CELL, WATER - h, CELL), Enum.Material.Water)
		end
	end
	task.wait() -- yield so the server stays responsive
end
''')),
"obby_map": ("Write a Roblox script that builds an obby course of $count platforms with checkpoints every $every stages and kill bricks between them.",
T('''--!strict
-- Script: generates an obby. Checkpoints are SpawnLocations; touching a kill brick resets the character.
local Players = game:GetService("Players")
local folder = Instance.new("Folder")
folder.Name = "Obby"
folder.Parent = workspace

local rng = Random.new($seed)
local pos = Vector3.new(0, 10, 0)
for i = 1, $count do
	local isCheckpoint = i % $every == 0
	local part: BasePart = if isCheckpoint then Instance.new("SpawnLocation") else Instance.new("Part")
	part.Anchored = true
	part.Size = Vector3.new(rng:NextInteger(6, 10), 1, rng:NextInteger(6, 10))
	part.Position = pos
	part.Color = if isCheckpoint then Color3.fromRGB(80, 220, 120) else Color3.fromHSV(i / $count, 0.6, 0.9)
	part.Name = if isCheckpoint then "Checkpoint" .. i else "Stage" .. i
	part.Parent = folder

	local kill = Instance.new("Part")
	kill.Anchored = true
	kill.Size = Vector3.new(12, 0.5, 12)
	kill.Position = pos + Vector3.new(0, -8, $gap / 2)
	kill.Color = Color3.fromRGB(255, 40, 40)
	kill.Material = Enum.Material.Neon
	kill.Name = "KillBrick"
	kill.Touched:Connect(function(hit: BasePart)
		local humanoid = hit.Parent and hit.Parent:FindFirstChildOfClass("Humanoid")
		if humanoid and Players:GetPlayerFromCharacter(hit.Parent) then
			humanoid.Health = 0
		end
	end)
	kill.Parent = folder

	pos += Vector3.new(rng:NextNumber(-6, 6), rng:NextNumber(0, 3), $gap)
end
''')),
"sprint_character": ("Add sprinting to the Roblox character: hold $key to run at $run speed with stamina that drains and regenerates.",
T('''--!strict
-- LocalScript in StarterCharacterScripts: sprint with stamina.
local ContextActionService = game:GetService("ContextActionService")
local RunService = game:GetService("RunService")

local character = script.Parent
local humanoid = character:WaitForChild("Humanoid") :: Humanoid
local WALK, RUN = $walk, $run
local MAX_STAMINA, DRAIN, REGEN = 100, $drain, 15
local stamina = MAX_STAMINA
local sprinting = false

local function onSprint(_: string, state: Enum.UserInputState)
	sprinting = state == Enum.UserInputState.Begin
	return Enum.ContextActionResult.Pass
end
ContextActionService:BindAction("Sprint", onSprint, true, Enum.KeyCode.$key, Enum.KeyCode.ButtonL3)

RunService.Heartbeat:Connect(function(dt: number)
	local moving = humanoid.MoveDirection.Magnitude > 0
	if sprinting and moving and stamina > 0 then
		stamina = math.max(0, stamina - DRAIN * dt)
		humanoid.WalkSpeed = RUN
	else
		stamina = math.min(MAX_STAMINA, stamina + REGEN * dt)
		humanoid.WalkSpeed = WALK
	end
	character:SetAttribute("Stamina", stamina)
end)
''')),
"npc_patrol": ("Create a Roblox NPC $npc that patrols between waypoints using PathfindingService and waits $wait seconds at each.",
T('''--!strict
-- Script inside the NPC model ($npc). Waypoints: Parts in workspace.$folder.
local PathfindingService = game:GetService("PathfindingService")
local npc = script.Parent
local humanoid = npc:WaitForChild("Humanoid") :: Humanoid
local root = npc:WaitForChild("HumanoidRootPart") :: BasePart
local points = workspace:WaitForChild("$folder"):GetChildren()
table.sort(points, function(a, b) return a.Name < b.Name end)

humanoid.WalkSpeed = $speed
local path = PathfindingService:CreatePath({ AgentRadius = 2, AgentHeight = 5, AgentCanJump = true })

local function walkTo(target: Vector3)
	local ok = pcall(function() path:ComputeAsync(root.Position, target) end)
	if not ok or path.Status ~= Enum.PathStatus.Success then
		humanoid:MoveTo(target)
		humanoid.MoveToFinished:Wait()
		return
	end
	for _, wp in path:GetWaypoints() do
		if wp.Action == Enum.PathWaypointAction.Jump then
			humanoid.Jump = true
		end
		humanoid:MoveTo(wp.Position)
		humanoid.MoveToFinished:Wait()
	end
end

while npc.Parent do
	for _, p in points do
		if p:IsA("BasePart") then
			walkTo(p.Position)
			task.wait($wait)
		end
	end
end
''')),
"character_look": ("Make a Roblox server script that gives every player's character a $style look using HumanoidDescription (colors and scale).",
T('''--!strict
-- Script in ServerScriptService: applies a $style appearance on spawn.
local Players = game:GetService("Players")

local function style(character: Model)
	local humanoid = character:WaitForChild("Humanoid") :: Humanoid
	local desc = humanoid:GetAppliedDescription()
	desc.HeadColor = $c1
	desc.TorsoColor = $c2
	desc.LeftArmColor = $c1
	desc.RightArmColor = $c1
	desc.LeftLegColor = $c2
	desc.RightLegColor = $c2
	desc.HeightScale = $h
	desc.WidthScale = $w
	humanoid:ApplyDescription(desc)
end

Players.PlayerAdded:Connect(function(player)
	player.CharacterAppearanceLoaded:Connect(style)
end)
''')),
}

# ---------------------------------------------------------------- C# (Unity)
CS = {
"main_menu": ("Create a Unity main menu for \"$game\" with UI Toolkit: Play loads scene \"$scene\", Settings opens a panel, Quit exits. $theme colors.",
T('''using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.UIElements;

// Attach next to a UIDocument. Builds the menu in code so no UXML file is required.
[RequireComponent(typeof(UIDocument))]
public class MainMenu$cls : MonoBehaviour
{
    [SerializeField] string gameScene = "$scene";
    static readonly Color Background = $bg;
    static readonly Color Accent = $accent;
    VisualElement settingsPanel;

    void OnEnable()
    {
        var root = GetComponent<UIDocument>().rootVisualElement;
        root.Clear();
        root.style.backgroundColor = Background;
        root.style.alignItems = Align.Center;
        root.style.justifyContent = Justify.Center;

        var title = new Label("$game");
        title.style.fontSize = $font;
        title.style.color = Accent;
        title.style.unityFontStyleAndWeight = FontStyle.Bold;
        title.style.marginBottom = 40;
        root.Add(title);

        root.Add(MakeButton("Play", () => SceneManager.LoadScene(gameScene)));
        root.Add(MakeButton("Settings", () => settingsPanel.style.display =
            settingsPanel.style.display == DisplayStyle.None ? DisplayStyle.Flex : DisplayStyle.None));
        root.Add(MakeButton("Quit", Quit));

        settingsPanel = new VisualElement();
        settingsPanel.style.display = DisplayStyle.None;
        var volume = new Slider("Volume", 0f, 1f) { value = AudioListener.volume };
        volume.RegisterValueChangedCallback(e => AudioListener.volume = e.newValue);
        settingsPanel.Add(volume);
        root.Add(settingsPanel);
    }

    Button MakeButton(string text, System.Action onClick)
    {
        var b = new Button(onClick) { text = text };
        b.style.width = 260;
        b.style.height = $height;
        b.style.fontSize = 22;
        b.style.backgroundColor = Accent;
        b.style.color = Color.white;
        b.style.marginBottom = 12;
        b.RegisterCallback<MouseEnterEvent>(_ => b.style.scale = new Scale(new Vector3(1.05f, 1.05f, 1f)));
        b.RegisterCallback<MouseLeaveEvent>(_ => b.style.scale = new Scale(Vector3.one));
        return b;
    }

    static void Quit()
    {
        Application.Quit();
    }
}
''')),
"pause_menu": ("Write a Unity pause menu toggled with $key that freezes time and offers Resume and Main Menu (scene \"$scene\").",
T('''using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.UIElements;

[RequireComponent(typeof(UIDocument))]
public class PauseMenu$cls : MonoBehaviour
{
    [SerializeField] KeyCode toggleKey = KeyCode.$key;
    [SerializeField] string menuScene = "$scene";
    VisualElement overlay;
    bool paused;

    void OnEnable()
    {
        var root = GetComponent<UIDocument>().rootVisualElement;
        overlay = new VisualElement();
        overlay.style.position = Position.Absolute;
        overlay.style.left = 0; overlay.style.right = 0; overlay.style.top = 0; overlay.style.bottom = 0;
        overlay.style.backgroundColor = new Color(0f, 0f, 0f, 0.6f);
        overlay.style.alignItems = Align.Center;
        overlay.style.justifyContent = Justify.Center;
        overlay.Add(new Label("Paused") { style = { fontSize = 48, color = $accent } });
        overlay.Add(new Button(() => SetPaused(false)) { text = "Resume" });
        overlay.Add(new Button(() => { SetPaused(false); SceneManager.LoadScene(menuScene); }) { text = "Main Menu" });
        root.Add(overlay);
        SetPaused(false);
    }

    void Update()
    {
        if (Input.GetKeyDown(toggleKey)) SetPaused(!paused);
    }

    void SetPaused(bool value)
    {
        paused = value;
        Time.timeScale = value ? 0f : 1f;
        overlay.style.display = value ? DisplayStyle.Flex : DisplayStyle.None;
        UnityEngine.Cursor.lockState = value ? CursorLockMode.None : CursorLockMode.Locked;
        UnityEngine.Cursor.visible = value;
    }
}
''')),
"tilemap_map": ("Generate a $w x $h 2D $biome map in Unity with a Tilemap and Perlin noise (ground, $mid, and water tiles).",
T('''using UnityEngine;
using UnityEngine.Tilemaps;

public class TileMapGenerator$cls : MonoBehaviour
{
    [SerializeField] Tilemap tilemap;
    [SerializeField] TileBase waterTile;
    [SerializeField] TileBase groundTile;
    [SerializeField] TileBase featureTile; // $mid
    [SerializeField] int width = $w, height = $h;
    [SerializeField] float scale = $scale;
    [SerializeField] int seed = $seed;

    void Start() => Generate();

    [ContextMenu("Generate")]
    public void Generate()
    {
        tilemap.ClearAllTiles();
        var offset = new Vector2(seed * 13.37f, seed * 7.77f);
        for (int x = 0; x < width; x++)
        for (int y = 0; y < height; y++)
        {
            float n = Mathf.PerlinNoise(x / scale + offset.x, y / scale + offset.y);
            TileBase tile = n < $water ? waterTile : n > $feature ? featureTile : groundTile;
            tilemap.SetTile(new Vector3Int(x - width / 2, y - height / 2, 0), tile);
        }
    }
}
''')),
"terrain_map": ("Create a Unity script that sculpts a $res heightmap Terrain with layered Perlin noise for a $biome level, max height $max m.",
T('''using UnityEngine;

[RequireComponent(typeof(Terrain))]
public class TerrainGenerator$cls : MonoBehaviour
{
    [SerializeField] int resolution = $res;
    [SerializeField] float maxHeight = $max;
    [SerializeField] float scale = $scale;
    [SerializeField] int octaves = $oct;

    void Start()
    {
        var data = GetComponent<Terrain>().terrainData;
        data.heightmapResolution = resolution + 1;
        data.size = new Vector3(resolution, maxHeight, resolution);
        int n = data.heightmapResolution;
        var heights = new float[n, n];
        for (int y = 0; y < n; y++)
        for (int x = 0; x < n; x++)
        {
            float h = 0f, amp = 1f, freq = 1f, total = 0f;
            for (int o = 0; o < octaves; o++)
            {
                h += Mathf.PerlinNoise(x * freq / scale, y * freq / scale) * amp;
                total += amp; amp *= 0.5f; freq *= 2f;
            }
            heights[y, x] = h / total;
        }
        data.SetHeights(0, 0, heights);
    }
}
''')),
"minimap": ("Add a minimap to my Unity game: a top-down camera that follows the player at height $height and renders to a RenderTexture.",
T('''using UnityEngine;

[RequireComponent(typeof(Camera))]
public class Minimap$cls : MonoBehaviour
{
    [SerializeField] Transform target;
    [SerializeField] float height = $height;
    [SerializeField] float size = $size;
    [SerializeField] bool rotateWithTarget = $rot;

    void Awake()
    {
        var cam = GetComponent<Camera>();
        cam.orthographic = true;
        cam.orthographicSize = size;
        if (cam.targetTexture == null) cam.targetTexture = new RenderTexture(256, 256, 16);
    }

    void LateUpdate()
    {
        if (target == null) return;
        transform.position = target.position + Vector3.up * height;
        float yaw = rotateWithTarget ? target.eulerAngles.y : 0f;
        transform.rotation = Quaternion.Euler(90f, yaw, 0f);
    }
}
''')),
"character_controller": ("Write a Unity third-person character controller: WASD movement at $speed m/s, sprint x$sprint, jumping $jump m, gravity, camera-relative.",
T('''using UnityEngine;

[RequireComponent(typeof(CharacterController))]
public class PlayerMovement$cls : MonoBehaviour
{
    [SerializeField] Transform cameraTransform;
    [SerializeField] float speed = $speed;
    [SerializeField] float sprintMultiplier = $sprint;
    [SerializeField] float jumpHeight = $jump;
    [SerializeField] float gravity = -19.6f;
    [SerializeField] float turnSmooth = 0.1f;

    CharacterController controller;
    Vector3 velocity;
    float turnVelocity;

    void Awake() => controller = GetComponent<CharacterController>();

    void Update()
    {
        var input = new Vector3(Input.GetAxisRaw("Horizontal"), 0f, Input.GetAxisRaw("Vertical")).normalized;
        if (input.sqrMagnitude > 0.01f)
        {
            float camYaw = cameraTransform != null ? cameraTransform.eulerAngles.y : 0f;
            float targetYaw = Mathf.Atan2(input.x, input.z) * Mathf.Rad2Deg + camYaw;
            float yaw = Mathf.SmoothDampAngle(transform.eulerAngles.y, targetYaw, ref turnVelocity, turnSmooth);
            transform.rotation = Quaternion.Euler(0f, yaw, 0f);
            float s = speed * (Input.GetKey(KeyCode.LeftShift) ? sprintMultiplier : 1f);
            controller.Move(Quaternion.Euler(0f, targetYaw, 0f) * Vector3.forward * s * Time.deltaTime);
        }

        if (controller.isGrounded && velocity.y < 0f) velocity.y = -2f;
        if (controller.isGrounded && Input.GetButtonDown("Jump")) velocity.y = Mathf.Sqrt(jumpHeight * -2f * gravity);
        velocity.y += gravity * Time.deltaTime;
        controller.Move(velocity * Time.deltaTime);
    }
}
''')),
"npc_patrol": ("Make a Unity NPC ($npc) that patrols waypoints with a NavMeshAgent and chases the player within $range m.",
T('''using UnityEngine;
using UnityEngine.AI;

[RequireComponent(typeof(NavMeshAgent))]
public class NpcPatrol$cls : MonoBehaviour
{
    [SerializeField] Transform[] waypoints;
    [SerializeField] Transform player;
    [SerializeField] float chaseRange = $range;
    [SerializeField] float waitTime = $wait;

    NavMeshAgent agent;
    int index;
    float waitTimer;

    void Awake()
    {
        agent = GetComponent<NavMeshAgent>();
        agent.speed = $speed;
    }

    void Update()
    {
        if (player != null && Vector3.Distance(transform.position, player.position) < chaseRange)
        {
            agent.SetDestination(player.position);
            return;
        }
        if (waypoints == null || waypoints.Length == 0 || agent.pathPending) return;
        if (agent.remainingDistance <= agent.stoppingDistance)
        {
            waitTimer += Time.deltaTime;
            if (waitTimer < waitTime) return;
            waitTimer = 0f;
            index = (index + 1) % waypoints.Length;
            agent.SetDestination(waypoints[index].position);
        }
    }
}
''')),
"character_stats": ("Create a Unity ScriptableObject for $npc character stats (health $hp, damage $dmg, speed) and a component that takes damage and dies.",
T('''using System;
using UnityEngine;

[CreateAssetMenu(menuName = "Game/Character Stats $cls")]
public class CharacterStats$cls : ScriptableObject
{
    public string displayName = "$npc";
    public int maxHealth = $hp;
    public int damage = $dmg;
    public float moveSpeed = $speed;
}

public class Health$cls : MonoBehaviour
{
    [SerializeField] CharacterStats$cls stats;
    public int Current { get; private set; }
    public event Action<int, int> Changed;
    public event Action Died;

    void Awake() => Current = stats != null ? stats.maxHealth : 100;

    public void TakeDamage(int amount)
    {
        if (Current <= 0 || amount <= 0) return;
        Current = Mathf.Max(0, Current - amount);
        Changed?.Invoke(Current, stats != null ? stats.maxHealth : 100);
        if (Current == 0)
        {
            Died?.Invoke();
            Destroy(gameObject, 2f);
        }
    }
}
''')),
}

KEYS = ["LeftShift", "LeftControl", "Q", "E"]
UKEYS = ["Escape", "P", "Tab"]
BIOMES = [("forest", "Grass", "Rock", "Ground"), ("snow", "Snow", "Glacier", "Rock"), ("desert", "Sand", "Sandstone", "Sandstone"),
          ("volcanic", "Basalt", "CrackedLava", "Basalt"), ("swamp", "Mud", "LeafyGrass", "Ground")]
NPCS = ["Guard", "Goblin", "Robot Sentry", "Shopkeeper", "Zombie", "Knight", "Slime", "Pirate"]
STYLES = [("knight", "Color3.fromRGB(170,170,180)", "Color3.fromRGB(60,60,80)"), ("zombie", "Color3.fromRGB(110,160,90)", "Color3.fromRGB(70,50,40)"),
          ("robot", "Color3.fromRGB(200,200,210)", "Color3.fromRGB(40,120,220)"), ("pirate", "Color3.fromRGB(230,190,150)", "Color3.fromRGB(120,30,30)")]
ITEM_POOL = ["Speed Coil", "Gravity Coil", "Sword", "Pet Egg", "Jetpack", "Trail", "Double Jump", "Shield", "Magnet", "Hat"]


def luau_params(kind, i):
    g, (theme, th) = rng.choice(GAMES), rng.choice(list(THEMES.items()))
    b = rng.choice(BIOMES)
    p = dict(game=g, theme=theme, bg=th[0], accent=th[1], seed=rng.randint(1, 9999))
    if kind == "main_menu": p.update(height=rng.choice([48, 56, 64]))
    if kind == "shop_menu":
        items = rng.sample(ITEM_POOL, rng.randint(3, 6))
        p.update(cell=rng.choice([110, 130, 150]), items="".join(
            f'\t{{ id = "{n.lower().replace(" ", "_")}", name = "{n}", price = {rng.choice([50, 100, 250, 500, 1000])} }},\n' for n in items))
    if kind == "settings_menu":
        t = rng.choice(["Shadows", "Particles", "Camera Shake", "Damage Numbers"])
        p.update(toggle=t, attr=t.replace(" ", ""), volume=rng.choice([50, 70, 80]))
    if kind == "terrain_map":
        p.update(size=rng.choice([256, 512, 1024]), water=rng.choice([8, 12, 16]), amp=rng.choice([40, 60, 90]),
                 peak=rng.choice([35, 45, 55]), biome=b[0], low=b[1], high=b[2], base=b[3])
    if kind == "obby_map": p.update(count=rng.choice([20, 30, 50]), every=rng.choice([5, 10]), gap=rng.choice([14, 16, 18]))
    if kind == "sprint_character":
        p.update(key=rng.choice(KEYS), walk=16, run=rng.choice([24, 28, 32]), drain=rng.choice([20, 25, 35]))
    if kind == "npc_patrol":
        n = rng.choice(NPCS)
        p.update(npc=n, folder=n.replace(" ", "") + "Waypoints", speed=rng.choice([8, 10, 12]), wait=rng.choice([1, 2, 3]))
    if kind == "character_look":
        s = rng.choice(STYLES)
        p.update(style=s[0], c1=s[1], c2=s[2], h=rng.choice([0.9, 1, 1.1]), w=rng.choice([0.9, 1, 1.1]))
    return p


def cs_params(kind, i):
    g, (theme, th) = rng.choice(GAMES), rng.choice(list(THEMES.items()))
    p = dict(game=g, theme=theme, bg=th[2], accent=th[3], cls=str(i), seed=rng.randint(1, 9999),
             scene=rng.choice(["Level1", "Game", "World", "Arena"]))
    p.update(font=rng.choice([48, 64, 72]), height=rng.choice([48, 56]), key=rng.choice(UKEYS),
             w=rng.choice([64, 100, 128]), h=rng.choice([64, 100, 128]), scale=rng.choice(["12f", "18f", "25f"]),
             water=rng.choice(["0.3f", "0.35f"]), feature=rng.choice(["0.7f", "0.75f"]),
             mid=rng.choice(["trees", "rocks", "flowers"]), biome=rng.choice(["forest", "island", "canyon", "tundra"]),
             res=rng.choice([256, 512]), max=rng.choice(["40f", "80f", "120f"]), oct=rng.choice([3, 4, 5]),
             size=rng.choice(["25f", "40f"]), rot=rng.choice(["true", "false"]), speed=rng.choice(["4f", "5f", "6f"]),
             sprint=rng.choice(["1.5f", "1.8f"]), jump=rng.choice(["1.2f", "1.5f", "2f"]), npc=rng.choice(NPCS),
             range=rng.choice(["8f", "12f", "15f"]), wait=rng.choice(["1f", "2f"]), hp=rng.choice([50, 100, 250]),
             dmg=rng.choice([5, 10, 20]))
    p["height"] = p["height"] if kind != "minimap" else rng.choice(["30f", "50f"])
    return p


def fmt_prompt(t, p):
    return T(t.replace('"$game"', '"$game"')).safe_substitute(p)


out, PER = [], 18
for kind, (prompt, tmpl) in LUAU.items():
    for i in range(PER):
        p = luau_params(kind, i)
        out.append({"id": f"design_luau_{kind}_{i}", "lang": "luau", "prompt": fmt_prompt(prompt, p),
                    "code": tmpl.substitute(p).strip(), "source": "hand-written", "topic": kind})
for kind, (prompt, tmpl) in CS.items():
    for i in range(PER):
        p = cs_params(kind, i)
        out.append({"id": f"design_cs_{kind}_{i}", "lang": "csharp", "prompt": fmt_prompt(prompt, p),
                    "code": tmpl.substitute(p).strip(), "source": "hand-written", "topic": kind})
(ROOT / "data/raw").mkdir(parents=True, exist_ok=True)
(ROOT / "data/raw/design.jsonl").write_text("\n".join(json.dumps(r) for r in out) + "\n")

# ---------------------------------------------------------------- prose design specs (menus, maps, characters)
SPECS = []
for g in GAMES:
    genre = rng.choice(["obby", "tycoon", "survival", "arena shooter", "dungeon crawler", "racing"])
    eng = rng.choice(["Roblox", "Unity"])
    SPECS.append({"messages": [
        {"role": "system", "content": "You are a game-dev assistant. Give concrete, buildable design specs."},
        {"role": "user", "content": f"Design the menus, map and characters for {g}, a {genre} game in {eng}."},
        {"role": "assistant", "content": f"""# {g} - design spec ({genre}, {eng})

## Menus (flow: Title -> Main -> Play / Shop / Settings; Pause in-game)
- **Main menu:** game title top-center (15% height), 3 stacked buttons center (Play, Shop, Settings), 12 px spacing, hover = 5% scale-up in 0.15 s.
- **HUD:** health/stamina bars top-left, currency top-right, minimap bottom-right (256x256, top-down orthographic).
- **Pause:** dark overlay at 60% opacity, Resume / Settings / Main Menu; freezes time{' (Time.timeScale = 0)' if eng == 'Unity' else ' for single-player sections only - Roblox servers keep running'}.
- **Shop:** grid of item cards (icon, name, price); the server validates every purchase.
- **Settings:** music volume, SFX volume, graphics toggles (shadows, particles), camera sensitivity; saved per player.
- **Readability:** minimum 18 px text, 4.5:1 contrast, all buttons reachable by gamepad and touch.

## Map
- **Layout:** hub spawn in the center; 3 zones radiating out, each harder than the last; one landmark per zone visible from spawn for navigation.
- **Size:** {'about 1,024 x 1,024 studs' if eng == 'Roblox' else 'about 512 x 512 m'}; travel time to the farthest zone under 90 s.
- **Generation:** noise-based terrain for the base, hand-placed points of interest on top; water below the lowest walkable height.
- **Pacing:** checkpoint or safe spot every 60-90 s of play; dead ends hold rewards.

## Characters
- **Player:** humanoid, about {'5 studs' if eng == 'Roblox' else '1.8 m'} tall; walk {'16' if eng == 'Roblox' else '5 m/s'}, sprint x1.6 with stamina; jump to clear 1.2x body height.
- **Enemies:** 3 archetypes - grunt (low HP, melee), ranged (keeps distance), elite (high HP, telegraphed attacks). Each has a distinct silhouette and color.
- **NPCs:** shopkeeper at the hub, a guide at each zone entrance; patrol NPCs use pathfinding between named waypoints.
- **Art pipeline:** one reference image per angle (front, back, left, right, top, three-quarter) -> TRELLIS.2 -> Blender cleanup -> basic humanoid rig (29 bones) -> engine import.
- **Stats:** data-driven (ScriptableObject / ModuleScript table), so balance changes need no code edits.
"""}]})
(ROOT / "data/design_specs.jsonl").write_text("\n".join(json.dumps(s) for s in SPECS) + "\n")
print(f"code examples={len(out)} specs={len(SPECS)}")
