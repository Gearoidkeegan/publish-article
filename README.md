# publish-article

A free Claude Code plugin with two skills:

- **publish-article** turns a Word (`.docx`) draft into a published article on a
  markdown or static-site website. It doesn't lose the text boxes, SmartArt
  diagrams, images and author emphasis that ordinary extraction drops.
- **social-pack** turns an article into branded social assets: a carousel (PNG
  slides plus a PDF for LinkedIn), quote cards, a link-preview image and post copy.

## What publish-article does
- Extracts the draft and runs a **content census** that counts paragraphs, tables,
  text boxes, SmartArt, images, and notes or headers, so nothing is silently left out.
- Converts the draft to your site's format with **light copy-editing only**. It keeps
  the author's voice, keeps their bold, and avoids AI tells such as added em-dashes.
- Optimises and places images, then builds the page and **renders it to check it
  visually** before shipping.
- Ships through your repo's normal branch → PR → deploy flow, and merges only with
  your approval.

## What social-pack does
- Plans a 5-8 slide carousel from the article: a cover, one idea per slide, and a
  call to action. Slide types cover stats, points, cards, tables, bar and line
  charts, images and quotes.
- **Every number and quote comes from the article.** The pack summarises; it
  doesn't add.
- Renders portrait (1080×1350) or square slides in your brand, and **checks that
  every slide fits** before writing any images. Text that would slide under
  another element stops the build. The fix is to shorten or split, never to
  shrink the type.
- Writes `carousel.pdf` (LinkedIn document posts), the PNGs (Instagram), a
  1200×627 link image, `post.txt` and a contact sheet for review.

## Install
In Claude Code:
```
/plugin marketplace add Gearoidkeegan/publish-article
/plugin install publish-article@publish-article
```
Restart Claude Code. Or copy `skills/publish-article/` into `~/.claude/skills/` by hand.

Requirements: Python 3 with `pip install python-docx Pillow`. Chrome or Edge is
needed for the rendering checks.

## First run: your house style
The plugin ships with **no design or branding**. The first time you use it on a site,
Claude asks for **either**:
- **your style guide** (a file, or paste it in), **or**
- **the URL of a published article on your site** to use as the template.

Claude saves the result in your site's repo at `.claude/publish-article-style.md`
and asks you to confirm it, so each site keeps its own style. You can also copy
`skills/publish-article/STYLE-GUIDE.md` there and fill it in yourself.

If your blog has no source in git (WordPress, Ghost, Webflow), the plugin still
prepares the finished article and images for you to paste in.

For social-pack, the first run asks for your brand guidelines (colours, fonts, logo),
**or** your website's URL to take them from, **or** "neutral" for a clean default.
It saves the theme at `.claude/social-pack-theme.json`.

## Use
> Publish this draft: `path/to/draft.docx`

> Make a LinkedIn carousel for that article

## Privacy
Everything runs locally in your Claude Code session. The plugin sends nothing
anywhere itself. The draft text goes to the model like any other file you share
with Claude.

## Licence
MIT
