using UnityEngine;
#if UNITY_EDITOR
using System.Reflection;
using UnityEditor;
#endif

namespace MCPForUnity.Runtime.Helpers
{
    // Part of MCP for Unity's compat-shim family. See UnityCompatShims.cs in this
    // folder for the full list of shims, the audit policy, and the reflection pattern.
    /// <summary>
    /// Version-gated wrappers for the InstanceID ↔ EntityId migration introduced in Unity 6.5
    /// and tightened in 6.6.
    ///   Forward (Object → int): <see cref="GetInstanceIDCompat"/>
    ///   Reverse (int → Object, Editor-only): <see cref="InstanceIDToObjectCompat"/>
    /// </summary>
    public static class UnityObjectIdCompat
    {
        /// <summary>
        /// Returns a session-scoped int handle for the object. On 6.5+ truncates the
        /// EntityId's underlying ulong; lossy but stable within a session and preserves
        /// the int-shaped wire format that older consumers expect. For deserialization
        /// round-trips on 6.5+, prefer the full <c>entityID</c> field.
        /// </summary>
        public static int GetInstanceIDCompat(this Object obj)
        {
            if (obj == null)
            {
                return 0;
            }

#if UNITY_6000_5_OR_NEWER
            return (int)EntityId.ToULong(obj.GetEntityId());
#else
            return obj.GetInstanceID();
#endif
        }

#if UNITY_EDITOR
#if UNITY_6000_6_OR_NEWER
        private static MethodInfo _instanceIdToObject;
        private static bool _instanceIdToObjectInitialized;
#endif

        /// <summary>
        /// Resolves an int instance ID handle back to a UnityEngine.Object.
        ///   Pre-6.0  : EditorUtility.InstanceIDToObject(int)
        ///   6.0–6.5  : EditorUtility.EntityIdToObject(int)  (implicit int→EntityId cast)
        ///   6.6+     : reflection on InstanceIDToObject(int) — the API still exists at runtime
        ///              but is obsolete-as-error; reflection bypasses CS0619 until the public
        ///              EntityId(int) ctor stabilizes.
        /// </summary>
#if UNITY_6000_6_OR_NEWER
        private static Object OntelicResolve(int instanceId)
        {
            try
            {
                var byEntity = EditorUtility.EntityIdToObject(EntityId.FromULong((ulong)(uint)instanceId));
                if (byEntity != null) return byEntity;
            }
            catch (System.Exception) { }
            for (int s = 0; s < UnityEngine.SceneManagement.SceneManager.sceneCount; s++)
            {
                var scene = UnityEngine.SceneManagement.SceneManager.GetSceneAt(s);
                if (!scene.isLoaded) continue;
                foreach (var root in scene.GetRootGameObjects())
                {
                    foreach (var t in root.GetComponentsInChildren<Transform>(true))
                    {
                        if (GetInstanceIDCompat(t.gameObject) == instanceId) return t.gameObject;
                        foreach (var c in t.GetComponents<Component>())
                        {
                            if (c != null && GetInstanceIDCompat(c) == instanceId) return c;
                        }
                    }
                }
            }
            return null;
        }
#endif

        public static Object InstanceIDToObjectCompat(int instanceId)
        {
#if UNITY_6000_6_OR_NEWER
            if (!_instanceIdToObjectInitialized)
            {
                _instanceIdToObject = typeof(EditorUtility).GetMethod(
                    "InstanceIDToObject",
                    BindingFlags.Public | BindingFlags.Static,
                    null,
                    new[] { typeof(int) },
                    null);
                _instanceIdToObjectInitialized = true;
            }
            // Ontelic build: on 6000.6 the reflected InstanceIDToObject(int) throws at runtime, so every lookup by
            // instanceID failed (find by_id, get_gameobject, components). Forward mapping is (int)EntityId.ToULong,
            // so map back with EntityId.FromULong, then scan open scenes, then try the old path last.
            var resolved = OntelicResolve(instanceId);
            if (resolved != null) return resolved;
            try { return _instanceIdToObject?.Invoke(null, new object[] { instanceId }) as Object; }
            catch (System.Exception) { return null; }
#elif UNITY_6000_3_OR_NEWER
            return EditorUtility.EntityIdToObject(instanceId);
#else
            return EditorUtility.InstanceIDToObject(instanceId);
#endif
        }
#endif
    }
}
