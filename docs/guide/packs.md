# Skills and packs

**English** · [한국어](packs.ko.md)

Sonjari's core knows the browser, files and documents. Everything else is added on top, in layers you can see and switch
off:

```mermaid
flowchart TB
    I["Instructions about me<br/>your own rules, read every turn"]
    SP["Skill packs (content)<br/>a folder anyone can write — skills, trigger words, a default ask"]
    DP["Domain packs (code)<br/>new tools — ours and verified partners only, off by default"]
    SK["Skills<br/>know-how written as text (SKILL.md), picked per request"]
    R["Recipes<br/>step-by-step site procedures, checked step by step"]
    C["Sonjari core<br/>browser · files · documents · code"]
    I --> C
    SP --> SK
    DP --> SK
    DP --> R
    DP -->|"adds tools"| C
    SK --> C
    R --> C
```

| Layer | What it is | Who can add it | Can it add new abilities? |
|---|---|---|---|
| Instructions about me | your work, answer length, tone, things to avoid | you (Settings › About me) | no — text only |
| Skills | how to do a kind of job, written as a `SKILL.md` | bundled, or through a pack | no — text only |
| Skill packs | a folder of skills + the words that trigger them + a default ask | anyone | no — `content` only |
| Domain packs | new tools, recipes, skills and a guide for a field (games, …) | us and verified partners | yes — `code`, shown with permissions before you turn it on |
| Recipes | site procedures with an expected result after each step | reviewed by people | no — they drive the existing browser |

---

## Skills

A skill is know-how written as text: which sites to use, what to read, how the result table should look, where people
usually go wrong. Sonjari ships about 190 of them, collected from open sources with their licenses.

- **Picked by code, per request.** When a request matches a skill, Sonjari attaches it to that job (Settings › Skills ›
  *Attach a skill that fits the request*, and *Main fields* to narrow the choice). Another AI can name one directly with the
  `skill` field of `sonjari_task`.
- **Treated as untrusted text.** A skill's body is wrapped and marked as outside material. A skill cannot lower a safety
  level or skip an approval, even if its text says so.
- **No license, no serving.** A bundle without a `LICENSE` file is read but not used, and the list says why.

## Skill packs — anyone can make one

A skill pack is a folder. Put it in `Documents\Sonjari\skillpacks\` and turn it on in **Settings › Pack**.

```text
Documents\Sonjari\skillpacks\price-watch-demo\
  pack.json
  skills\price-watch\SKILL.md
