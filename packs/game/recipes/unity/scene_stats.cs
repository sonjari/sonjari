// 씬 성능 점검 — 읽기만 한다(씬을 열어 보지만 저장하지 않는다).
// 씬마다 오브젝트·렌더러·삼각형·조명(실시간·그림자)·재질·카메라·파티클 수를 세어 「어느 씬이 왜 무거운가」에 답한다.
using System;
using System.Collections.Generic;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace Sonjari.Recipes
{
    public static class SceneStats
    {
        [Serializable]
        public class Args
        {
            public string folder = "Assets";
            public int limit = 30;
        }

        static long Triangles(Mesh mesh)
        {
            if (mesh == null) return 0;
            long total = 0;
            for (int i = 0; i < mesh.subMeshCount; i++)
            {
                if (mesh.GetTopology(i) == MeshTopology.Triangles) total += mesh.GetIndexCount(i) / 3;
            }
            return total;
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
                var rows = new List<Dictionary<string, object>>();
                foreach (var guid in AssetDatabase.FindAssets("t:Scene", new[] { a.folder }))
                {
                    var path = AssetDatabase.GUIDToAssetPath(guid);
                    if (!path.StartsWith("Assets/")) continue;
                    var scene = EditorSceneManager.OpenScene(path, OpenSceneMode.Single);
                    var roots = scene.GetRootGameObjects();
                    var all = roots.SelectMany(r => r.GetComponentsInChildren<Transform>(true)).ToList();
                    var renderers = roots.SelectMany(r => r.GetComponentsInChildren<Renderer>(true)).ToList();
                    long triangles = 0;
                    foreach (var filter in roots.SelectMany(r => r.GetComponentsInChildren<MeshFilter>(true))) triangles += Triangles(filter.sharedMesh);
                    foreach (var skinned in roots.SelectMany(r => r.GetComponentsInChildren<SkinnedMeshRenderer>(true))) triangles += Triangles(skinned.sharedMesh);
                    var lights = roots.SelectMany(r => r.GetComponentsInChildren<Light>(true)).ToList();
                    var realtime = lights.Where(l => l.lightmapBakeType == LightmapBakeType.Realtime).ToList();
                    var materials = new HashSet<Material>(renderers.SelectMany(r => r.sharedMaterials).Where(m => m != null));
                    rows.Add(new Dictionary<string, object>
                    {
                        { "scene", path },
                        { "objects", all.Count },
                        { "renderers", renderers.Count },
                        { "triangles", triangles },
                        { "lights", lights.Count },
                        { "realtime_lights", realtime.Count },
                        { "shadow_casting_realtime_lights", realtime.Count(l => l.shadows != LightShadows.None) },
                        { "materials", materials.Count },
                        { "cameras", roots.SelectMany(r => r.GetComponentsInChildren<Camera>(true)).Count() },
                        { "particle_systems", roots.SelectMany(r => r.GetComponentsInChildren<ParticleSystem>(true)).Count() },
                    });
                }
                var sorted = rows.OrderByDescending(r => (long)r["triangles"]).Take(a.limit).Cast<object>().ToList();
                RecipeIO.Write(new Dictionary<string, object>
                {
                    { "ok", true },
                    { "recipe", "scene_stats" },
                    { "folder", a.folder },
                    { "scenes_checked", rows.Count },
                    { "scenes", sorted },
                });
            }
            catch (Exception error)
            {
                RecipeIO.Fail(error);
            }
        }
    }
}
