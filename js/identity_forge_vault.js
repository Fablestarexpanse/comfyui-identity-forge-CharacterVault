/**
 * Identity Forge — Vault Preview extension.
 *
 * Adds two pieces of UX to the IdentityForgeVaultLoad node:
 *
 * 1. **Hover preview**: When the character dropdown is open, mousing over any
 *    character name shows a floating thumbnail of their saved image.
 *
 * 2. **Inline node preview**: When a character is selected (even before the
 *    workflow runs), the node body shows the saved image so you always know
 *    which character is loaded.
 *
 * Both features are driven by the `/identity_forge/vault/preview/{name}`
 * endpoint registered in __init__.py.
 */

import { app } from "../../scripts/app.js";

const NONE_SENTINEL = "(no characters saved)";
const PREVIEW_URL = (name) =>
  `/identity_forge/vault/preview/${encodeURIComponent(name)}`;

// ── Floating Hover Tooltip ─────────────────────────────────────────────────
//
// A single shared <div> that floats next to the cursor over the dropdown.

let _tooltip = null;

function ensureTooltip() {
  if (_tooltip) return _tooltip;
  _tooltip = document.createElement("div");
  Object.assign(_tooltip.style, {
    position: "fixed",
    pointerEvents: "none",
    zIndex: "10000",
    display: "none",
    background: "#1a1a1a",
    border: "1px solid #555",
    borderRadius: "6px",
    padding: "5px",
    boxShadow: "0 6px 20px rgba(0,0,0,0.85)",
  });
  const img = document.createElement("img");
  Object.assign(img.style, {
    display: "block",
    maxWidth: "240px",
    maxHeight: "240px",
    objectFit: "contain",
    borderRadius: "3px",
  });
  _tooltip.appendChild(img);
  document.body.appendChild(_tooltip);
  return _tooltip;
}

function _placeTooltip(clientX, clientY) {
  if (!_tooltip) return;
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const w = _tooltip.offsetWidth || 250;
  const h = _tooltip.offsetHeight || 250;
  _tooltip.style.left = Math.min(clientX + 18, vw - w - 8) + "px";
  _tooltip.style.top = Math.max(8, Math.min(clientY, vh - h - 8)) + "px";
}

function showTooltip(characterName, clientX, clientY) {
  if (!characterName || characterName === NONE_SENTINEL) return;
  const el = ensureTooltip();
  const img = el.querySelector("img");
  const src = PREVIEW_URL(characterName);

  if (img.dataset.src !== src) {
    img.dataset.src = src;
    img.style.display = "none";
    img.onload = () => {
      img.style.display = "block";
      _placeTooltip(clientX, clientY);
    };
    img.onerror = () => {
      // Character not in vault or image missing — hide silently.
      hideTooltip();
    };
    img.src = src;
  }

  _placeTooltip(clientX, clientY);
  el.style.display = "block";
}

function hideTooltip() {
  if (_tooltip) _tooltip.style.display = "none";
}

// ── Context Menu Detection ────────────────────────────────────────────────
//
// LiteGraph combo dropdowns become a DOM element with class "litecontextmenu"
// appended directly to <body>.  We watch for that with a MutationObserver and,
// if the currently-hovered node is one of our VaultLoad nodes, attach
// mouseover handlers to each item so the tooltip fires.

const _menuObserver = new MutationObserver((mutations) => {
  const nodeOver = app.canvas?.node_over;
  if (!nodeOver || nodeOver.type !== "IdentityForgeVaultLoad") return;

  for (const m of mutations) {
    for (const added of m.addedNodes) {
      if (
        added instanceof HTMLElement &&
        added.classList.contains("litecontextmenu")
      ) {
        _attachHoverToMenu(added);
      }
    }
  }
});

function _attachHoverToMenu(menuEl) {
  // Each entry is a .litemenu-entry; the label lives in a child <span class="label">
  // or as plain textContent when there are no submenus.
  const entries = menuEl.querySelectorAll(".litemenu-entry");
  entries.forEach((entry) => {
    const labelEl = entry.querySelector(".label") || entry;
    const name = labelEl.textContent?.trim();
    if (!name || name === NONE_SENTINEL) return;

    entry.addEventListener("mouseenter", (e) =>
      showTooltip(name, e.clientX, e.clientY)
    );
    entry.addEventListener("mousemove", (e) =>
      _placeTooltip(e.clientX, e.clientY)
    );
    entry.addEventListener("mouseleave", hideTooltip);
  });

  // Hide when the whole menu is dismissed.
  menuEl.addEventListener("mouseleave", hideTooltip);
}

// ── Inline Node Preview ───────────────────────────────────────────────────
//
// When the user changes the character dropdown (before running the workflow),
// load the saved image into node.imgs so ComfyUI's built-in image-display
// system shows it inside the node body.

function _loadInlinePreview(node, characterName) {
  if (!characterName || characterName === NONE_SENTINEL) {
    node.imgs = null;
    node.setSizeForImage?.(true);
    node.setDirtyCanvas(true, true);
    return;
  }

  const img = new Image();
  img.onload = () => {
    node.imgs = [img];
    node.setSizeForImage?.();
    node.setDirtyCanvas(true, true);
  };
  img.onerror = () => {
    // Image missing or not yet saved — clear any stale preview.
    node.imgs = null;
    node.setSizeForImage?.(true);
    node.setDirtyCanvas(true, true);
  };
  img.src = PREVIEW_URL(characterName);
}

// ── Extension Registration ────────────────────────────────────────────────

app.registerExtension({
  name: "identity_forge.vault_preview",

  async setup() {
    // Watch for context menus added directly to <body> (LiteGraph behaviour).
    _menuObserver.observe(document.body, { childList: true });
  },

  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "IdentityForgeVaultLoad") return;

    const onCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      if (onCreated) onCreated.apply(this, arguments);

      const node = this;

      // Locate the character combo widget.
      const charWidget = node.widgets?.find((w) => w.name === "character");
      if (!charWidget) return;

      // Inline preview on dropdown change.
      const origCallback = charWidget.callback;
      charWidget.callback = function (value) {
        if (origCallback) origCallback.apply(this, arguments);
        _loadInlinePreview(node, value);
      };

      // Load the preview immediately for the current (default/restored) value.
      _loadInlinePreview(node, charWidget.value);
    };
  },
});
