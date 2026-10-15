// 안 쓰는 에셋 찾기 — 읽기만 한다(아무것도 지우지 않는다).
// 빌드에 들어가는 씬(Build Settings)에서 의존성을 따라가 **닿지 않는** 에셋을 크기순으로 뽑는다.
// 코드로 불러 쓰는 자리(Resources·StreamingAssets·Editor·Plugins, 스크립트·어셈블리 정의)는 따로 세고 후보에서 뺀다 —
// 그런 파일은 의존성 그래프에 안 잡혀도 실제로 쓰일 수 있다. Addressables·에셋 번들도 같은 이유로 확인이 필요하다고 적는다.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;

namespace Sonjari.Recipes
{
    public static class UnusedAssets
    {
        [Serializable]
        public class Args
        {
            public string folder = "Assets";
            public int limit = 100;
            public int min_kb = 0;
        }

        static readonly string[] DynamicFolders = { "/Resources/", "/StreamingAssets/", "/Editor/", "/Plugins/", "/Gizmos/" };
        static readonly string[] CodeExtensions = { ".cs", ".asmdef", ".asmref", ".dll", ".rsp", ".shader", ".cginc", ".hlsl", ".compute" };

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
                var scenes = EditorBuildSettings.scenes.Where(s => s.enabled).Select(s => s.path).ToArray();
                var used = new HashSet<string>(AssetDatabase.GetDependencies(scenes, true));
                var prefix = a.folder.TrimEnd('/') + "/";
                int checkedCount = 0, dynamicSkipped = 0, codeSkipped = 0, unusedCount = 0;
                long unusedBytes = 0;
                var rows = new List<KeyValuePair<long, string>>();
                foreach (var path in AssetDatabase.GetAllAssetPaths())
                {
                    if (!(path + "/").StartsWith(prefix) && !path.StartsWith(prefix)) continue;
                    if (AssetDatabase.IsValidFolder(path)) continue;
                    checkedCount++;
                    if (DynamicFolders.Any(f => ("/" + path).Contains(f))) { dynamicSkipped++; continue; }
                    if (CodeExtensions.Any(e => path.EndsWith(e, StringComparison.OrdinalIgnoreCase))) { codeSkipped++; continue; }
                    if (used.Contains(path)) continue;
                    long size = 0;
                    try { size = new FileInfo(path).Length; } catch (Exception) { }
                    if (size / 1024 < a.min_kb) continue;
                    unusedCount++;
                    unusedBytes += size;
                    rows.Add(new KeyValuePair<long, string>(size, path));
                }
                var items = rows.OrderByDescending(r => r.Key).Take(a.limit)
                    .Select(r => (object)new Dictionary<string, object> { { "path", r.Value }, { "kb", r.Key / 1024 } })
                    .ToList();
                RecipeIO.Write(new Dictionary<string, object>
                {
                    { "ok", true },
                    { "recipe", "unused_assets" },
                    { "folder", a.folder },
                    { "build_scenes", scenes.ToList<object>() },
                    { "assets_checked", checkedCount },
                    { "used_by_build", used.Count },
                    { "skipped_dynamic_folders", dynamicSkipped },
                    { "skipped_code", codeSkipped },
                    { "unused_total", unusedCount },
                    { "unused_mb", Math.Round(unusedBytes / 1048576.0, 2) },
                    { "listed", items.Count },
                    { "items", items },
                    { "note", "빌드 씬에서 닿지 않는 파일이다. 코드가 이름으로 불러 쓰거나(Addressables·에셋 번들 등) 다른 빌드 설정에서 쓰면 여기 떠도 쓰이는 것일 수 있다 — 지우기 전에 확인해야 한다." },
                });
            }
            catch (Exception error)
            {
                RecipeIO.Fail(error);
            }
        }
    }
}