```

`pack.json` (the [sample pack](../skillpacks/price-watch-demo/pack.json), shortened):

```json
{
  "id": "price-watch-demo",
  "name": "Price check skill pack (sample)",
  "version": "0.3.0",
  "kind": "content",
  "summary": "Finds one product at three set shops and puts price and shipping into one Excel sheet.",
  "skills": ["price-watch"],
  "triggers": { "price-watch": ["가격 조사", "가격 비교", "최저가 조사"] },
  "asks": { "price-watch": "Find the product at each shop in the skill and put price and shipping into an Excel file" },
  "work": { "price-watch": "web" },
  "permissions": {
    "reads": ["the shop pages Sonjari opens"],
    "writes": ["the result Excel file, in Sonjari's output folder"],
    "runs": [],
    "network": "only to open the shop pages"
  }
}
```

| Field | Meaning |
|---|---|
| `id` | lower-case letters, digits and `-`, 2–32 characters. Cannot take the name of a pack we ship |
| `kind` | must be `content` here — a folder you drop in can never add tools |
| `skills` | the skill folders under `skills/` |
| `triggers` | per skill, the words that attach it (2–40 characters each, up to 40 per skill) |
| `asks` | per skill, the full request a person would otherwise type every time (10–300 characters). Added after the person's own words, so a short "price check" still ends with an Excel file |
| `work` | what kind of job it is (`web`, …) |
| `permissions` | shown to the person before the pack is turned on: what it reads, writes, runs, and whether it uses the network |

`SKILL.md` uses the same layout as a Claude skill: a front matter with `name` and `description`, then the text — the shops,
the order of steps, the items to read, the result columns, and the places it usually goes wrong. Packs that cannot be read
are listed with the reason, not dropped silently.

**To make your own:** copy [`docs/skillpacks/price-watch-demo`](../skillpacks/price-watch-demo), change the id, the skill
text and the trigger words, put the folder in `Documents\Sonjari\skillpacks\`, turn it on, and type one of the trigger
words. See [CONTRIBUTING](../../CONTRIBUTING.md) to share it.

## Domain packs — new abilities for a field

A domain pack adds real tools, so only packs that ship with Sonjari (ours and verified partners) can be `code`. They are
**off by default**, and turning one on first shows its `permissions` — what it reads, writes, runs, and whether it uses the
network. Pressing *Turn on* is the consent.

The game pack is the first one:

| | |
|---|---|
| What it does | checks Unity projects, shows the open Unity editor inside Sonjari's window, and changes it only after you approve. Scripts written by Claude or Codex are run in the real project and kept as recipes that can run on a schedule without a model |
| Tools it adds | `unity_project_info`, `unity_list_recipes`, `unity_run_recipe`, `unity_try_script`, `unity_editor_status`, `unity_editor_look`, `unity_editor_change`, `unity_editor_undo` |
| Writes | the project's `Assets/Editor/SonjariRecipes` only while a recipe runs; one line in `Packages/manifest.json` when you connect the editor (undone when you disconnect); scene changes only after approval, kept in the editor's Undo |
| Network | none. Built on a pinned copy of [MCP for Unity](https://github.com/CoplayDev/unity-mcp) (MIT) with its outside connections and telemetry removed |

### 3D pack

| | |
|---|---|
| What it does | turns one drawing into a 3D model (GLB) on your graphics card and returns a receipt it measured itself: faces, size, closed mesh or not, time, graphics memory, plus small previews. Makes print files (STL, one-colour 3MF), can split a figure into parts with pins, and with Blender installed cleans up, renders and exports (GLB, FBX for Unity) |
| Tools it adds | `gen_3d_check`, `gen_3d_blender`, `gen_3d_prep`, `gen_3d`, `gen_3d_status`, `gen_3d_print`, `gen_3d_views`, `gen_3d_finish`, `gen_3d_render`, `gen_3d_export`, `gen_3d_split_plan`, `gen_3d_split`, `gen_3d_fit_test`, `gen_3d_fit_set` |
| Writes | a new folder per run under `Documents/Sonjari/gen3d` (never overwritten); the runner and model when you turn it on (about 0.7 GB + 9.9 GB); Blender, only if you agree to download it |
| Runs | `trellis-cli` once per drawing, one at a time, no window; Blender headless with factory settings; on a Mac it unloads the local text model before baking and checks free memory first |
| Network | none while making. Downloads the runner (GitHub release) and model (Hugging Face) once, showing size and licence first and checking hashes afterwards. Blender comes from blender.org only after you read and accept the notice |
| Built on | [trellis.cpp](https://github.com/pwilkin/trellis.cpp) v0.8.1 (MIT), [TRELLIS.2 GGUF](https://huggingface.co/ilintar/trellis2-gguf) q8 (MIT, following the original) |
| Measured | RTX 3060 12GB at 512: 11 runs of 85–139 s, 2,908–4,064 MiB of graphics memory (whole card). 16 GB Mac: 512 only |

### Video pack

| | |
|---|---|
| What it does | Claude writes the storyboard; Sonjari renders draft cuts on your graphics card and returns a receipt instead of the video: time, checks (motion, frozen, too dark, pops, sound), a contact sheet and a pick sheet. Only the cuts you choose are rendered again as finals. Text, logos and app screens are never generated — they are composited by code |
| Tools it adds | `gen_video_check`, `gen_video_prep`, `gen_video_batch`, `gen_video_status`, `gen_video_finish` |
| Writes | a new folder per batch under `Documents/Sonjari/genvideo` (never overwritten); the runner and models when you turn it on (about 0.98 GB + 18.3 GB) |
| Runs | `sd-cli` once per cut, one at a time, no window; `ffmpeg` for the checks. On a PC with one graphics card it unloads the local text model before rendering |
| Network | none while making. Downloads the runner and models once, showing size and licence first and checking hashes afterwards |
| Built on | [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) (MIT); FastWan2.2-TI2V-5B for drafts and Wan2.2-TI2V-5B for finals (Apache-2.0). LTX-2.x with sound is optional: you accept its licence and download it yourself |
| Measured | RTX 3060 12GB, 832×480, 3-second cut: drafts 31–57 s (4 runs), a final about 370 s (1 run). Windows only |

Licence for these two packs (from 0.4.49): free for personal and noncommercial use, and for companies with fewer than 100 people and less
than US$1M revenue a year — [PolyForm Noncommercial](https://polyformproject.org/licenses/noncommercial/1.0.0) or [PolyForm Small Business](https://polyformproject.org/licenses/small-business/1.0.0) 1.0.0, your pick.

When a domain pack is on and you connect Claude Code or Codex, its usage guide is installed next to Sonjari's own, and its
tools show up over MCP (see the [MCP guide](mcp.md)).

The code: `src/alture_jarvis/packs.py` (packs), `skills.py` (skills), `site_recipes.py` (recipes), `about_me.py`
(instructions about me).
