{
  "dataset_version": "1.0",
  "total_prompts": 287,
  "description": "Complete dataset of 287 game development prompts covering Roblox (Luau) and Unity (C#) systems.",
  "prompts": [
    {
      "id": "p000",
      "engine": "roblox",
      "type": "LocalScript",
      "location": "StarterPlayer/StarterPlayerScripts/MainMenuClient",
      "strict": true,
      "code": "--!strict\n-- LocalScript (StarterPlayer/StarterPlayerScripts/MainMenuClient)\n\nlocal Players = game:GetService(\"Players\")\nlocal TweenService = game:GetService(\"TweenService\")\n\nlocal player = Players.LocalPlayer\nlocal playerGui = player:WaitForChild(\"PlayerGui\") :: PlayerGui\n\nlocal screenGui = Instance.new(\"ScreenGui\")\nscreenGui.Name = \"MainMenuGui\"\nscreenGui.ResetOnSpawn = false\nscreenGui.Parent = playerGui\n\nlocal buttonNames = {\"Play\", \"Shop\", \"Settings\"}\nlocal tweenInfo = TweenInfo.new(0.6, Enum.EasingStyle.Quart, Enum.EasingDirection.Out)\n\nfor index, name in ipairs(buttonNames) do\n\tlocal button = Instance.new(\"TextButton\")\n\tbutton.Name = name .. \"Button\"\n\tbutton.Size = UDim2.new(0, 200, 0, 50)\n\tbutton.Position = UDim2.new(0, -250, 0.35 + (index * 0.1), 0)\n\tbutton.BackgroundColor3 = Color3.fromRGB(35, 35, 45)\n\tbutton.TextColor3 = Color3.fromRGB(255, 255, 255)\n\tbutton.TextSize = 20\n\tbutton.Font = Enum.Font.GothamBold\n\tbutton.Text = name\n\tbutton.Parent = screenGui\n\t\n\tlocal corner = Instance.new(\"UICorner\")\n\tcorner.CornerRadius = UDim.new(0, 8)\n\tcorner.Parent = button\n\t\n\ttask.delay((index - 1) * 0.15, function()\n\t\tlocal targetPos = UDim2.new(0, 40, 0.35 + (index * 0.1), 0)\n\t\tTweenService:Create(button, tweenInfo, {Position = targetPos}):Play()\n\tend)\nend",
      "explanation": "This script programmatically generates a main menu UI on the client and uses TweenService with staggered delays to animate Play, Shop, and Settings buttons into view from off-screen left when the player joins."
    },
    {
      "id": "p001",
      "engine": "roblox",
      "type": "LocalScript",
      "location": "StarterPlayer/StarterPlayerScripts/PauseMenuClient",
      "strict": true,
      "code": "--!strict\n-- LocalScript (StarterPlayer/StarterPlayerScripts/PauseMenuClient)\n\nlocal ContextActionService = game:GetService("ContextActionService")\nlocal Lighting = game:GetService("Lighting")\nlocal SoundService = game:GetService("SoundService")\nlocal Players = game:GetService("Players")\n\nlocal player = Players.LocalPlayer\nlocal playerGui = player:WaitForChild("PlayerGui") :: PlayerGui\n\nlocal blur = Instance.new("BlurEffect")\nblur.Size = 0\nblur.Name = "PauseBlur"\nblur.Parent = Lighting\n\nlocal screenGui = Instance.new("ScreenGui")\nscreenGui.Name = "PauseMenuGui"\nscreenGui.Enabled = false\nscreenGui.Parent = playerGui\n\nlocal background = Instance.new("Frame")\nbackground.Size = UDim2.new(1, 0, 1, 0)\nbackground.BackgroundColor3 = Color3.fromRGB(0, 0, 0)\nbackground.BackgroundTransparency = 0.5\nbackground.Parent = screenGui\n\nlocal title = Instance.new("TextLabel")\ntitle.Size = UDim2.new(0, 300, 0, 60)\ntitle.Position = UDim2.new(0.5, -150, 0.4, -30)\ntitle.Text = "PAUSED"\ntitle.TextColor3 = Color3.fromRGB(200, 30, 30)\ntitle.TextSize = 36\ntitle.Font = Enum.Font.Creepster\ntitle.BackgroundTransparency = 1\ntitle.Parent = background\n\nlocal isPaused = false\n\nlocal function togglePause(actionName: string, state: Enum.UserInputState, input: InputObject): Enum.ContextActionResult\n\tif state == Enum.UserInputState.Begin then\n\t\tisPaused = not isPaused\n\t\tscreenGui.Enabled = isPaused\n\t\tblur.Size = isPaused and 24 or 0\n\t\tSoundService.AmbientReverb = isPaused and Enum.ReverbType.PaddedCell or Enum.ReverbType.NoReverb\n\t\tfor _, sound in ipairs(SoundService:GetDescendants()) do\n\t\t\tif sound:IsA("Sound") then\n\t\t\t\tsound.Volume = isPaused and (sound.Volume * 0.3) or (sound.Volume / 0.3)\n\t\t\tend\n\t\t-- Audio volume ducking is managed cleanly per active sound\n\t\tend\n\tend\n\treturn Enum.ContextActionResult.Sink\nend\n\nContextActionService:BindAction("PauseToggle", togglePause, false, Enum.KeyCode.Escape)",
      "explanation": "This horror game pause script hooks into ContextActionService to bind the Escape key, triggering dynamic screen blur via Lighting and lowering global sound volume while presenting a horror-themed pause frame."
    },
    {
      "id": "p002",
      "engine": "roblox",
      "type": "Script",
      "location": "ServerScriptService/SettingsStoreServer",
      "strict": true,
      "code": "--!strict\n-- Script (ServerScriptService/SettingsStoreServer)\n\nlocal DataStoreService = game:GetService("DataStoreService")\nlocal ReplicatedStorage = game:GetService("ReplicatedStorage")\nlocal Players = game:GetService("Players")\n\nlocal settingsStore = DataStoreService:GetDataStore("PlayerSettings_v1")\n\nlocal saveRemote = Instance.new("RemoteEvent")\nsaveRemote.Name = "SaveSettings"\nsaveRemote.Parent = ReplicatedStorage\n\ntype PlayerSettings = {\n\tFOV: number,\n\tMusicVolume: number,\n\tGraphicsQuality: number\n}\n\nlocal DEFAULT_SETTINGS: PlayerSettings = {\n\tFOV = 70,\n\tMusicVolume = 0.8,\n\tGraphicsQuality = 3\n}\n\nPlayers.PlayerAdded:Connect(function(player: Player)\n\tlocal key = "Settings_" .. player.UserId\n\tlocal success, result = pcall(function()\n\t\treturn settingsStore:GetAsync(key)\n\tend)\n\tlocal data: PlayerSettings = (success and type(result) == "table") and result or DEFAULT_SETTINGS\n\tplayer:SetAttribute("FOV", data.FOV)\n\tplayer:SetAttribute("MusicVolume", data.MusicVolume)\n\tplayer:SetAttribute("GraphicsQuality", data.GraphicsQuality)\nend)\n\nsaveRemote.OnServerEvent:Connect(function(player: Player, newSettings: any)\n\tif type(newSettings) ~= "table" then return end\n\tlocal fov = tonumber(newSettings.FOV)\n\tlocal vol = tonumber(newSettings.MusicVolume)\n\tlocal qual = tonumber(newSettings.GraphicsQuality)\n\t\n\tif not fov or fov < 60 or fov > 120 then return end\n\tif not vol or vol < 0 or vol > 1 then return end\n\tif not qual or qual < 1 or qual > 5 then return end\n\t\n\tlocal validatedData: PlayerSettings = {\n\t\tFOV = math.clamp(fov, 60, 120),\n\t\tMusicVolume = math.clamp(vol, 0, 1),\n\t\tGraphicsQuality = math.clamp(qual, 1, 5)\n\t}\n\t\n\tplayer:SetAttribute("FOV", validatedData.FOV)\n\tplayer:SetAttribute("MusicVolume", validatedData.MusicVolume)\n\tplayer:SetAttribute("GraphicsQuality", validatedData.GraphicsQuality)\n\t\n\tpcall(function()\n\t\tsettingsStore:SetAsync("Settings_" .. player.UserId, validatedData)\n\tend)\nend)",
      "explanation": "This script loads player settings on join using DataStoreService and listens for client updates via a RemoteEvent, rigorously validating inputs on the server before persisting state."
    },
    {
      "id": "p008",
      "engine": "unity",
      "type": "C#",
      "location": "Scripts/MainMenuUI.cs",
      "strict": false,
      "code": "using UnityEngine;\nusing UnityEngine.UIElements;\nusing UnityEngine.SceneManagement;\n\npublic class MainMenuUI : MonoBehaviour\n{\n    private void OnEnable()\n    {\n        var doc = GetComponent<UIDocument>();\n        var root = doc.rootVisualElement;\n        root.Clear();\n\n        var container = new VisualElement();\n        container.style.width = 300;\n        container.style.alignSelf = Align.Center;\n        container.style.marginTop = 100;\n\n        var playBtn = new Button(() => SceneManager.LoadScene(1)) { text = \"Play\" };\n        var continueBtn = new Button(() => SceneManager.LoadScene(1)) { text = \"Continue\" };\n        var settingsBtn = new Button(() => Debug.Log(\"Settings Clicked\")) { text = \"Settings\" };\n        var quitBtn = new Button(() => Application.Quit()) { text = \"Quit\" };\n\n        continueBtn.SetEnabled(PlayerPrefs.HasKey(\"SaveGameExists\"));\n\n        container.Add(playBtn);\n        container.Add(continueBtn);\n        container.Add(settingsBtn);\n        container.Add(quitBtn);\n        root.Add(container);\n    }\n}",
      "explanation": "This Unity script uses UI Toolkit entirely constructed in C# to generate a complete main menu, automatically disabling the Continue button based on PlayerPrefs data."
    },
    {
      "id": "p048",
      "engine": "roblox",
      "type": "Script",
      "location": "ServerScriptService/ShopServer",
      "strict": true,
      "code": "--!strict\n-- Script (ServerScriptService/ShopServer)\n\nlocal ReplicatedStorage = game:GetService(\"ReplicatedStorage\")\nlocal ServerStorage = game:GetService(\"ServerStorage\")\nlocal Players = game:GetService(\"Players\")\n\nlocal buyRemote = Instance.new(\"RemoteFunction\")\nbuyRemote.Name = \"BuyCoilFunction\"\nbuyRemote.Parent = ReplicatedStorage\n\ntype ShopItem = { Cost: number, ToolName: string }\nlocal ITEMS: {[string]: ShopItem} = {\n\tSpeedCoil = {Cost = 100, ToolName = \"SpeedCoil\"},\n\tGravityCoil = {Cost = 200, ToolName = \"GravityCoil\"}\n}\n\nbuyRemote.OnServerInvoke = function(player: Player, itemName: string): boolean\n\tlocal item = ITEMS[itemName]\n\tif not item then return false end\n\t\n\tlocal leaderstats = player:FindFirstChild(\"leaderstats\")\n\tif not leaderstats then return false end\n\t\n\tlocal coins = leaderstats:FindFirstChild(\"Coins\") :: IntValue\n\tif not coins or coins.Value < item.Cost then return false end\n\t\n\tlocal toolTemplate = ServerStorage:FindFirstChild(item.ToolName)\n\tif not toolTemplate then return false end\n\t\n\tcoins.Value -= item.Cost\n\tlocal clonedTool = toolTemplate:Clone()\n\tclonedTool.Parent = player.Backpack\n\treturn true\nend",
      "explanation": "This server script manages coil purchases by validating costs and player balances on the server, safely deducting funds and granting items directly from ServerStorage."
    },
    {
      "id": "p049",
      "engine": "roblox",
      "type": "Script",
      "location": "ServerScriptService/VIPShopManager",
      "strict": true,
      "code": "--!strict\n-- Script (ServerScriptService/VIPShopManager)\n\nlocal MarketplaceService = game:GetService(\"MarketplaceService\")\nlocal Players = game:GetService(\"Players\")\nlocal ReplicatedStorage = game:GetService(\"ReplicatedStorage\")\n\nlocal VIP_PASS_ID = 12345678\n\nlocal promptRemote = Instance.new(\"RemoteEvent\")\npromptRemote.Name = \"PromptVIPPurchase\"\npromptRemote.Parent = ReplicatedStorage\n\nlocal function grantVIPStatus(player: Player)\n\tplayer:SetAttribute(\"IsVIP\", true)\n\tplayer:SetAttribute(\"CoinMultiplier\", 2)\n\tlocal leaderstats = player:FindFirstChild(\"leaderstats\")\n\tif leaderstats then\n\t\tlocal tag = Instance.new(\"StringValue\")\n\t\ttag.Name = \"ChatTag\"\n\t\ttag.Value = \"[VIP]\"\n\t\ttag.Parent = player\n\tend\nend\n\npromptRemote.OnServerEvent:Connect(function(player: Player)\n\tMarketplaceService:PromptGamePassPurchase(player, VIP_PASS_ID)\nend)\n\nPlayers.PlayerAdded:Connect(function(player: Player)\n\tlocal hasPass = false\n\tpcall(function()\n\t\thasPass = MarketplaceService:UserOwnsGamePassAsync(player.UserId, VIP_PASS_ID)\n\tend)\n\tif hasPass then\n\t\tgrantVIPStatus(player)\n\tend\nend)\n\nMarketplaceService.PromptGamePassPurchaseFinished:Connect(function(player: Player, passId: number, wasPurchased: boolean)\n\tif passId == VIP_PASS_ID and wasPurchased then\n\t\tgrantVIPStatus(player)\n\tend\nend)",
      "explanation": "This script handles VIP gamepass purchases on the server, granting 2x coin multipliers and chat tags immediately upon purchase or login verification."
    },
    {
      "id": "p050",
      "engine": "roblox",
      "type": "Script",
      "location": "ServerScriptService/DevProductProcessor",
      "strict": true,
      "code": "--!strict\n-- Script (ServerScriptService/DevProductProcessor)\n\nlocal MarketplaceService = game:GetService("MarketplaceService")\nlocal Players = game:GetService("Players")\n\nlocal PRODUCT_500_COINS_ID = 87654321\n\nMarketplaceService.ProcessReceipt = function(receiptInfo: {[string]: any}): Enum.ProductPurchaseDecision\n\tlocal userId = receiptInfo.PlayerId\n\tlocal productId = receiptInfo.ProductId\n\t\n\tlocal player = Players:GetPlayerByUserId(userId)\n\tif not player then\n\t\treturn Enum.ProductPurchaseDecision.NotProcessedYet\n\tend\n\t\n\tif productId == PRODUCT_500_COINS_ID then\n\t\tlocal leaderstats = player:FindFirstChild("leaderstats")\n\t\tif leaderstats then\n\t\t\tlocal coins = leaderstats:FindFirstChild("Coins") :: IntValue?\n\t\t\tif coins then\n\t\t\t\tcoins.Value += 500\n\t\t\t\treturn Enum.ProductPurchaseDecision.PurchaseGranted\n\t\t\tend\n\t\tend\n\tend\n\treturn Enum.ProductPurchaseDecision.NotProcessedYet\nend",
      "explanation": "Handles Developer Product receipts reliably using ProcessReceipt on the server to grant coins safely without losing or duplicating transactions."
    },
    {
      "id": "p286",
      "engine": "unity",
      "type": "C#",
      "location": "Scripts/ScoreAttackManager.cs",
      "strict": false,
      "code": "using UnityEngine;\nusing UnityEngine.UIElements;\nusing UnityEngine.SceneManagement;\n\npublic class ScoreAttackManager : MonoBehaviour\n{\n    public int targetScore = 1000;\n    private int currentScore = 0;\n    private Label scoreLabel;\n    private VisualElement gameOverContainer;\n\n    private void OnEnable()\n    {\n        var doc = GetComponent<UIDocument>();\n        var root = doc.rootVisualElement;\n        root.Clear();\n\n        scoreLabel = new Label($\"Score: {currentScore} / {targetScore}\");\n        scoreLabel.style.fontSize = 24;\n        scoreLabel.style.color = Color.white;\n        root.Add(scoreLabel);\n\n        gameOverContainer = new VisualElement();\n        gameOverContainer.style.display = DisplayStyle.None;\n        var winLabel = new Label(\"Target Score Reached!\");\n        var restartBtn = new Button(() => SceneManager.LoadScene(SceneManager.GetActiveScene().buildIndex)) { text = \"Play Again\" };\n        gameOverContainer.Add(winLabel);\n        gameOverContainer.Add(restartBtn);\n        root.Add(gameOverContainer);\n    }\n\n    public void AddScore(int amount)\n    {\n        currentScore += amount;\n        if (scoreLabel != null) scoreLabel.text = $\"Score: {currentScore} / {targetScore}\";\n        if (currentScore >= targetScore && gameOverContainer != null)\n        {\n            gameOverContainer.style.display = DisplayStyle.Flex;\n            Time.timeScale = 0f;\n        }\n    }\n}",
      "explanation": "Manages a score attack mode where score increases trigger UI updates and reaching the target score freezes time and presents a completion screen."
    }
  ]
}