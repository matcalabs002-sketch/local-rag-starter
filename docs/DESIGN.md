# Workspace design

The interface follows the [Apple design guidance](https://github.com/emilkowalski/skills/tree/main/skills/apple-design) requested for this project, adapted to Streamlit's native controls. It remains a light, local developer workspace with Chat, Sources, and Settings.

## Hierarchy

- A single translucent sidebar holds the brand, keyboard-accessible navigation, and readable service status.
- Main pages use short destination titles and supporting descriptions. The platform system font handles headings, body text, and controls; no font download is required.
- Solid white panels group forms, source information, and model settings against a neutral canvas. Translucency belongs to structural chrome rather than every card.
- User questions have a quiet blue surface. Assistant answers stay on white, with supporting evidence visually subordinate and expandable.
- The composer is one clear white surface. Real model/retrieval stages remain visible during processing; cosmetic animation does not stand in for progress.

## Tokens and input

Colors, surface roles, spacing, radii, focus treatment, and press timing live in `rag/workspace/style.css`. Native Streamlit controls keep their labels and keyboard semantics. Navigation icons are decorative SVG masks; the actual radio inputs remain focusable.

Press feedback starts immediately with CSS rather than waiting for a server round trip. Controls remain usable throughout transitions. This workspace does not introduce gesture-driven interactions or a motion library solely to demonstrate animation.

Reduced motion removes transitions and press scaling. Reduced transparency uses solid structural surfaces. Increased contrast strengthens secondary text and surface edges. Keyboard focus has an explicit ring, independent of selected navigation state.

## Privacy and verification

Source titles remain escaped, document excerpts and answers remain literal text, and service chrome never renders configuration secrets or raw diagnostics as HTML. Existing source/index/model safeguards are unchanged.

All release screenshots use the fictional handbook in a separate disposable local database, never the ordinary workspace library. Browser checks cover the three destinations at 320 px, 390 px, and 1440 px, keyboard navigation, a real cited answer, and reduced-motion/transparency behavior. Platform accessibility settings and physical browsers still need their own device-level checks.
