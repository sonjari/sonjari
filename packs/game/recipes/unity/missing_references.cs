// 빠진 참조 찾기 — 읽기만 한다(씬을 열어 보지만 저장하지 않는다).
// 걸리는 것: 스크립트가 사라진 컴포넌트(Missing Script) · 대상이 사라진 참조 칸(Missing reference).
using System;
using System.Collections.Generic;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace Sonjari.Recipes
{
    public static class MissingReferences
    {
        [Serializable]
        public class Args
        {
            public string folder = "Assets";
            public bool include_scenes = true;
            public int limit = 200;
        }

        class Tally
        {
            public int missingScripts;
            public int missingRefs;
            public int found;
            public readonly List<object> items = new List<object>();
        }

        public static void Run()
        {
            try
            {
                var a = RecipeIO.ReadArgs<Args>();
                if (!AssetDatabase.IsValidFolder(a.folder))
                {
                    RecipeIO.Write(new Dictionary<string, object> { { "ok", false }, { "error", "folder_not_found: " + a.folder } });
                    return;
                }
                var tally = new Tally();
                int prefabs = 0, scenes = 0;
                foreach (var guid in AssetDatabase.FindAssets("t:Prefab", new[] { a.folder }))
                {
                    var path = AssetDatabase.GUIDToAssetPath(guid);
                    var root = AssetDatabase.LoadAssetAtPath<GameObject>(path);
                    if (root == null) continue;
                    prefabs++;
                    Scan(root, path, a.limit, tally);
                }
                if (a.include_scenes)
                {
                    foreach (var guid in AssetDatabase.FindAssets("t:Scene", new[] { a.folder }))
                    {
                        var path = AssetDatabase.GUIDToAssetPath(guid);
                        if (!path.StartsWith("Assets/")) continue;
                        var scene = EditorSceneManager.OpenScene(path, OpenSceneMode.Single);
                        scenes++;
                        foreach (var go in scene.GetRootGameObjects()) Scan(go, path, a.limit, tally);
                    }
                }
                RecipeIO.Write(new Dictionary<string, object>
                {
                    { "ok", true },
                    { "recipe", "missing_references" },
                    { "folder", a.folder },
                    { "prefabs_checked", prefabs },
                    { "scenes_checked", scenes },
                    { "missing_scripts", tally.missingScripts },
                    { "missing_references", tally.missingRefs },
                    { "found_total", tally.found },
                    { "listed", tally.items.Count },
                    { "items", tally.items },
                });
            }
            catch (Exception error)
            {
                RecipeIO.Fail(error);
            }
        }

        static void Scan(GameObject root, string asset, int limit, Tally tally)
        {
            foreach (var transform in root.GetComponentsInChildren<Transform>(true))
            {
                var go = transform.gameObject;
                var missing = GameObjectUtility.GetMonoBehavioursWithMissingScriptCount(go);
                if (missing > 0)
                {
                    tally.missingScripts += missing;
                    Add(tally, limit, asset, HierarchyPath(go), "missing_script", "", missing);
                }
                foreach (var component in go.GetComponents<Component>())
                {
                    if (component == null) continue;
                    var serialized = new SerializedObject(component);
                    var property = serialized.GetIterator();
                    while (property.NextVisible(true))
                    {
                        if (property.propertyType != SerializedPropertyType.ObjectReference) continue;
                        if (property.objectReferenceValue != null) continue;
                        if (!PointsSomewhere(property)) continue;
                        tally.missingRefs++;
                        Add(tally, limit, asset, HierarchyPath(go), "missing_reference",
                            component.GetType().Name + "." + property.propertyPath, 1);
                    }
                }
            }
        }

        // 값은 비었는데 **어딘가를 가리키던 흔적**이 있으면 빠진 참조다(처음부터 빈 칸은 아니다).
        // 유니티 6.2 부터 인스턴스 ID 가 EntityId 로 바뀌어 옛 API 가 컴파일 오류가 된다 — 버전마다 맞는 쪽을 쓴다.
        static bool PointsSomewhere(SerializedProperty property)
        {
#if UNITY_6000_2_OR_NEWER
            return !property.objectReferenceEntityIdValue.Equals(default(EntityId));
#else
            return property.objectReferenceInstanceIDValue != 0;
#endif
        }

        static void Add(Tally tally, int limit, string asset, string objectPath, string kind, string field, int count)
        {
            tally.found++;
            if (tally.items.Count >= limit) return;
            tally.items.Add(new Dictionary<string, object>
            {
                { "asset", asset },
                { "object", objectPath },
                { "kind", kind },
                { "field", field },
                { "count", count },
            });
        }

        static string HierarchyPath(GameObject go)
        {
            var path = go.name;
            var parent = go.transform.parent;
            while (parent != null)
            {
                path = parent.name + "/" + path;
                parent = parent.parent;
            }
            return path;
        }
    }
}
