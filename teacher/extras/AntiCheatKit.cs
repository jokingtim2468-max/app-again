// AntiCheatKit.cs - Unity 2021.3+ (C# 9). Drop into Assets/. Works for PC/Steam, Quest/SteamVR (VR) and mobile builds.
//
// HONEST SCOPE: client-side checks (ObscuredInt, ClockGuard, IntegrityGuard) only raise the cost of casual cheating.
// The checks that actually hold are the SERVER-SIDE ones: MovementValidator, VrPoseValidator, RateLimiter and
// server-owned state. Run those on your dedicated/host server (Netcode, Mirror, Photon, Steam Networking...) and never
// let a client decide health, damage, currency, inventory or match results.
using System;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Text;
using UnityEngine;

namespace AntiCheatKit
{
    /// <summary>Central place to react to detections: log, strike, kick, ban, upload telemetry.</summary>
    public static class CheatEvents
    {
        public static event Action<string> OnDetected;

        public static void Report(string reason)
        {
            Debug.LogWarning("[AntiCheat] " + reason);
            if (OnDetected != null) OnDetected(reason);
        }
    }

    // ---------------------------------------------------------------- memory-tamper protection (client)

    /// <summary>Int that is stored XOR-encrypted with a random key plus a decoy copy; Cheat Engine edits are detected.</summary>
    [Serializable]
    public struct ObscuredInt
    {
        private static readonly System.Random Rng = new System.Random();
        private int key;
        private int hidden;
        private int decoy;

        public ObscuredInt(int value)
        {
            key = Rng.Next(int.MinValue, int.MaxValue);
            hidden = value ^ key;
            decoy = value;
        }

        public int Value
        {
            get
            {
                int real = hidden ^ key;
                if (real != decoy) CheatEvents.Report("ObscuredInt tampered (decoy " + decoy + " vs real " + real + ")");
                return real;
            }
            set { this = new ObscuredInt(value); }
        }

        public static implicit operator ObscuredInt(int v) { return new ObscuredInt(v); }
        public static implicit operator int(ObscuredInt v) { return v.Value; }
    }

    [Serializable]
    public struct ObscuredFloat
    {
        private static readonly System.Random Rng = new System.Random();
        private int key;
        private int hidden;
        private float decoy;

        public ObscuredFloat(float value)
        {
            key = Rng.Next(int.MinValue, int.MaxValue);
            hidden = BitConverter.SingleToInt32Bits(value) ^ key;
            decoy = value;
        }

        public float Value
        {
            get
            {
                float real = BitConverter.Int32BitsToSingle(hidden ^ key);
                if (!Mathf.Approximately(real, decoy)) CheatEvents.Report("ObscuredFloat tampered");
                return real;
            }
            set { this = new ObscuredFloat(value); }
        }

        public static implicit operator ObscuredFloat(float v) { return new ObscuredFloat(v); }
        public static implicit operator float(ObscuredFloat v) { return v.Value; }
    }

    // ---------------------------------------------------------------- server-side validators

    public enum Verdict { Ok, Corrected, Kick }

    /// <summary>Server-side check of a client's reported position: speed, teleport and strike counting.</summary>
    public class MovementValidator
    {
        private class State { public Vector3 pos; public double time; public int strikes; public double graceUntil; }

        private readonly Dictionary<ulong, State> states = new Dictionary<ulong, State>();
        public float MaxSpeed = 12f;           // metres per second you will ever allow (sprint + margin)
        public float TeleportDistance = 25f;
        public int StrikesToKick = 8;

        public void Grace(ulong clientId, double nowSeconds, double seconds)
        {
            State s;
            if (states.TryGetValue(clientId, out s)) { s.graceUntil = nowSeconds + seconds; }
        }

        public void Remove(ulong clientId) { states.Remove(clientId); }

        /// <summary>Returns Ok, or Corrected with the position the server should snap the player back to.</summary>
        public Verdict Validate(ulong clientId, Vector3 reported, double nowSeconds, out Vector3 corrected)
        {
            corrected = reported;
            State s;
            if (!states.TryGetValue(clientId, out s))
            {
                states[clientId] = new State { pos = reported, time = nowSeconds, graceUntil = nowSeconds + 3 };
                return Verdict.Ok;
            }

            double dt = Math.Max(nowSeconds - s.time, 0.001);
            float distance = Vector3.Distance(s.pos, reported);
            float horizontal = Vector2.Distance(new Vector2(s.pos.x, s.pos.z), new Vector2(reported.x, reported.z));
            bool grace = nowSeconds < s.graceUntil;

            if (!grace && (distance > TeleportDistance || horizontal / dt > MaxSpeed))
            {
                s.strikes++;
                CheatEvents.Report("client " + clientId + " moved " + distance.ToString("0.0") + "m in " + dt.ToString("0.00") + "s");
                corrected = s.pos;
                s.time = nowSeconds;
                return s.strikes >= StrikesToKick ? Verdict.Kick : Verdict.Corrected;
            }

            s.pos = reported;
            s.time = nowSeconds;
            return Verdict.Ok;
        }
    }

    /// <summary>VR-specific plausibility: head and hand tracking cannot teleport, stretch past arm length, or leave the room.</summary>
    public class VrPoseValidator
    {
        private class State { public Vector3 head, left, right; public double time; public int strikes; }

