/**
 * Identity Forge — Vault Preview extension.
 *
 * Adds to the IdentityForgeVaultLoad node:
 *
 * 1. **Dropdown thumbnails** — when the character dropdown opens, each seed
 *    entry gets a 40×40 portrait thumbnail to its left so you can see who
 *    the character is before selecting them.
 *
 * 2. **Inline node preview** — when a character is selected the saved image
 *    loads into the node body immediately (before the workflow runs).
 *
 * 3. **Refresh button** — fetches the current vault list from the backend and
 *    updates the character dropdown without restarting ComfyUI.
 */

import { app } from "../../scripts/app.js";

const NONE_SENTINEL = "(no characters saved)";
const PREVIEW_URL   = (name) => `/identity_forge/vault/preview/${encodeURIComponent(name)}`;
const REFRESH_URL   = "/identity_forge/vault/characters";

// ── Dropdown thumbnail injection ──────────────────────────────────────────
//
// LiteGraph combo dropdowns are <div class="litegraph litecontextmenu"> elements
// appended directly to <body>. We intercept them with a MutationObserver and
// convert each entry into a flex row with a portrait thumbnail on the left.
//
// The observer is gated on app.canvas.node_over.type so it ONLY fires when the
// cursor is over an IdentityForgeVaultLoad node — no other node in ComfyUI is
// affected.

function _attachThumbsToMenu(menuEl) {
  try {
    const entries = menuEl.querySelectorAll(".litemenu-entry");
    entries.forEach((entry) => {
      try {
        // The character name lives in a child <span class="label"> or as
        // plain textContent when there are no submenus.
        const labelEl = entry.querySelector(".label") || entry;
        const name = labelEl.textContent?.trim();

        if (!name || name === NONE_SENTINEL) return;

        // Wrap the existing text in a span so we can flex alongside the image.
        const textSpan = document.createElement("span");
        Object.assign(textSpan.style, {
          flex: "1",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        });
        textSpan.textContent = name;

        // Thumbnail image — grey background acts as a loading placeholder.
        const img = document.createElement("img");
        Object.assign(img.style, {
          width: "40px",
          height: "40px",
          objectFit: "cover",
          borderRadius: "3px",
          flexShrink: "0",
          background: "#333",
          display: "block",
        });
        img.onerror = () => {
          img.style.display = "none";
        };
        img.src = PREVIEW_URL(name);

        // Replace the entry's content with a flex row.
        entry.innerHTML = "";
        Object.assign(entry.style, {
          display: "flex",
          alignItems: "center",
          gap: "8px",
          padding: "4px 6px",
          minHeight: "48px",
          boxSizing: "border-box",
        });
        entry.appendChild(img);
        entry.appendChild(textSpan);
      } catch (_) {}
    });
  } catch (_) {}
}

const _menuObserver = new MutationObserver((mutations) => {
  try {
    const nodeOver = app.canvas?.node_over;
    if (!nodeOver || nodeOver.type !== "IdentityForgeVaultLoad") return;

    for (const m of mutations) {
      for (const added of m.addedNodes) {
        if (
          added instanceof HTMLElement &&
          added.classList.contains("litecontextmenu")
        ) {
          _attachThumbsToMenu(added);
        }
      }
    }
  } catch (_) {}
});

// ── Inline node image preview ─────────────────────────────────────────────

function setNodePreview(node, characterName) {
  try {
    if (!characterName || characterName === NONE_SENTINEL) {
      node.imgs = null;
      node.setSizeForImage?.(true);
      node.setDirtyCanvas?.(true, true);
      return;
    }

    const img = new Image();

    img.onload = () => {
      try {
        node.imgs = [img];
        node.setSizeForImage?.();
        node.setDirtyCanvas?.(true, true);
      } catch (_) {}
    };

    img.onerror = () => {
      try {
        node.imgs = null;
        node.setSizeForImage?.(true);
        node.setDirtyCanvas?.(true, true);
      } catch (_) {}
    };

    img.src = PREVIEW_URL(characterName);
  } catch (_) {}
}

// ── Extension ─────────────────────────────────────────────────────────────

app.registerExtension({
  name: "identity_forge.vault_preview",

  async setup() {
    // Watch for context menus added directly to <body> (LiteGraph behaviour).
    // childList: true is sufficient — context menus are direct children of body.
    _menuObserver.observe(document.body, { childList: true });
  },

  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "IdentityForgeVaultLoad") return;

    try {
      const onCreated = nodeType.prototype.onNodeCreated;

      nodeType.prototype.onNodeCreated = function () {
        try {
          if (onCreated) onCreated.apply(this, arguments);

          const node = this;

          // Find the character combo widget.
          const charWidget = node.widgets?.find((w) => w.name === "character");
          if (!charWidget) return;

          // Update inline preview whenever the dropdown value changes.
          const origCallback = charWidget.callback;
          charWidget.callback = function (value) {
            try { if (origCallback) origCallback.apply(this, arguments); } catch (_) {}
            setNodePreview(node, value);
          };

          // ── Refresh button ───────────────────────────────────────────────
          node.addWidget(
            "button",
            "↺  Refresh Character List",
            null,
            () => {
              fetch(REFRESH_URL)
                .then((r) => r.json())
                .then((names) => {
                  if (!Array.isArray(names) || names.length === 0) return;
                  charWidget.options.values = names;
                  // Keep current selection if still valid, else pick first.
                  if (!names.includes(charWidget.value)) {
                    charWidget.value = names[0];
                    setNodePreview(node, names[0]);
                  }
                  node.setDirtyCanvas?.(true, true);
                })
                .catch((err) => {
                  console.warn("[IdentityForge Vault] Refresh failed:", err);
                });
            },
            { serialize: false },
          );

          // Show preview for the current (default / workflow-restored) value.
          const initial = charWidget.value;
          if (initial && initial !== NONE_SENTINEL) {
            setTimeout(() => setNodePreview(node, initial), 50);
          }
        } catch (_) {}
      };
    } catch (_) {}
  },
});
