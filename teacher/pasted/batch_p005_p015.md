`p005`: Mobile-Friendly Main Menu
Plan: Detect screen width changes to switch button layout direction between horizontal (PC) and vertical (Mobile).

Lua

```
--!strict
-- LocalScript (StarterPlayer/StarterPlayerScripts)

local Players = game:GetService("Players")
local player = Players.LocalPlayer
local playerGui = player:WaitForChild("PlayerGui") :: PlayerGui

local screenGui = Instance.new("ScreenGui")
screenGui.Name = "ResponsiveMenu"
screenGui.Parent = playerGui

local layout = Instance.new("UIListLayout")
layout.SortOrder = Enum.SortOrder.LayoutOrder
layout.Padding = UDim.new(0, 10)
layout.Parent = screenGui

for i = 1, 3 do
	local btn = Instance.new("TextButton")
	btn.Size = UDim2.new(0, 180, 0, 50)
	btn.Text = "Button " .. i
	btn.Parent = screenGui
end

screenGui:GetPropertyChangedSignal("AbsoluteSize"):Connect(function()
	if screenGui.AbsoluteSize.X < 600 then
		layout.FillDirection = Enum.FillDirection.Vertical
	else
		layout.FillDirection = Enum.FillDirection.Horizontal
	end
end)

```

Explanation: Dynamically updates the `UIListLayout` fill direction based on the viewport width.

`p006`: Auto-Scrolling Credits Screen
Plan: Use `TweenService` to scroll a text container upwards smoothly with a Back button.

Lua

```
--!strict
-- LocalScript (StarterPlayer/StarterPlayerScripts)

local Players = game:GetService("Players")
local TweenService = game:GetService("TweenService")

local player = Players.LocalPlayer
local screenGui = Instance.new("ScreenGui", player.PlayerGui)

local scroll = Instance.new("ScrollingFrame")
scroll.Size = UDim2.new(0, 400, 0, 500)
scroll.Position = UDim2.new(0.5, -200, 0.5, -250)
scroll.CanvasSize = UDim2.new(0, 0, 0, 1000)
scroll.Parent = screenGui

local text = Instance.new("TextLabel")
text.Size = UDim2.new(1, 0, 0, 1000)
text.Text = "Lead Dev: Alex\nBuilder: Sam\nDesigner: Chris"
text.TextSize = 24
text.Parent = scroll

TweenService:Create(scroll, TweenInfo.new(15, Enum.EasingStyle.Linear), {CanvasPosition = Vector2.new(0, 500)}):Play()

```

Explanation: Tweens the `CanvasPosition` of a `ScrollingFrame` to produce a scrolling credits roll.

`p007`: Reusable Confirmation Popup Module
Plan: ModuleScript that returns a boolean via a callback when the user clicks Yes or No.

Lua

```
--!strict
-- ModuleScript (ReplicatedStorage/ConfirmDialog)

local Players = game:GetService("Players")
local module = {}

function module.Prompt(title: string, message: string): boolean
	local player = Players.LocalPlayer
	local gui = Instance.new("ScreenGui", player.PlayerGui)
	
	local frame = Instance.new("Frame", gui)
	frame.Size = UDim2.new(0, 300, 0, 150)
	frame.Position = UDim2.new(0.5, -150, 0.5, -75)
	
	local lbl = Instance.new("TextLabel", frame)
	lbl.Size = UDim2.new(1, 0, 0, 80)
	lbl.Text = message
	
	local yes = Instance.new("TextButton", frame)
	yes.Size = UDim2.new(0.4, 0, 0, 40)
	yes.Position = UDim2.new(0.05, 0, 0.65, 0)
	yes.Text = "Yes"
	
	local no = Instance.new("TextButton", frame)
	no.Size = UDim2.new(0.4, 0, 0, 40)
	no.Position = UDim2.new(0.55, 0, 0.65, 0)
	no.Text = "No"
	
	local result: boolean? = nil
	yes.MouseButton1Click:Connect(function() result = true end)
	no.MouseButton1Click:Connect(function() result = false end)
	
	while result == nil do
		task.wait(0.1)
	end
	
	gui:Destroy()
	return result
end

return module

```

