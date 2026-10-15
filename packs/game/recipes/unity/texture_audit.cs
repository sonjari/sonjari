// 텍스처 설정 점검 — 읽기만 한다(설정을 바꾸지 않는다).
// 걸리는 것: 최대 크기가 기준을 넘음 · 압축 안 함 · Read/Write 켜짐(메모리 두 배) · 원본이 기준보다 큼.
using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;

namespace Sonjari.Recipes
{
    public static class TextureAudit
    {
        [Serializable]
        public class Args
        {
            public string folder = "Assets";
            public int max_size = 2048;
            public int limit = 200;
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
                // ★ 2026-10-01 테스터 시험: 경로 순서로 앞의 limit 개만 담아, 제일 무거운 16MB 텍스처 넷이 잘렸다.
                //   걸린 것을 전부 모은 뒤 **파일이 큰 순서로** limit 개를 담는다.
                var found = new List<KeyValuePair<long, Dictionary<string, object>>>();
                int overMax = 0, uncompressed = 0, readable = 0, sourceBig = 0, checkedCount = 0, flaggedTotal = 0;
                long bytes = 0;
                foreach (var guid in AssetDatabase.FindAssets("t:Texture2D", new[] { a.folder }))
                {
                    var path = AssetDatabase.GUIDToAssetPath(guid);
                    var importer = AssetImporter.GetAtPath(path) as TextureImporter;
                    if (importer == null) continue;
                    checkedCount++;
                    importer.GetSourceTextureWidthAndHeight(out var width, out var height);
                    long size = 0;
                    try { size = new FileInfo(path).Length; } catch (Exception) { }
                    bytes += size;
                    var flags = new List<object>();
                    if (importer.maxTextureSize > a.max_size) { flags.Add("over_max"); overMax++; }
                    if (importer.textureCompression == TextureImporterCompression.Uncompressed) { flags.Add("uncompressed"); uncompressed++; }
                    if (importer.isReadable) { flags.Add("readable"); readable++; }
                    if (Math.Max(width, height) > a.max_size) { flags.Add("source_over_max"); sourceBig++; }
                    if (flags.Count == 0) continue;
                    flaggedTotal++;
                    found.Add(new KeyValuePair<long, Dictionary<string, object>>(size, new Dictionary<string, object>
                    {
                        { "path", path },
                        { "flags", flags },
                        { "max_texture_size", importer.maxTextureSize },
                        { "source", width + "x" + height },
                        { "compression", importer.textureCompression.ToString() },
                        { "type", importer.textureType.ToString() },
                        { "readable", importer.isReadable },
                        { "mipmaps", importer.mipmapEnabled },
                        { "kb", size / 1024 },
                    }));
                }
                found.Sort((x, y) => y.Key.CompareTo(x.Key));
                var items = new List<object>();
                foreach (var pair in found)
                {
                    if (items.Count >= a.limit) break;
                    items.Add(pair.Value);
                }
                RecipeIO.Write(new Dictionary<string, object>
                {
                    { "ok", true },
                    { "recipe", "texture_audit" },
                    { "folder", a.folder },
                    { "max_size", a.max_size },
                    { "textures_checked", checkedCount },
                    { "total_mb", Math.Round(bytes / 1048576.0, 2) },
                    { "flagged_total", flaggedTotal },
                    { "flag_counts", new Dictionary<string, object>
                        {
                            { "over_max", overMax },
                            { "uncompressed", uncompressed },
                            { "readable", readable },
                            { "source_over_max", sourceBig },
                        }
                    },
                    { "flagged_listed", items.Count },
                    { "sorted_by", "file_size_desc" },
                    { "flagged", items },
                });
            }
            catch (Exception error)
            {
                RecipeIO.Fail(error);
            }
        }
    }
}
