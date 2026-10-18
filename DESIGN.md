---
name: YouTube Metadata Extractor
description: Compact local extraction console with light and dark themes.
colors:
  canvas: "#faf8ff"
  surface: "#fff"
  recess: "#f2f3ff"
  border: "#e2e7f1"
  text: "#131b2e"
  muted: "#586176"
  primary: "#e62117"
  secondary: "#4b41e1"
  green: "#05754f"
  green-bg: "#e6f8ef"
  red: "#b3232b"
  red-bg: "#fff0f0"
  amber: "#875300"
  amber-bg: "#fff5dc"
  header: "#283044"
  terminal: "#20283b"
  focus: "#6962ef"
  canvas-dark: "#080d12"
  surface-dark: "#10171e"
  recess-dark: "#161f29"
  border-dark: "#26313e"
  text-dark: "#eef2f7"
  muted-dark: "#a3afbe"
  secondary-dark: "#aca5ff"
  green-dark: "#64d9a6"
  green-bg-dark: "#102d24"
  red-dark: "#ff9699"
  red-bg-dark: "#351a20"
  amber-dark: "#f3c66d"
  amber-bg-dark: "#352c17"
  header-dark: "#0b1118"
  terminal-dark: "#0d141d"
  focus-dark: "#aea8ff"
  primary-hover: "#c81d14"
typography:
  headline:
    fontFamily: "Geist, system-ui, sans-serif"
    fontSize: "24px"
    fontWeight: 650
    lineHeight: 1.25
    letterSpacing: "-0.025em"
  title:
    fontFamily: "Geist, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 600
    letterSpacing: "-0.01em"
  body:
    fontFamily: "Geist, system-ui, sans-serif"
    fontSize: "13px"
    lineHeight: 1.5
  label:
    fontFamily: "Geist, system-ui, sans-serif"
    fontSize: "11px"
    fontWeight: 500
  mono:
    fontFamily: "JetBrains Mono, ui-monospace, monospace"
    fontSize: "11px"
    lineHeight: 1.5
rounded:
  panel: "7px"
  control: "4px"
  compact: "3px"
spacing:
  compact: "8px"
  field-gap: "14px"
  panel-padding: "18px"
  column-gap: "20px"
  page-padding: "24px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "#fff"
    rounded: "{rounded.control}"
    padding: "9px 13px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
    padding: "9px 13px"
  input:
    backgroundColor: "{colors.recess}"
    textColor: "{colors.text}"
    typography: "{typography.mono}"
    rounded: "{rounded.control}"
    padding: "9px 11px"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.panel}"
    padding: "{spacing.panel-padding}"
---
# Design System: YouTube Metadata Extractor

## Overview

**Creative North Star: "The Extraction Console"**

A compact operational console following the selected light and dark Stitch references. Dark navigation anchors both themes; lavender-tinted light surfaces and slate dark surfaces organize configuration, live summaries, and run records. Scarlet identifies primary actions and extraction controls.

Typography and tonal grouping carry hierarchy without decorative imagery. Keep the information density useful: clear labels, aligned metrics, restrained borders, and readable code previews.

**Key Characteristics:**
- Dark navigation across both themes.
- Scarlet primary actions; violet links and focus.
- Locally hosted Geist and JetBrains Mono.
- Configuration left, summary right; stacked phone layout.

## Colors

### Primary

Scarlet (`primary`) identifies primary buttons, range values, carets, and native selection controls. Its darker hover variant preserves the same character. Dark-theme range values use the lighter semantic red foreground for legibility.

### Secondary

Violet (`secondary`) marks links and secondary badges. The light and dark focus colors provide a distinct keyboard outline.

### Neutral

The light palette pairs a lavender canvas and recessed controls with white panels and navy text. The dark palette uses an ink canvas, slate panels, lighter recesses, and pale text. Borders and muted text change with the theme. Header and terminal surfaces stay dark in both modes.

Green, red, and amber are semantic status pairs with dedicated foregrounds and backgrounds. Running and failed badges currently share the red pair; succeeded uses green and cancelled uses amber. Preserve their explicit text labels.

