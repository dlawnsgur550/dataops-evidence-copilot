---
name: DataOps Copilot
description: An evidence-bound incident workspace.
colors:
  ink: "#202735"
  secondary: "#606c7e"
  muted: "#6b7585"
  ground: "#fff"
  rail: "#f6f7f9"
  line: "#e5e8ee"
  blue: "#3157d5"
  blue-light: "#edf1ff"
  red: "#bd3444"
  red-light: "#fff2f2"
  green: "#16775e"
  green-light: "#eaf6f0"
  amber: "#936111"
  amber-light: "#fff7e7"
  focus: "#8ea4ff"
  navigation-selected: "#e8edff"
  panel-ground: "#fcfdff"
  comparison-bar: "#8197bb"
  separate-scope: "#b4c1d9"
typography:
  display:
    fontFamily: "Pretendard, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "26px"
    fontWeight: 720
    lineHeight: 1.4
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "Pretendard, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "20px"
    fontWeight: 690
    lineHeight: 1.5
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Pretendard, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "16px"
    fontWeight: 680
    lineHeight: 1.5
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Pretendard, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.6
  diagnosis:
    fontFamily: "Pretendard, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.85
  action:
    fontFamily: "Pretendard, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.8
  label:
    fontFamily: "Pretendard, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "12px"
    fontWeight: 590
    lineHeight: 1.5
  identifier:
    fontFamily: "ui-monospace, SFMono-Regular, Consolas, monospace"
    fontSize: "12px"
rounded:
  tag: "4px"
  control: "6px"
  region: "8px"
  popover: "10px"
  dialog: "12px"
  circle: "50%"
spacing:
  step-4: "4px"
  step-8: "8px"
  step-12: "12px"
  step-16: "16px"
  step-20: "20px"
  step-24: "24px"
  step-32: "32px"
components:
  button-primary:
    backgroundColor: "{colors.blue}"
    textColor: "{colors.ground}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "8px 13px"
    height: "40px"
  button-secondary:
    backgroundColor: "{colors.ground}"
    textColor: "#38465a"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "8px 13px"
    height: "40px"
  icon-button:
    textColor: "#667487"
    rounded: "{rounded.control}"
    height: "40px"
    width: "40px"
  select:
    backgroundColor: "{colors.ground}"
    textColor: "#36455a"
    rounded: "{rounded.control}"
    padding: "7px 28px 7px 10px"
    height: "40px"
  navigation-active:
    backgroundColor: "{colors.navigation-selected}"
    textColor: "#294bbe"
    rounded: "{rounded.control}"
    padding: "10px 12px"
  status-pass:
    backgroundColor: "{colors.green-light}"
    textColor: "{colors.green}"
    rounded: "{rounded.tag}"
    padding: "2px 6px"
  pipeline:
    backgroundColor: "{colors.panel-ground}"
    rounded: "{rounded.region}"
    padding: "24px 16px 19px"
  evidence-row:
    backgroundColor: "{colors.ground}"
    textColor: "#536379"
    padding: "12px 2px"
  claim-reference:
    textColor: "#53657d"
    padding: "7px 0"
  detail-dialog:
    textColor: "{colors.ink}"
    rounded: "{rounded.dialog}"
    width: "min(760px, calc(100vw - 32px))"
---
# Design System: DataOps Copilot

## Overview

**Creative North Star: "Precise validation record"**

A precise validation record: white work surfaces, a cool gray navigation rail, cobalt actions and selected states. Typography, dividers and aligned rows establish hierarchy; content remains close to its source.

This is an operating workspace with flat regions and compact native controls. The visual signature is an evidence reference that preserves its ID and temporal scope, opens source details, and emphasizes the related pipeline task when a mapping exists.

**Key Characteristics:**
- Evidence IDs and scope labels stay next to claims.
- A restrained cobalt accent and explicit red, amber and green states.
- Flat, divided regions with compact native interaction.

## Colors

### Primary
Cobalt (`blue`) marks explicit actions, selection, focused tasks and the selected-run share of the evidence strip. The pale counterpart supports selected context.

### Secondary
Red and its pale counterpart mean failure or rejected claims; amber means uncertainty, blocked dependencies or missing evidence; green means verified or successful states. Muted blue comparison bars distinguish the second measured series and separate observations.

### Neutral
White is the main ground; cool gray is the navigation rail; `ink` is primary text; `secondary` and `muted` support metadata. Hairline borders divide regions. `panel-ground` gives the pipeline and empty state a slight tonal separation. The YAML values are the canonical palette.

**The State has words Rule.** Pair state color with a label or icon; color alone does not carry a verdict.

## Typography