        private readonly Dictionary<ulong, State> states = new Dictionary<ulong, State>();
        public float MaxHeadSpeed = 15f;       // m/s (includes artificial locomotion)
        public float MaxHandSpeed = 30f;       // m/s (a fast swing)
        public float MaxArmReach = 1.6f;       // metres from head to controller
        public float MinHeadHeight = 0.2f, MaxHeadHeight = 2.8f; // relative to the tracking-space floor

        public bool Validate(ulong clientId, Vector3 head, Vector3 left, Vector3 right, double now, out string reason)
        {
            reason = null;
            State s;
            if (!states.TryGetValue(clientId, out s))
            {
                states[clientId] = new State { head = head, left = left, right = right, time = now };
                return true;
            }

            double dt = Math.Max(now - s.time, 0.001);
            if (Vector3.Distance(s.head, head) / dt > MaxHeadSpeed) reason = "head moved too fast";
            else if (Vector3.Distance(s.left, left) / dt > MaxHandSpeed || Vector3.Distance(s.right, right) / dt > MaxHandSpeed) reason = "hand moved too fast";
            else if (Vector3.Distance(head, left) > MaxArmReach || Vector3.Distance(head, right) > MaxArmReach) reason = "impossible arm reach";
            else if (head.y < MinHeadHeight || head.y > MaxHeadHeight) reason = "head height out of range";

            if (reason != null)
            {
                s.strikes++;
                CheatEvents.Report("VR client " + clientId + ": " + reason);
                return false; // caller should ignore this pose and keep the last valid one
            }

            s.head = head; s.left = left; s.right = right; s.time = now;
            return true;
        }

        public void Remove(ulong clientId) { states.Remove(clientId); }
    }

    /// <summary>Token-bucket limiter for network messages (fire, buy, chat, emote...).</summary>
    public class RateLimiter
    {
        private class Bucket { public double tokens; public double last; }

        private readonly Dictionary<string, Bucket> buckets = new Dictionary<string, Bucket>();
        private readonly double capacity;
        private readonly double refillPerSecond;

        public RateLimiter(double capacity, double refillPerSecond)
        {
            this.capacity = capacity;
            this.refillPerSecond = refillPerSecond;
        }

        public bool Allow(ulong clientId, string action, double nowSeconds)
        {
            string key = clientId + ":" + action;
            Bucket b;
            if (!buckets.TryGetValue(key, out b))
            {
                b = new Bucket { tokens = capacity, last = nowSeconds };
                buckets[key] = b;
            }
            b.tokens = Math.Min(capacity, b.tokens + (nowSeconds - b.last) * refillPerSecond);
            b.last = nowSeconds;
            if (b.tokens < 1) return false;
            b.tokens -= 1;
            return true;
        }
    }

    // ---------------------------------------------------------------- local saves, clock and integrity

    /// <summary>HMAC-SHA256 signing of save strings. The secret lives in the client, so this stops casual
    /// file edits only; real progression and purchases must be stored server-side.</summary>
    public static class SignedStore
    {
        public static string Sign(string payload, string secret)
        {
            using (HMACSHA256 hmac = new HMACSHA256(Encoding.UTF8.GetBytes(secret)))
            {
                byte[] sig = hmac.ComputeHash(Encoding.UTF8.GetBytes(payload));
                return Convert.ToBase64String(sig) + "." + Convert.ToBase64String(Encoding.UTF8.GetBytes(payload));
            }
        }

        public static bool TryVerify(string signed, string secret, out string payload)
        {
            payload = null;
            string[] parts = signed.Split('.');
            if (parts.Length != 2) return false;
            string candidate = Encoding.UTF8.GetString(Convert.FromBase64String(parts[1]));
            string expected = Sign(candidate, secret);
            if (!string.Equals(expected, signed, StringComparison.Ordinal)) return false;
            payload = candidate;
            return true;
        }
    }

    /// <summary>Detects system-clock rewinds and speed hacks by comparing wall-clock time with a monotonic timer.</summary>
    public class ClockGuard : MonoBehaviour
    {
        [SerializeField] private float toleranceSeconds = 2f;
        private DateTime lastUtc;
        private float lastReal;

        private void Start()
        {
            lastUtc = DateTime.UtcNow;
            lastReal = Time.realtimeSinceStartup;
        }

        private void Update()
        {
            DateTime utc = DateTime.UtcNow;
            float real = Time.realtimeSinceStartup;
            double wallDelta = (utc - lastUtc).TotalSeconds;
            double monoDelta = real - lastReal;
            if (Math.Abs(wallDelta - monoDelta) > toleranceSeconds)
            {
                CheatEvents.Report("clock mismatch: wall " + wallDelta.ToString("0.0") + "s vs monotonic " + monoDelta.ToString("0.0") + "s");
            }
            lastUtc = utc;
            lastReal = real;
        }
    }

    /// <summary>Cheap environment checks. Treat results as signals to send to your server, not as proof.</summary>
    public class IntegrityGuard : MonoBehaviour
    {
        private void Start()
        {
            if (System.Diagnostics.Debugger.IsAttached) CheatEvents.Report("debugger attached");
            if (Application.genuineCheckAvailable && !Application.genuine) CheatEvents.Report("build files modified");
            if (Application.isEditor == false && Debug.isDebugBuild) CheatEvents.Report("development build running in release");
        }
    }
}
