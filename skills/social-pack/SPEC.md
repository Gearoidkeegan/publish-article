# Social pack spec

Two JSON files: the **deck** (one per article) and the **theme** (one per site).
In any text field, `**bold**` works. Everything else is escaped, so write `&`
rather than `&amp;`.

## Deck (`deck.json`)

```json
{
  "format": "portrait",
  "eyebrow": "Pricing update",
  "url": "example.com/blog/q3-pricing",
  "band_lines": 2,
  "slides": [
    {"type": "cover", "name": "cover", "kicker": "Q3 review",
     "title": "Why our prices moved this quarter",
     "sub": "Three causes, one fix, and what it means for **your next order**."},
    {"type": "stat", "name": "headline", "kicker": "The number", "title": "Input costs rose sharply",
     "items": [{"value": "+18%", "label": "Raw material costs", "text": "Q3 against Q2."}],
     "band": "We absorbed half of it."},
    {"type": "cta", "name": "read-more", "kicker": "Read the full article",
     "title": "The full breakdown, line by line"}
  ],
  "singles": [
    {"type": "quote", "name": "quote-card", "quote": "Exact words from the article.", "by": "Author name"},
    {"type": "link", "name": "link-image", "kicker": "Q3 review", "title": "Why our prices moved this quarter"}
  ]
}
```

| Deck field | Meaning |
|---|---|
| `format` | `portrait` (1080×1350, default choice) or `square` (1080×1080) |
| `eyebrow` | Small label at the top left of every slide (series or topic name) |
| `url` | Shown in the footer and on the CTA slide (default: the theme's `url`) |
| `band_lines` | Height the band is pinned to, in lines (default 2) |

**Fields every slide takes:** `type`, `name` (used in the file name), `kicker`,
`title`, `sub`, `band`, and `url` (overrides the deck's).

| `type` | Extra fields |
|---|---|
| `cover` | (none) |
| `cta` | (none). Shows the URL large. |
| `points` | `items`: `[{"title", "text"}]`, 3-6 items. Leave out `title` on every item for number + text rows. |
| `cards` | `items`: `[{"label", "title", "text"}]`, 2-4 items |
| `stat` | `items`: `[{"value", "label", "text"}]`, 1-3 items |
| `quote` | `quote`, `by` |
| `table` | `columns`: `[...]`, `rows`: `[[...], ...]`, `note` |
| `bars` | `items`: `[{"label", "value", "display"}]`, `unit`, `note`. Values ≥ 0; `display` overrides the printed value. |
| `line` | `x`: `[labels]`, `series`: `[{"name", "values"}]` (1-3; `null` for a gap), `unit`, `zero` (start the axis at 0, default true), `note` |
| `image` | `src` (path relative to deck.json), `caption` |

`singles`: `quote` (1080×1080, fields as for the slide) and `link` (1200×627:
`kicker`, `title`).

## Theme (`.claude/social-pack-theme.json`)

```json
{
  "colors": {
    "bg": "#FFFFFF", "ink": "#16181D", "body": "#454A54", "muted": "#8A8F99",
    "rule": "#E3E5E8", "accent": "#2563EB", "band": "#2563EB", "band_ink": "#FFFFFF",
    "paper": "#F7F8FA", "series": ["#2563EB", "#D97706", "#475569"]
  },
  "fonts": {
    "heading": {"family": "BrandSans", "files": {"700": "fonts/BrandSans-Bold.woff2"}, "weight": 700},
    "body":    {"family": "BrandText", "files": {"400": "fonts/BrandText-Regular.woff2",
                                                 "700": "fonts/BrandText-Bold.woff2"}},
    "mono":    {"family": "Consolas, monospace"}
  },
  "logo": "images/logo.png",
  "brand": "Brand name (shown when there is no logo)",
  "tagline": "Optional short line beside the logo",
  "url": "example.com"
}
```

- Every field is optional; anything left out uses the neutral default above.
- Paths are relative to the theme file. Font files are loaded from local disk
  (headless Chrome fetches nothing over a relative path). `css_url` on a font
  loads a hosted stylesheet such as Google Fonts instead, which needs a network
  connection.
- `ink`, `body` and `muted` need enough contrast against `bg`, and `band_ink`
  against `band`. `series` colours should stay distinguishable for colour-blind
  readers: blue, orange and slate do; red and green don't.
- Use a logo with a transparent background, at least 80px tall.