Explanation: Spawns a modal dialog window and yields until the player makes a choice.

`p008`: Unity Main Menu with UI Toolkit
Plan: Query UI Toolkit elements, check PlayerPrefs for save data to enable Continue.

C#

```
using UnityEngine;
using UnityEngine.UIElements;
using UnityEngine.SceneManagement;

public class MainMenuUI : MonoBehaviour
{
    private void OnEnable()
    {
        var root = GetComponent<UIDocument>().rootVisualElement;
        var playBtn = root.Q<Button>("PlayButton");
        var continueBtn = root.Q<Button>("ContinueButton");
        var settingsBtn = root.Q<Button>("SettingsButton");
        var quitBtn = root.Q<Button>("QuitButton");

        continueBtn.SetEnabled(PlayerPrefs.HasKey("SaveData"));

        playBtn.clicked += () => SceneManager.LoadScene("GameScene");
        continueBtn.clicked += () => SceneManager.LoadScene("GameScene");
        settingsBtn.clicked += () => Debug.Log("Open Settings");
        quitBtn.clicked += Application.Quit;
    }
}

```

Explanation: Uses UI Toolkit to wire up menu buttons and conditionally enable "Continue".

`p009`: Settings Screen with PlayerPrefs
Plan: UI Toolkit sliders and toggles persisting values to `PlayerPrefs`.

C#

```
using UnityEngine;
using UnityEngine.UIElements;

public class SettingsUI : MonoBehaviour
{
    private void OnEnable()
    {
        var root = GetComponent<UIDocument>().rootVisualElement;
        var volumeSlider = root.Q<Slider>("VolumeSlider");
        var fullscreenToggle = root.Q<Toggle>("FullscreenToggle");

        volumeSlider.value = PlayerPrefs.GetFloat("Volume", 1.0f);
        fullscreenToggle.value = Screen.fullScreen;

        volumeSlider.RegisterValueChangedCallback(evt => {
            PlayerPrefs.SetFloat("Volume", evt.newValue);
            AudioListener.volume = evt.newValue;
        });

        fullscreenToggle.RegisterValueChangedCallback(evt => {
            Screen.fullScreen = evt.newValue;
        });
    }
}

```

Explanation: Binds UI Toolkit controls to live engine settings and saves them instantly.

`p010`: Pause Menu
Plan: Toggle time scale and pause overlay on Escape key press.

C#

```
using UnityEngine;
using UnityEngine.UIElements;
using UnityEngine.SceneManagement;

public class PauseMenu : MonoBehaviour
{
    private VisualElement root;
    private bool isPaused = false;

    private void Start()
    {
        root = GetComponent<UIDocument>().rootVisualElement;
        root.style.display = DisplayStyle.None;
        root.Q<Button>("ResumeButton").clicked += TogglePause;
        root.Q<Button>("QuitButton").clicked += () => SceneManager.LoadScene("MainMenu");
    }

    private void Update()
    {
        if (Input.GetKeyDown(KeyCode.Escape)) TogglePause();
    }

    private void TogglePause()
    {
        isPaused = !isPaused;
        root.style.display = isPaused ? DisplayStyle.Flex : DisplayStyle.None;
        Time.timeScale = isPaused ? 0 : 1;
    }
}

```

Explanation: Manages game pause state, time scaling, and UI visibility via Escape.

`p011`: Level-Select Menu
Plan: Dynamically generate buttons based on unlocked level count.

C#

```
using UnityEngine;
using UnityEngine.UIElements;
using UnityEngine.SceneManagement;

public class LevelSelectUI : MonoBehaviour
{
    private void OnEnable()
    {
        var root = GetComponent<UIDocument>().rootVisualElement;
        var container = root.Q<VisualElement>("LevelContainer");
        int unlockedLevels = PlayerPrefs.GetInt("UnlockedLevels", 1);

        for (int i = 1; i <= 5; i++)
        {
            int levelIndex = i;
            var btn = new Button(() => SceneManager.LoadScene("Level " + levelIndex));
            btn.text = "Level " + levelIndex;
            btn.SetEnabled(levelIndex <= unlockedLevels);
            container.Add(btn);
        }
    }
}

```

