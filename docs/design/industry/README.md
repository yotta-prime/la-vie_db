# Industry theme for la-vie admin

Restyle of the admin UI, from the "Industry" design (Claude Design package `la-vie-industry-package`).

## Where it lives

- `app/admin/templates/base.html` holds the live theme: the stylesheet is inlined in its `<style>` block. No other template, route or Python file changed; every existing class name is kept.
- `docs/design/industry/la-vie-industry.css` is the same stylesheet as a standalone file, for reading or editing.
- `docs/design/industry/la-vie-original.css` is the previous `<style>` block, for rollback.

## Dependencies

- Fonts: Barlow and Barlow Condensed, loaded from Google Fonts by your browser. Without internet access the page falls back to the system font.
- Dark mode follows `prefers-color-scheme`, as before.

## Editing

Change `la-vie-industry.css`, then paste it into the `<style>` block of `base.html` so the two stay identical.

## Rollback

Paste `la-vie-original.css` (without its first comment line) back into the `<style>` block of `base.html` and remove the three Google Fonts `<link>` lines.
