# Stone encyclopedia

One JSON file per stone in `stones/<slug>.json`. The slug matches the model's label, so an
identification result links straight to its page. Reviewed by pull request; shipped as static files.

## Writing rules ([ADR 0004](../../docs/adr/0004-pivot-to-crystals-and-healing-stones.md))

1. **Our own words.** Never copy sentences from websites, books or shops. Facts and traditional
   associations are free to use; someone else's wording is not.
2. **Tradition, not fact.** Meanings start from "In crystal healing traditions, …" or "is associated
   with …". Never say a stone heals, treats, cures or prevents anything, and never link it to organs or
   illnesses. Every page shows the `tradition-not-medical` disclaimer.
3. **Facts are plain and sourced.** Mineral, hardness, origin, birthstone, history: checked against at
   least one independent source (Wikipedia, mindat, GIA) and listed in `sources`.
4. **Say what a photo can't tell.** `lookalikes` names stones and imitations that look the same.
   The app says "looks like", never "is genuine".
5. **Images** come from Wikimedia Commons (or our own photos) with author, license and link in `images`.
   Never product photos from shops.

## Fields

| Field | Content |
|---|---|
| `slug`, `name`, `also_called` | Identity; `slug` = model label (lowercase, hyphens) |
| `status` | `draft` → `reviewed` (owner approved) → `published` |
| `summary` | One sentence for the result card |
| `what_it_is` | What the stone is, in plain language |
| `how_to_recognize` | `color`, `appearance`, `lookalikes` (`slug` or `name` + `how_to_tell`) |
| `facts` | `mineral`, `hardness_mohs`, `main_sources`, `birthstone` (optional) |
| `history` | Name origin and notable history |
| `tradition` | `summary`, `associations`, `chakras`, `zodiac`, `how_people_use_it` |
| `care` | Cleaning and handling tips |
| `disclaimer` | Key of the disclaimer text shown on the page |
| `images` | `{ "file", "author", "license", "url" }` |
| `sources` | `{ "title", "url", "license", "used_for" }` |

## Data credits

Traditional associations are adapted from
[crystalSearch](https://github.com/aar0np/crystalSearch) `gemstones_and_chakras.csv` by aar0np,
licensed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0). We rewrite the
text and do not use its "Physical Attributes" column (body and health claims).