Explanation: Programmatically populates unlocked level buttons in UI Toolkit.

`p012`: Async Loading Screen
Plan: Load scene asynchronously and update a UI Toolkit progress bar/label.

C#

```
using UnityEngine;
using UnityEngine.UIElements;
using UnityEngine.SceneManagement;
using System.Collections;

public class LoadingScreen : MonoBehaviour
{
    private IEnumerator Start()
    {
        var root = GetComponent<UIDocument>().rootVisualElement;
        var progressLabel = root.Q<Label>("ProgressLabel");

        AsyncOperation op = SceneManager.LoadSceneAsync("GameScene");
        op.allowSceneActivation = false;

        while (!op.isDone)
        {
            float progress = Mathf.Clamp01(op.progress / 0.9f);
            progressLabel.text = $"Loading: {progress * 100:F0}%";

            if (op.progress >= 0.9f)
            {
                op.allowSceneActivation = true;
            }
            yield return null;
        }
    }
}

```

Explanation: Tracks asynchronous scene loading progress and displays percentage feedback.

`p013`: Game-Over Screen
Plan: Display scores and provide retry/menu options.

C#

```
using UnityEngine;
using UnityEngine.UIElements;
using UnityEngine.SceneManagement;

public class GameOverUI : MonoBehaviour
{
    public void ShowGameOver(int score, int bestScore)
    {
        var root = GetComponent<UIDocument>().rootVisualElement;
        root.style.display = DisplayStyle.Flex;

        root.Q<Label>("ScoreLabel").text = $"Score: {score}";
        root.Q<Label>("BestLabel").text = $"Best: {bestScore}";

        root.Q<Button>("RetryButton").clicked += () => SceneManager.LoadScene(SceneManager.GetActiveScene().name);
        root.Q<Button>("MenuButton").clicked += () => SceneManager.LoadScene("MainMenu");
    }
}

```

Explanation: Populates and reveals game-over statistics and navigation options.

`p014`: Reusable Confirmation Dialog
Plan: UI Toolkit dialog component with delegate callbacks.

C#

```
using UnityEngine;
using UnityEngine.UIElements;
using System;

public class ConfirmDialog : MonoBehaviour
{
    private VisualElement dialogBox;
    private Action onYesCallback;

    private void Awake()
    {
        var root = GetComponent<UIDocument>().rootVisualElement;
        dialogBox = root.Q<VisualElement>("DialogBox");
        dialogBox.style.display = DisplayStyle.None;

        root.Q<Button>("YesButton").clicked += () => { onYesCallback?.Invoke(); Hide(); };
        root.Q<Button>("NoButton").clicked += Hide;
    }

    public void Show(string message, Action onYes)
    {
        dialogBox.style.display = DisplayStyle.Flex;
        dialogBox.Q<Label>("MessageLabel").text = message;
        onYesCallback = onYes;
    }

    private void Hide() => dialogBox.style.display = DisplayStyle.None;
}

```

Explanation: Encapsulates confirmation popup logic with action callbacks.

`p015`: Key-Rebinding Menu
Plan: Capture key presses and save custom keybinds via PlayerPrefs.

C#

```
using UnityEngine;
using UnityEngine.UIElements;
using System;

public class KeyRebindUI : MonoBehaviour
{
    private string bindingKey = "";

    private void OnEnable()
    {
        var root = GetComponent<UIDocument>().rootVisualElement;
        root.Q<Button>("JumpRebind").clicked += () => StartRebind("JumpKey");
    }

    private void StartRebind(string keyName)
    {
        bindingKey = keyName;
    }

    private void OnGUI()
    {
        if (string.IsNullOrEmpty(bindingKey)) return;

        Event e = Event.current;
        if (e.isKey)
        {
            PlayerPrefs.SetString(bindingKey, e.keyCode.ToString());
            PlayerPrefs.Save();
            bindingKey = "";
        }
    }
}

```

Explanation: Listens for the next key press event to update and store control keybindings.
