`p024`: Unity Health Bar with UI Toolkit
Plan: Listen to a Health component's event and lerp the fill width smoothly.

C#

```
using UnityEngine;
using UnityEngine.UIElements;

public class HealthBarUI : MonoBehaviour
{
    private VisualElement fillBar;

    private void OnEnable()
    {
        var root = GetComponent<UIDocument>().rootVisualElement;
        fillBar = root.Q<VisualElement>("HealthFill");
    }

    public void UpdateHealth(float current, float max)
    {
        float pct = Mathf.Clamp01(current / max);
        fillBar.style.width = Length.Percent(pct * 100);
    }
}

```

Explanation: Updates UI Toolkit element widths dynamically to reflect health percentages.

`p025`: Dynamic Crosshair
Plan: Expand crosshair dimensions during movement and shrink when stationary.

C#

```
using UnityEngine;
using UnityEngine.UIElements;

public class DynamicCrosshair : MonoBehaviour
{
    private VisualElement crosshair;
    private float currentSize = 20f;

    private void Start()
    {
        var root = GetComponent<UIDocument>().rootVisualElement;
        crosshair = root.Q<VisualElement>("Crosshair");
    }

    private void Update()
    {
        bool isMoving = Input.GetAxis("Horizontal") != 0 || Input.GetAxis("Vertical") != 0;
        float targetSize = isMoving ? 40f : 20f;
        currentSize = Mathf.Lerp(currentSize, targetSize, Time.deltaTime * 10f);
        crosshair.style.width = currentSize;
        crosshair.style.height = currentSize;
    }
}

```

Explanation: Smoothly interpolates crosshair size based on player movement state.

`p026`: Ammo Counter with Reload Flash
Plan: Show current/max ammo and flash red when empty.

C#

```
using UnityEngine;
using UnityEngine.UIElements;

public class AmmoCounterUI : MonoBehaviour
{
    private Label ammoLabel;

    private void Start()
    {
        var root = GetComponent<UIDocument>().rootVisualElement;
        ammoLabel = root.Q<Label>("AmmoLabel");
    }

    public void UpdateAmmo(int current, int max)
    {
        ammoLabel.text = $"{current} / {max}";
        ammoLabel.style.color = current == 0 ? Color.red : Color.white;
    }
}

```

Explanation: Updates text and shifts text color dynamically when reloading is required.

`p027`: World Space Damage Numbers
Plan: Spawn floating damage numbers above enemies that face the camera and fade out over time.

C#

```
using UnityEngine;
using TMPro;

public class WorldDamageNumber : MonoBehaviour
{
    public void Initialize(int damage)
    {
        GetComponent<TextMeshPro>().text = damage.ToString();
        Destroy(gameObject, 1.0f);
    }

    private void Update()
    {
        transform.position += Vector3.up * Time.deltaTime;
        transform.LookAt(Camera.main.transform);
    }
}

```

Explanation: Moves text upwards and billboards it toward the main camera.

`p028`: Score Display Pop Effect
Plan: Scale up score label briefly every time it increases.

C#

```
using UnityEngine;
using UnityEngine.UIElements;
using System.Collections;

public class ScorePopupUI : MonoBehaviour
{
    private Label scoreLabel;

    private void Start()
    {
        var root = GetComponent<UIDocument>().rootVisualElement;
        scoreLabel = root.Q<Label>("ScoreLabel");
    }

    public IEnumerator PopEffect()
    {
        scoreLabel.style.scale = new Scale(new Vector3(1.3f, 1.3f, 1f));
        yield return new WaitForSeconds(0.1f);
        scoreLabel.style.scale = new Scale(new Vector3(1f, 1f, 1f));
    }
}

```

Explanation: Temporarily scales UI elements to emphasize score gains.

`p029`: Minimap Marker System
Plan: Register entities so they appear as colored dots on a minimap.

C#

```
using UnityEngine;

public class MinimapMarker : MonoBehaviour
{
    public enum MarkerType { Enemy, Pickup, Objective }
    public MarkerType type;
    
    private void OnEnable() => MinimapManager.Register(this);
    private void OnDisable() => MinimapManager.Unregister(this);
}

```

Explanation: Allows game objects to register themselves with a central minimap manager.

`p030`: Interaction Prompt
Plan: Show 'Press E to ' when looking at interactable objects within 3 meters.

C#

```
using UnityEngine;
using UnityEngine.UIElements;

public class InteractionPrompt : MonoBehaviour
{
    private Label promptLabel;
    public float range = 3f;

    private void Start()
    {
        var root = GetComponent<UIDocument>().rootVisualElement;
        promptLabel = root.Q<Label>("PromptLabel");
        promptLabel.style.display = DisplayStyle.None;
    }

    private void Update()
    {
        Ray ray = new Ray(Camera.main.transform.position, Camera.main.transform.forward);
        if (Physics.Raycast(ray, out RaycastHit hit, range))
        {
            if (hit.collider.CompareTag("Interactable"))
            {
                promptLabel.text = "Press E to interact";
                promptLabel.style.display = DisplayStyle.Flex;
                return;
            }
        }
        promptLabel.style.display = DisplayStyle.None;
    }
}

```

Explanation: Casts a ray from the camera to detect nearby interactable objects.

`p031`: Racing Game Timer HUD
Plan: Show current lap time, best lap, and lap count.

C#

```
using UnityEngine;
using UnityEngine.UIElements;

public class RacingHUD : MonoBehaviour
{
    private Label timerLabel;
    private float currentTime;

    private void Start()
    {
        var root = GetComponent<UIDocument>().rootVisualElement;
        timerLabel = root.Q<Label>("TimerLabel");
    }

    private void Update()
    {
        currentTime += Time.deltaTime;
        int minutes = Mathf.FloorToInt(currentTime / 60f);
        int seconds = Mathf.FloorToInt(currentTime % 60f);
        timerLabel.text = string.Format("{0:00}:{1:00}", minutes, seconds);
    }
}

```

Explanation: Tracks elapsed time and formats it neatly for racing HUD displays.
5:47
Unity UI Toolkit in 5 Minutes
YouTube · MadCat Tutorials
