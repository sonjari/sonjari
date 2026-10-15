// 손자리 레시피 공용 입출력. 손자리가 레시피를 돌릴 때만 잠깐 프로젝트에 들어왔다가 끝나면 지워진다.
// 값은 -sonjariArgs <json 파일> 로 받고, 결과는 -sonjariOut <json 파일> 로 남긴다.
// 모델이 준 글은 코드에 끼워 넣지 않는다 — 값(JSON)으로만 받는다.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEngine;

namespace Sonjari.Recipes
{
    public static class RecipeIO
    {
        static string Arg(string name)
        {
            var args = Environment.GetCommandLineArgs();
            for (int i = 0; i < args.Length - 1; i++)
            {
                if (args[i] == name) return args[i + 1];
            }
            return null;
        }

        public static T ReadArgs<T>() where T : new()
        {
            var obj = new T();
            var path = Arg("-sonjariArgs");
            if (!string.IsNullOrEmpty(path) && File.Exists(path))
            {
                JsonUtility.FromJsonOverwrite(File.ReadAllText(path, Encoding.UTF8), obj);
            }
            return obj;
        }

        public static void Write(Dictionary<string, object> result)
        {
            var path = Arg("-sonjariOut");
            if (string.IsNullOrEmpty(path)) return;
            File.WriteAllText(path, Json(result), new UTF8Encoding(false));
        }

        public static void Fail(Exception error)
        {
            Write(new Dictionary<string, object>
            {
                { "ok", false },
                { "error", error.GetType().Name + ": " + error.Message },
            });
        }

        public static string Json(object value)
        {
            var sb = new StringBuilder();
            Emit(sb, value);
            return sb.ToString();
        }

        static void Emit(StringBuilder sb, object value)
        {
            switch (value)
            {
                case null: sb.Append("null"); break;
                case string s: Str(sb, s); break;
                case bool b: sb.Append(b ? "true" : "false"); break;
                case int i: sb.Append(i.ToString(CultureInfo.InvariantCulture)); break;
                case long l: sb.Append(l.ToString(CultureInfo.InvariantCulture)); break;
                case float f: sb.Append(f.ToString("R", CultureInfo.InvariantCulture)); break;
                case double d: sb.Append(d.ToString("R", CultureInfo.InvariantCulture)); break;
                case IDictionary<string, object> dict:
                    sb.Append('{');
                    var first = true;
                    foreach (var pair in dict)
                    {
                        if (!first) sb.Append(',');
                        first = false;
                        Str(sb, pair.Key);
                        sb.Append(':');
                        Emit(sb, pair.Value);
                    }
                    sb.Append('}');
                    break;
                case IEnumerable list:
                    sb.Append('[');
                    var head = true;
                    foreach (var item in list)
                    {
                        if (!head) sb.Append(',');
                        head = false;
                        Emit(sb, item);
                    }
                    sb.Append(']');
                    break;
                default: Str(sb, value.ToString()); break;
            }
        }

        static void Str(StringBuilder sb, string s)
        {
            sb.Append('"');
            foreach (var c in s)
            {
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    default:
                        if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4"));
                        else sb.Append(c);
                        break;
                }
            }
            sb.Append('"');
        }
    }
}

// ★ 이름 2단계(2026-09-29) 전에 만든 초안(`namespace Ontelic.Recipes`)이 그대로 돌게 하는 통로.
//   새 레시피는 Sonjari.Recipes 를 쓴다. 옛 초안이 다 옮겨지면 지운다.
namespace Ontelic.Recipes
{
    public static class RecipeIO
    {
        public static T ReadArgs<T>() where T : new() { return Sonjari.Recipes.RecipeIO.ReadArgs<T>(); }
        public static void Write(System.Collections.Generic.Dictionary<string, object> result) { Sonjari.Recipes.RecipeIO.Write(result); }
        public static void Fail(System.Exception error) { Sonjari.Recipes.RecipeIO.Fail(error); }
        public static string Json(object value) { return Sonjari.Recipes.RecipeIO.Json(value); }
    }
}