The self-hosted Pretendard variable face serves headings, body and controls with the recorded system fallbacks. Identifiers and source JSON use platform monospace; numbers use tabular figures where aligned.

The hierarchy is display (26px, 720), verdict headline (20px, 690), section title (16px, 680), body/action prose (14px), and compact control label (12px, 590). Diagnosis text has a more open line height (1.85) and a maximum measure (73ch); action steps use (1.8). Supporting metadata uses the existing 10–13px range and is not the body scale. Mobile display headings reduce to (24px). The current mobile diagnosis text reduces to (13px); this is an observed compact exception, not a reusable body rule.

**The Evidence continuity Rule.** Keep the same evidence ID and temporal-scope label in the claim reference and source detail. Emphasize a pipeline task only when the evidence maps to it.

## Layout

The desktop rail is fixed (218px), the topbar is (59px), and the content width is capped (1510px) with padding (28px 32px 40px). The diagnosis/source grid uses a flexible ratio (1.65:1), a source minimum (265px), and a gap (32px). A four-stage pipeline maintains equal-width task positions. Other surfaces reuse divided rows, tables and labeled comparative bars rather than a general card grid.

At (1150px), padding and the diagnosis gap tighten. At (900px), the rail becomes (190px), diagnosis/source regions stack, and source rows form two columns. At (680px), the rail becomes a native modal menu, the topbar becomes (56px), content padding becomes (22px 17px 32px), evidence rows and comparison regions become one column, recovery stages become two columns, and form fields fill the width. The four-stage pipeline stays intact with smaller nodes. Run IDs truncate within their region and run facts wrap. Tables scroll within their container.

## Elevation & Depth

Ordinary surfaces use a single border or a tonal shift. The selected case has a faint shadow; floating settings, native dialogs and toast feedback carry stronger shadows. Exact shadow and motion values live in the sidecar. State transitions are short (150ms); the busy spinner rotates over (700ms). Reduced-motion preferences disable animation, transitions and smooth scrolling.

**The Flat at rest Rule.** Use borders, spacing and tone for ordinary content. Reserve pronounced shadows for popovers, dialogs and transient feedback.

## Shapes

Control corners are gently rounded (6px); tags use (4px), pipeline and empty regions use (8px), floating settings use (10px), and dialogs use (12px). Status dots, verdict icons and task nodes are circular. Thin connectors link task nodes; blocked dependencies use a dashed connector. Icons and charts are native SVG geometry, not glyph illustrations.

## Components

### Buttons and fields
Primary buttons use cobalt with white text; secondary buttons use white with a light stroke. Both have a minimum height (40px), compact label type and horizontal padding (13px). Icon buttons are square (40px). Selects are native and share the control radius and minimum height. Buttons respond to hover with tone/stroke changes; disabled buttons reduce opacity (0.58). Interactive keyboard focus uses the recorded focus color with a solid outline (3px) and offset (3px). The skip link stays white on cobalt when focused or hovered.

### Navigation and status tags
Navigation is a quiet row list with icon, label and selected background; the active page has `aria-current`. Case rows pair a state dot with words and a compact identifier. Status tags pair a short verdict with the matching state palette. The small navigation section label names the case group; it is not a general-purpose promotional eyebrow pattern.

### Pipeline and evidence
Task nodes are native buttons with an icon, name and explicit state. Evidence rows open a native modal containing source JSON, the evidence ID and temporal scope. Claim references expose the same ID and scope alongside the diagnosis. Only task-context and dbt artifact evidence emphasize the associated incident task. The two-part scope strip shows actual evidence counts; it is not a live progress metric.

### Containers, tables and overlays
Content regions stay flat. Tables use a pale header, thin row dividers and aligned tabular values. Source JSON uses a bordered pale region with wrapping text and bounded scrolling. Native details expose optional settings or source records. The detail dialog has a sticky title area, close control, scrollable source body and dim backdrop. Loading, unavailable, error and empty states are explicit; transient feedback uses a bottom toast with live status.

## Do's and Don'ts

### Do:
- **Do** preserve native buttons, selects, checkboxes, details and dialogs with visible keyboard focus.
- **Do** keep desktop body and action prose at the recorded body size; ordinary action controls have a minimum height of 40px.
- **Do** display measured comparison bars with visible labels and values, and label the source and scope of those values.
- **Do** retain evidence IDs, temporal scope and source access when extending a screen.

### Don't:
- **Don't** substitute decorative charts, invented telemetry or quality metrics for available evidence.
- **Don't** infer historical absence of failure or complete recovery from a separate current observation.
- **Don't** reintroduce repeated statistic cards or decorative images into the selected-run workspace.
- **Don't** treat compact captions or the observed mobile diagnosis reduction as a new general body-text rule.