**The Semantic Theme Rule.** Use the existing semantic variables; the `-dark` frontmatter entries document their dark-theme overrides, not additional UI roles.

## Typography

Geist supplies interface headings, labels, and body text. JetBrains Mono supplies field values, code, paths, badges, timestamps, and run metrics. Both variable fonts are hosted under `static/fonts/` with swap loading and system fallbacks.

The headline role becomes (21px) on phones. Paragraphs are smaller than the base body (12px), with relaxed line height (1.6). Metadata and badges use compact mono (10px). Numeric metrics use tabular figures; headline counters range from (25px) to (36px) according to component hierarchy.

## Layout

Main content is centered with a maximum width of (1600px). Standard page padding uses the page token, increases to (32px) at wide desktop, and becomes (20px 14px) on phones. The extraction workspace and keys page use a (2:1) grid with a minimum sidebar of (300px); history uses (2.5:1) with a minimum sidebar of (260px).

At (1150px), reduce form density and hide local workspace labels. At (850px), stack the main columns and place navigation on its own horizontally scrollable row; the extraction summary temporarily uses two columns. At (560px), stack summary panels, use a two-column stat strip, wrap filters, and put datetime fields in one column. Keep regular form pairs in two columns where implemented. Phone inputs and selects grow to at least (42px).

## Elevation & Depth

The interface is flat by default. Surface, recess, terminal tone, and thin borders establish depth. The selected source-mode segment alone uses a small shadow (`0 1px 3px #00000012`). Do not add ambient card shadows.

## Shapes

Panels use the panel radius; fields, buttons, metric recesses, and badges use the tighter control radius. Use thin borders and compact rectangular forms. Status dots are circular. Empty states use a dashed outline, preserving the same panel silhouette.

## Components

### Buttons

Primary buttons are solid scarlet with white text and a darker hover. Secondary buttons use the surface color, bordered edges, and a recessed hover. Text actions use violet with an underline on hover. Disabled buttons reduce opacity to (0.5). Preserve the global visible focus outline (2px), offset (3px).

### Inputs / Fields

Recessed mono fields use a transparent resting border, a visible neutral border on hover, and the theme focus border on focus. Native checkbox, radio, and range accents are scarlet. Textareas resize vertically. Labels and supporting text remain distinct from values.

### Navigation

The dark header uses compact links with pale text, subtle translucent hover fills, and a stronger selected fill and weight. The theme switch has both an icon and a target-theme text label. It follows stored preference or system preference on first load, persists explicit selection when storage is available, and continues working without storage.

### Chips

Badges are compact mono labels with lightly rounded corners. Semantic status badges pair readable text with a dot; secondary badges use violet. Badges are status or context labels, not large decorative pills.

### Cards / Containers

Bordered surface panels contain configuration, summaries, credentials, and run records. Panel padding uses the panel token and reduces to (15px) on phones. Run records use (16px) padding, a subtle hover border, metric grids, and a divided action row.

### Source Mode Switch

The segmented radio group uses a recessed outer track, a surface-colored checked segment, and the small selected shadow. Keyboard focus outlines the visible segment. On phones the segments fill the available width equally.

### Terminal

CLI and checkpoint previews retain dark terminal surfaces in either theme, pale headings, muted supporting text, and green mono code. Code regions scroll independently. Copy controls are compact translucent buttons.

Motion is limited to color and border transitions (120ms ease-out) when reduced motion is not requested. Avoid adding layout or entrance animation to these operational controls.

## Do's and Don'ts

### Do:

- Do use the existing semantic CSS variables so both themes remain coherent.
- Do retain text labels alongside status colors and dots.
- Do preserve visible keyboard focus and reduced-motion behavior.
- Do keep configuration before the summary in document and phone order.

### Don't:

- Don't replace the compact console hierarchy with oversized marketing typography.
- Don't flatten terminal previews into ordinary light panels.
- Don't use accent color as the only indication of state.
