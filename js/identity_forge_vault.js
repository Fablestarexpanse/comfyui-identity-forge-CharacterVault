/**
 * Identity Forge — Vault Preview extension.
 *
 * Adds to the IdentityForgeVaultLoad node:
 *
 * 1. **Inline preview** — when a character is selected the saved image loads
 *    into the node body immediately (before the workflow runs).
 *
 * 2. **Refresh button** — fetches the current vault list from the backend and
 *    updates the character dropdown without restarting ComfyUI.
 */

import { app } from "../../scripts/app.js";

const NONE_SENTINEL = "(no characters saved)";
const PREVIEW_URL   = (name) => `/identity_forge/vault/preview/${encodeURIComponent(name)}`;
const REFRESH_URL   = "/identity_forge/vault/characters";

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
