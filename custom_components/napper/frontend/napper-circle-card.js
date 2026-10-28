/**
 * Napper Circle Card for Home Assistant Lovelace
 * Replicates the Napper app circular sleep tracker view in German,
 * including Wake-up, Tracked & Expected Naps, Bedtime, Countdown,
 * and actions to start/stop naps or log wake-up/bedtime now or X minutes ago.
 */

class NapperCircleCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._selectedEntityId = null;
    this._minutesAgo = 0;
    this._busyAction = null;
  }

  static getConfigElement() {
    return document.createElement("napper-circle-card-editor");
  }

  static getStubConfig(hass) {
    return {
      baby: "",
      show_nap_list: true,
      show_actions: true,
    };
  }

  setConfig(config) {
    const hasFixedChild = Boolean(
      config.baby || config.child || config.baby_id || config.entity
    );
    this._config = {
      show_nap_list: true,
      show_actions: true,
      show_baby_tabs: !hasFixedChild,
      ...config,
    };
    if (config.entity) {
      this._selectedEntityId = config.entity;
    } else if (!hasFixedChild) {
      // Multi-child mode keeps current selection or defaults to first child
    } else {
      this._selectedEntityId = null;
    }
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const resolved = this._resolveConfiguredBabyEntity(hass);
    if (resolved) {
      this._selectedEntityId = resolved.entity_id;
    } else if (!this._selectedEntityId) {
      const found = this._findAllBabyEntities(hass);
      if (found.length > 0) {
        this._selectedEntityId = found[0].entity_id;
      }
    }
    this._render();
  }

  getCardSize() {
    return 6;
  }

  _findAllBabyEntities(hass) {
    if (!hass || !hass.states) return [];
    const byBabyId = new Map();
    for (const [eid, stateObj] of Object.entries(hass.states)) {
      const summary = stateObj?.attributes?.summary;
      if (summary && summary.baby_id && summary.circle) {
        if (
          !byBabyId.has(summary.baby_id) ||
          eid.includes("nachstes_ereignis") ||
          eid.includes("upcoming_event") ||
          eid.includes("schlafstatus")
        ) {
          byBabyId.set(summary.baby_id, stateObj);
        }
      }
    }
    return Array.from(byBabyId.values());
  }

  _resolveConfiguredBabyEntity(hass) {
    if (!hass || !hass.states) return null;
    const allBabies = this._findAllBabyEntities(hass);
    if (allBabies.length === 0) return null;

    // 1. Check explicit baby / child / baby_id config (matches name or baby_id)
    const targetBaby = (
      this._config.baby ||
      this._config.child ||
      this._config.baby_id ||
      ""
    )
      .toString()
      .trim()
      .toLowerCase();

    if (targetBaby) {
      const match = allBabies.find((st) => {
        const s = st.attributes?.summary || {};
        return (
          String(s.baby_id || "").toLowerCase() === targetBaby ||
          String(s.baby_name || "").toLowerCase() === targetBaby
        );
      });
      if (match) return match;
    }

    // 2. Check explicit entity config (even if user picked a different sensor of the same child)
    if (this._config.entity && hass.states[this._config.entity]) {
      const configuredState = hass.states[this._config.entity];
      if (configuredState.attributes?.summary?.circle) {
        return configuredState;
      }
      const attrBabyId = configuredState.attributes?.baby_id;
      if (attrBabyId) {
        const matchByAttr = allBabies.find(
          (st) => st.attributes?.summary?.baby_id === attrBabyId
        );
        if (matchByAttr) return matchByAttr;
      }
    }

    return null;
  }

  _getActiveStateObj() {
    if (!this._hass) return null;
    const configured = this._resolveConfiguredBabyEntity(this._hass);
    if (configured) return configured;

    if (this._selectedEntityId && this._hass.states[this._selectedEntityId]) {
      const st = this._hass.states[this._selectedEntityId];
      if (st.attributes?.summary) return st;
    }
    const all = this._findAllBabyEntities(this._hass);
    return all.length > 0 ? all[0] : null;
  }

  // Convert Napper angle (-145..+145 where 0 is 12 o'clock) to SVG (x, y)
  _polarToCartesian(cx, cy, r, angleDeg) {
    const rad = ((angleDeg - 90) * Math.PI) / 180.0;
    return {
      x: cx + r * Math.cos(rad),
      y: cy + r * Math.sin(rad),
    };
  }

  _describeArc(cx, cy, r, startAngle, endAngle) {
    const clampedEnd = Math.max(startAngle + 0.5, endAngle);
    const start = this._polarToCartesian(cx, cy, r, startAngle);
    const end = this._polarToCartesian(cx, cy, r, clampedEnd);
    const largeArcFlag = clampedEnd - startAngle <= 180 ? "0" : "1";
    return [
      "M",
      start.x.toFixed(2),
      start.y.toFixed(2),
      "A",
      r,
      r,
      0,
      largeArcFlag,
      1,
      end.x.toFixed(2),
      end.y.toFixed(2),
    ].join(" ");
  }

  async _callNapperService(serviceName, babyId) {
    if (!this._hass || !babyId || this._busyAction) return;
    this._busyAction = serviceName;
    this._render();
    try {
      await this._hass.callService("napper", serviceName, {
        baby_id: babyId,
        minutes_ago: Number(this._minutesAgo) || 0,
      });
      this._minutesAgo = 0;
    } catch (err) {
      console.error("Napper service call failed:", err);
    } finally {
      setTimeout(() => {
        this._busyAction = null;
        this._render();
      }, 600);
    }
  }

  _renderSunCloudIcon(x, y, scale = 1) {
    return `
      <g transform="translate(${x}, ${y}) scale(${scale})">
        <!-- Sun rays & disc -->
        <circle cx="0" cy="-3" r="5.5" fill="#9c95ff" />
        <g stroke="#9c95ff" stroke-width="1.4" stroke-linecap="round">
          <line x1="0" y1="-11.5" x2="0" y2="-10" />
          <line x1="-6" y1="-9" x2="-4.8" y2="-7.8" />
          <line x1="6" y1="-9" x2="4.8" y2="-7.8" />
          <line x1="-8.5" y1="-3" x2="-7" y2="-3" />
          <line x1="8.5" y1="-3" x2="7" y2="-3" />
        </g>
        <!-- Cloud in front -->
        <path d="M -7 5 C -9.5 5 -11 3.2 -11 1 C -11 -1 -9.5 -2.6 -7.6 -2.8 C -6.8 -5.2 -4.5 -6.8 -1.8 -6.8 C 1.4 -6.8 4 -4.5 4.4 -1.5 C 6.4 -1.3 8 0.3 8 2.3 C 8 3.8 6.7 5 5 5 Z"
              fill="#e2e0ff" />
      </g>
    `;
  }

  _renderSunriseIcon(x, y) {
    return `
      <g transform="translate(${x}, ${y})">
        <path d="M -7 4 A 7 7 0 0 1 7 4 Z" fill="#f5c249" />
        <line x1="-10" y1="5.5" x2="10" y2="5.5" stroke="#f5c249" stroke-width="2" stroke-linecap="round" />
        <line x1="-6" y1="8.5" x2="6" y2="8.5" stroke="#f5c249" stroke-width="1.6" stroke-linecap="round" opacity="0.7" />
        <g stroke="#f5c249" stroke-width="1.5" stroke-linecap="round">
          <line x1="0" y1="-7" x2="0" y2="-5" />
          <line x1="-6.5" y1="-4.5" x2="-5" y2="-3" />
          <line x1="6.5" y1="-4.5" x2="5" y2="-3" />
        </g>
      </g>
    `;
  }

  _renderBedtimeIcon(x, y) {
    return `
      <g transform="translate(${x}, ${y})">
        <path d="M -7 3 A 7 7 0 0 1 7 3 Z" fill="#e5854b" />
        <path d="M -5 5 C -7 5 -8.5 3.8 -8.5 2.2 C -8.5 0.8 -7.3 -0.3 -5.8 -0.5 C -5 -2.2 -3.2 -3.3 -1 -3.3 C 1.5 -3.3 3.5 -1.6 3.8 0.6 C 5.3 0.8 6.5 2 6.5 3.4 C 6.5 4.3 5.5 5 4.2 5 Z"
              fill="#b96540" opacity="0.9" />
        <line x1="-9" y1="6.5" x2="9" y2="6.5" stroke="#e5854b" stroke-width="1.8" stroke-linecap="round" />
      </g>
    `;
  }

  _render() {
    if (!this.shadowRoot) return;
    const stateObj = this._getActiveStateObj();
    if (!stateObj || !stateObj.attributes?.summary) {
      this.shadowRoot.innerHTML = `
        <ha-card style="background:#15142b;color:#fff;padding:20px;border-radius:24px;">
          <div>Napper-Daten werden geladen… Bitte eine Napper-Entität auswählen.</div>
        </ha-card>
      `;
      return;
    }

    const summary = stateObj.attributes.summary;
    const allBabies = this._findAllBabyEntities(this._hass);
    const babyId = summary.baby_id;
    const babyName = summary.baby_name || "Baby";
    const wakeUp = summary.wake_up || {};
    const bedtime = summary.bedtime || {};
    const naps = summary.naps || [];
    const upcoming = summary.upcoming_event || {};
    const circle = summary.circle || {};

    const cx = 190;
    const cy = 185;
    const r = 122;
    const arcStart = circle.arc_start_deg ?? -145;
    const arcEnd = circle.arc_end_deg ?? 145;
    const nowAngle = circle.now_angle_deg ?? arcStart;

    const fullTrackPath = this._describeArc(cx, cy, r, arcStart, arcEnd);
    const progressPath =
      nowAngle > arcStart + 1
        ? this._describeArc(cx, cy, r, arcStart, Math.min(arcEnd, nowAngle))
        : "";

    const wakePos = this._polarToCartesian(cx, cy, r, arcStart);
    const bedPos = this._polarToCartesian(cx, cy, r, arcEnd);

    // Build SVG elements for each nap on the circle
    const napSvgItems = naps
      .map((nap) => {
        const sAng = nap.start_angle_deg ?? 0;
        const eAng = nap.end_angle_deg ?? sAng + 8;
        const midAng = nap.mid_angle_deg ?? (sAng + eAng) / 2;
        const midPos = this._polarToCartesian(cx, cy, r, midAng);
        const spanDeg = Math.max(eAng - sAng, 6);

        // Outer label positions
        const sLabelPos = this._polarToCartesian(cx, cy, r + 32, sAng - 2);
        const eLabelPos = this._polarToCartesian(cx, cy, r + 32, eAng + 2);
        const midLabelPos = this._polarToCartesian(cx, cy, r + 33, midAng);

        if (nap.is_tracked) {
          // Solid glowing capsule or circle (like Nap 1 and Nap 2 in the screenshot)
          const isWidePill = spanDeg >= 16;
          const pillPath = isWidePill
            ? this._describeArc(cx, cy, r, sAng, eAng)
            : "";
          return `
            <g class="nap-node tracked ${nap.is_open ? "open-nap" : ""}">
              ${
                isWidePill
                  ? `
                <path d="${pillPath}" fill="none" stroke="#9088ff" stroke-width="34" stroke-linecap="round" filter="url(#napGlow)" opacity="0.45" />
                <path d="${pillPath}" fill="none" stroke="#23204a" stroke-width="30" stroke-linecap="round" />
                <path d="${pillPath}" fill="none" stroke="#8b82ff" stroke-width="26" stroke-linecap="round" opacity="0.22" />
              `
                  : `
                <circle cx="${midPos.x.toFixed(1)}" cy="${midPos.y.toFixed(1)}" r="21" fill="#23204a" stroke="#8b82ff" stroke-width="2.5" filter="url(#napGlow)" />
              `
              }
              ${this._renderSunCloudIcon(midPos.x, midPos.y, 0.92)}
              <text x="${midLabelPos.x.toFixed(1)}" y="${midLabelPos.y.toFixed(1)}"
                    fill="#b8b3ff" font-size="10.5" font-weight="600" text-anchor="middle" dominant-baseline="middle">
                ${nap.start_time}–${nap.end_time}
              </text>
            </g>
          `;
        } else {
          // Expected nap: dotted ring + start/end labels outside the arc (like Nap 3 in screenshot)
          return `
            <g class="nap-node expected">
              <circle cx="${midPos.x.toFixed(1)}" cy="${midPos.y.toFixed(1)}" r="20"
                      fill="#1b1938" stroke="#7d75e6" stroke-width="2.4" stroke-dasharray="2.5 4.2" stroke-linecap="round" />
              ${this._renderSunCloudIcon(midPos.x, midPos.y, 0.88)}
              <text x="${sLabelPos.x.toFixed(1)}" y="${(midPos.y - 12).toFixed(1)}"
                    fill="#8f88ff" font-size="11" font-weight="500" text-anchor="middle">
                ${nap.start_time}
              </text>
              <text x="${eLabelPos.x.toFixed(1)}" y="${(midPos.y + 18).toFixed(1)}"
                    fill="#8f88ff" font-size="11" font-weight="500" text-anchor="middle">
                ${nap.end_time}
              </text>
            </g>
          `;
        }
      })
      .join("");

    const presetOffsets = [0, 5, 10, 15, 30, 60];

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", Roboto, sans-serif;
        }
        ha-card {
          background: radial-gradient(circle at 50% 28%, #221f4b 0%, #14122d 65%, #0e0d20 100%);
          color: #ffffff;
          border-radius: 28px;
          padding: 20px 18px 22px;
          box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45);
          border: 1px solid rgba(143, 136, 255, 0.16);
          position: relative;
          overflow: hidden;
        }
        .stars {
          position: absolute;
          inset: 0;
          pointer-events: none;
          background-image:
            radial-gradient(1.5px 1.5px at 18% 14%, rgba(255,255,255,0.55) 50%, transparent 100%),
            radial-gradient(1px 1px at 76% 12%, rgba(255,255,255,0.45) 50%, transparent 100%),
            radial-gradient(1.5px 1.5px at 84% 38%, rgba(255,255,255,0.4) 50%, transparent 100%),
            radial-gradient(1px 1px at 12% 52%, rgba(255,255,255,0.35) 50%, transparent 100%),
            radial-gradient(1.5px 1.5px at 64% 68%, rgba(255,255,255,0.35) 50%, transparent 100%),
            radial-gradient(1px 1px at 30% 74%, rgba(255,255,255,0.3) 50%, transparent 100%);
        }
        .top-bar {
          display: flex;
          align-items: center;
          justify-content: space-between;
          position: relative;
          z-index: 2;
          margin-bottom: 4px;
        }
        .baby-tabs {
          display: flex;
          gap: 10px;
          align-items: center;
        }
        .baby-avatar {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 5px 12px 5px 6px;
          border-radius: 999px;
          background: rgba(255, 255, 255, 0.07);
          border: 1.5px solid rgba(163, 156, 255, 0.25);
          color: #dcd9ff;
          cursor: pointer;
          font-size: 13px;
          font-weight: 600;
          transition: all 0.2s ease;
        }
        .baby-avatar.active {
          background: rgba(139, 130, 255, 0.22);
          border-color: #a69fff;
          color: #ffffff;
          box-shadow: 0 0 14px rgba(139, 130, 255, 0.35);
        }
        .avatar-circle {
          width: 28px;
          height: 28px;
          border-radius: 50%;
          background: linear-gradient(135deg, #6b63d6, #423c92);
          display: flex;
          align-items: center;
          justify-content: center;
          font-weight: 700;
          font-size: 14px;
          color: #fff;
        }
        .status-pill {
          font-size: 12px;
          font-weight: 600;
          padding: 5px 12px;
          border-radius: 999px;
          background: rgba(139, 130, 255, 0.16);
          color: #c9c4ff;
          border: 1px solid rgba(139, 130, 255, 0.3);
        }
        .status-pill.sleeping {
          background: rgba(110, 214, 154, 0.18);
          color: #8ff0b8;
          border-color: rgba(110, 214, 154, 0.4);
        }
        .dial-wrapper {
          position: relative;
          width: 100%;
          max-width: 380px;
          margin: 0 auto;
          z-index: 2;
        }
        svg.dial-svg {
          width: 100%;
          height: auto;
          display: block;
          overflow: visible;
        }
        .quick-stats {
          display: flex;
          justify-content: center;
          gap: 24px;
          margin: -6px 0 14px;
          position: relative;
          z-index: 2;
        }
        .stat-Bubble {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 4px;
        }
        .stat-circle {
          width: 46px;
          height: 46px;
          border-radius: 50%;
          background: rgba(38, 35, 78, 0.85);
          border: 1px solid rgba(143, 136, 255, 0.25);
          display: flex;
          align-items: center;
          justify-content: center;
          box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        }
        .stat-value {
          font-size: 13px;
          font-weight: 600;
          color: #9e96ff;
        }
        .stat-sub {
          font-size: 10.5px;
          color: rgba(255,255,255,0.52);
        }
        .nap-list {
          background: rgba(20, 18, 44, 0.65);
          border: 1px solid rgba(143, 136, 255, 0.15);
          border-radius: 18px;
          padding: 10px 14px;
          margin-bottom: 14px;
          position: relative;
          z-index: 2;
        }
        .nap-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 7px 0;
          border-bottom: 1px solid rgba(255, 255, 255, 0.06);
          font-size: 13px;
        }
        .nap-row:last-child {
          border-bottom: none;
        }
        .nap-name {
          font-weight: 600;
          color: #e4e2ff;
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .nap-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: #8f88ff;
        }
        .nap-dot.expected {
          background: transparent;
          border: 1.8px dashed #8f88ff;
        }
        .nap-times {
          color: #b7b2ec;
          font-variant-numeric: tabular-nums;
        }
        .nap-badge {
          font-size: 11px;
          padding: 2px 8px;
          border-radius: 999px;
          font-weight: 600;
        }
        .nap-badge.getrackt {
          background: rgba(139, 130, 255, 0.22);
          color: #c5bfff;
        }
        .nap-badge.erwartet {
          background: rgba(255, 255, 255, 0.07);
          color: rgba(255, 255, 255, 0.65);
          border: 1px dashed rgba(143, 136, 255, 0.4);
        }
        .nap-badge.aktiv {
          background: rgba(110, 214, 154, 0.22);
          color: #8ff0b8;
        }
        .actions-panel {
          background: rgba(28, 25, 60, 0.78);
          border: 1px solid rgba(143, 136, 255, 0.22);
          border-radius: 22px;
          padding: 12px;
          position: relative;
          z-index: 2;
        }
        .offset-row {
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          justify-content: space-between;
          gap: 6px;
          margin-bottom: 10px;
        }
        .offset-label {
          font-size: 12px;
          color: #b8b3e8;
          font-weight: 600;
        }
        .offset-chips {
          display: flex;
          flex-wrap: wrap;
          gap: 5px;
          align-items: center;
        }
        .chip {
          background: rgba(255, 255, 255, 0.07);
          border: 1px solid rgba(143, 136, 255, 0.22);
          color: #d6d3ff;
          border-radius: 999px;
          padding: 4px 9px;
          font-size: 11.5px;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.15s ease;
        }
        .chip.active {
          background: #7c73ff;
          color: #ffffff;
          border-color: #a9a3ff;
          box-shadow: 0 0 10px rgba(124, 115, 255, 0.45);
        }
        .custom-mins {
          width: 48px;
          background: rgba(0, 0, 0, 0.3);
          border: 1px solid rgba(143, 136, 255, 0.35);
          color: #fff;
          border-radius: 8px;
          padding: 3px 6px;
          font-size: 12px;
          text-align: center;
        }
        .action-buttons {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 8px;
        }
        @media (max-width: 420px) {
          .action-buttons {
            grid-template-columns: 1fr;
          }
        }
        .act-btn {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          padding: 10px 8px;
          border-radius: 14px;
          border: 1px solid rgba(163, 156, 255, 0.25);
          background: rgba(255, 255, 255, 0.07);
          color: #ffffff;
          font-size: 12.5px;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.15s ease;
        }
        .act-btn:hover:not(:disabled) {
          background: rgba(139, 130, 255, 0.25);
          border-color: #9e96ff;
        }
        .act-btn.primary:not(:disabled) {
          background: linear-gradient(135deg, rgba(124, 115, 255, 0.45), rgba(92, 83, 214, 0.45));
          border-color: #9e96ff;
        }
        .act-btn:disabled {
          opacity: 0.35;
          cursor: not-allowed;
          filter: grayscale(0.4);
        }
      </style>

      <ha-card>
        <div class="stars"></div>

        <!-- Top bar with child selector (or single-child header) & sleep status -->
        <div class="top-bar">
          <div class="baby-tabs">
            ${(this._config.show_baby_tabs ? allBabies : [stateObj])
              .map((st) => {
                const s = st.attributes.summary;
                const isSelected = st.entity_id === stateObj.entity_id;
                const initial = (s.baby_name || "B").charAt(0).toUpperCase();
                return `
                  <button class="baby-avatar ${isSelected ? "active" : ""}"
                          data-entity="${st.entity_id}"
                          style="${this._config.show_baby_tabs ? "" : "cursor:default;"}">
                    <span class="avatar-circle">${initial}</span>
                    <span>${s.baby_name}</span>
                  </button>
                `;
              })
              .join("")}
          </div>
          <div class="status-pill ${summary.is_sleeping ? "sleeping" : ""}">
            ${summary.sleep_state_de || "Wach"}
          </div>
        </div>

        <!-- Circular Napper Dial -->
        <div class="dial-wrapper">
          <svg class="dial-svg" viewBox="0 0 380 335">
            <defs>
              <filter id="napGlow" x="-40%" y="-40%" width="180%" height="180%">
                <feGaussianBlur stdDeviation="5" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>

            <!-- Horseshoe Background Track -->
            <path d="${fullTrackPath}"
                  fill="none"
                  stroke="#25224c"
                  stroke-width="26"
                  stroke-linecap="round" />

            <!-- Subtle Current-Time Progress Fill -->
            ${
              progressPath
                ? `<path d="${progressPath}"
                         fill="none"
                         stroke="#34306b"
                         stroke-width="26"
                         stroke-linecap="round" />`
                : ""
            }

            <!-- Naps along the arc -->
            ${napSvgItems}

            <!-- Wake-Up Node (Bottom-Left) -->
            <g class="wakeup-node">
              <circle cx="${wakePos.x.toFixed(1)}" cy="${wakePos.y.toFixed(1)}" r="21"
                      fill="#231f38"
                      stroke="#e8b439"
                      stroke-width="2.6"
                      ${wakeUp.is_tracked ? "" : 'stroke-dasharray="2.5 4"'} />
              ${this._renderSunriseIcon(wakePos.x, wakePos.y)}
              <text x="${wakePos.x.toFixed(1)}" y="${(wakePos.y + 37).toFixed(1)}"
                    fill="#e8b439" font-size="14" font-weight="600" text-anchor="middle">
                ${wakeUp.time || "--:--"}
              </text>
              <text x="${wakePos.x.toFixed(1)}" y="${(wakePos.y + 50).toFixed(1)}"
                    fill="rgba(232,180,57,0.65)" font-size="9.5" text-anchor="middle">
                ${wakeUp.status || ""}
              </text>
            </g>

            <!-- Bedtime Node (Bottom-Right) -->
            <g class="bedtime-node">
              <circle cx="${bedPos.x.toFixed(1)}" cy="${bedPos.y.toFixed(1)}" r="21"
                      fill="#231f38"
                      stroke="#d97b43"
                      stroke-width="2.6"
                      ${bedtime.is_tracked ? "" : 'stroke-dasharray="2.5 4"'} />
              ${this._renderBedtimeIcon(bedPos.x, bedPos.y)}
              <text x="${bedPos.x.toFixed(1)}" y="${(bedPos.y + 37).toFixed(1)}"
                    fill="#d97b43" font-size="14" font-weight="600" text-anchor="middle">
                ${bedtime.time || "--:--"}
              </text>
              <text x="${bedPos.x.toFixed(1)}" y="${(bedPos.y + 50).toFixed(1)}"
                    fill="rgba(217,123,67,0.65)" font-size="9.5" text-anchor="middle">
                ${bedtime.status || ""}
              </text>
            </g>

            <!-- Center Countdown Text (Exact Napper Layout) -->
            <text x="${cx}" y="${cy - 34}"
                  fill="#c7c3f0" font-size="15.5" font-weight="500" text-anchor="middle">
              ${upcoming.title_de || "Nächstes Ereignis"}
            </text>
            <text x="${cx}" y="${cy + 14}"
                  fill="#ffffff" font-size="46" font-weight="700" text-anchor="middle" letter-spacing="-0.5">
              ${upcoming.countdown_text || "--"}
            </text>
            <text x="${cx}" y="${cy + 42}"
                  fill="#a29dc9" font-size="14" font-weight="500" text-anchor="middle">
              ${upcoming.subtitle_de || ""}
            </text>
          </svg>
        </div>

        <!-- Bottom Napper Quick Bubbles (Awake time '1h 56m' + Total Day Sleep) -->
        <div class="quick-stats">
          <div class="stat-Bubble">
            <div class="stat-circle">
              <svg width="24" height="24" viewBox="-14 -14 28 28">
                ${this._renderSunCloudIcon(0, 0, 1.0)}
              </svg>
            </div>
            <div class="stat-value">${summary.awake_short || "0 min"}</div>
            <div class="stat-sub">Wachzeit</div>
          </div>

          <div class="stat-Bubble">
            <div class="stat-circle">
              <span style="font-size:18px;">💤</span>
            </div>
            <div class="stat-value">${summary.total_tracked_sleep_short || "0 min"} / ${summary.total_expected_sleep_short || "0 min"}</div>
            <div class="stat-sub">Tagesschlaf (getrackt / erw.)</div>
          </div>
        </div>

        <!-- Detailed Nap Schedule List -->
        ${
          this._config.show_nap_list
            ? `
          <div class="nap-list">
            <div class="nap-row">
              <div class="nap-name">☀️ Aufwachen</div>
              <div class="nap-times">${wakeUp.time || "--:--"} Uhr</div>
              <span class="nap-badge ${wakeUp.status}">${wakeUp.status}</span>
            </div>
            ${naps
              .map(
                (n) => `
              <div class="nap-row">
                <div class="nap-name">
                  <span class="nap-dot ${n.is_tracked ? "tracked" : "expected"}"></span>
                  ${n.label}
                </div>
                <div class="nap-times">
                  ${n.start_time} – ${n.end_time} (${n.duration_short})
                </div>
                <span class="nap-badge ${n.status}">${n.status}</span>
              </div>
            `
              )
              .join("")}
            <div class="nap-row">
              <div class="nap-name">🌙 Schlafenszeit</div>
              <div class="nap-times">${bedtime.time || "--:--"} Uhr</div>
              <span class="nap-badge ${bedtime.status}">${bedtime.status}</span>
            </div>
          </div>
        `
            : ""
        }

        <!-- Action Controls (Zeitdifferenz) -->
        ${
          this._config.show_actions
            ? `
          <div class="actions-panel">
            <div class="offset-row">
              <span class="offset-label">Zeitdifferenz: ${
                this._minutesAgo === 0 ? "0 Min. (Jetzt)" : `${this._minutesAgo} Min.`
              }</span>
              <div class="offset-chips">
                ${presetOffsets
                  .map(
                    (m) => `
                  <button class="chip ${this._minutesAgo === m ? "active" : ""}" data-mins="${m}">
                    ${m === 0 ? "0m" : `${m}m`}
                  </button>
                `
                  )
                  .join("")}
                <input type="number" min="0" max="720" class="custom-mins"
                       value="${this._minutesAgo}" title="Zeitdifferenz in Minuten" />
              </div>
            </div>

            <div class="action-buttons">
              <button class="act-btn ${summary.is_sleeping ? "primary" : ""}"
                      data-action="wake_up"
                      ${!summary.is_sleeping || this._busyAction ? "disabled" : ""}
                      title="${summary.is_sleeping ? "Aktuelles Nickerchen oder Nachtschlaf beenden" : "Nur aktiv, wenn das Kind gerade schläft"}">
                ☀️ Aufwachen ${this._minutesAgo > 0 ? `(-${this._minutesAgo}m)` : ""}
              </button>
              <button class="act-btn ${!summary.is_sleeping ? "primary" : ""}"
                      data-action="start_nap"
                      ${summary.is_sleeping || this._busyAction ? "disabled" : ""}
                      title="${!summary.is_sleeping ? "Nickerchen starten" : "Nicht möglich, da das Kind bereits schläft"}">
                ☁️ Nickerchen starten ${this._minutesAgo > 0 ? `(-${this._minutesAgo}m)` : ""}
              </button>
              <button class="act-btn"
                      data-action="start_sleep"
                      ${summary.is_sleeping || this._busyAction ? "disabled" : ""}
                      title="${!summary.is_sleeping ? "Nachtschlaf starten" : "Nicht möglich, da das Kind bereits schläft"}">
                🌙 Schlafen starten ${this._minutesAgo > 0 ? `(-${this._minutesAgo}m)` : ""}
              </button>
            </div>
          </div>
        `
            : ""
        }
      </ha-card>
    `;

    // Bind event listeners
    if (this._config.show_baby_tabs) {
      this.shadowRoot.querySelectorAll(".baby-avatar").forEach((btn) => {
        btn.addEventListener("click", () => {
          this._selectedEntityId = btn.getAttribute("data-entity");
          this._render();
        });
      });
    }

    this.shadowRoot.querySelectorAll(".chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        this._minutesAgo = Number(chip.getAttribute("data-mins")) || 0;
        this._render();
      });
    });

    const customInput = this.shadowRoot.querySelector(".custom-mins");
    if (customInput) {
      customInput.addEventListener("change", (e) => {
        this._minutesAgo = Math.max(0, Math.min(720, Number(e.target.value) || 0));
        this._render();
      });
    }

    this.shadowRoot.querySelectorAll(".act-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const action = btn.getAttribute("data-action");
        if (action) {
          this._callNapperService(action, babyId);
        }
      });
    });
  }
}

class NapperCircleCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
  }

  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _findBabies() {
    if (!this._hass || !this._hass.states) return [];
    const byId = new Map();
    for (const st of Object.values(this._hass.states)) {
      const s = st?.attributes?.summary;
      if (s && s.baby_id && s.circle && !byId.has(s.baby_id)) {
        byId.set(s.baby_id, {
          baby_id: s.baby_id,
          baby_name: s.baby_name || s.baby_id,
          entity_id: st.entity_id,
        });
      }
    }
    return Array.from(byId.values());
  }

  _emitConfig(newConfig) {
    this._config = newConfig;
    this.dispatchEvent(
      new CustomEvent("config-changed", {
        detail: { config: newConfig },
        bubbles: true,
        composed: true,
      })
    );
  }

  _render() {
    if (!this.shadowRoot) return;
    const babies = this._findBabies();
    const currentBaby = this._config.baby || this._config.baby_id || "";
    const showNapList = this._config.show_nap_list !== false;
    const showActions = this._config.show_actions !== false;

    this.shadowRoot.innerHTML = `
      <style>
        .editor {
          display: flex;
          flex-direction: column;
          gap: 14px;
          padding: 12px 4px;
          font-family: inherit;
        }
        .field {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        label {
          font-weight: 600;
          font-size: 14px;
        }
        select {
          padding: 8px 10px;
          border-radius: 8px;
          border: 1px solid var(--divider-color, #ccc);
          background: var(--card-background-color, #fff);
          color: var(--primary-text-color, #000);
          font-size: 14px;
        }
        .checkbox-row {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 14px;
        }
      </style>
      <div class="editor">
        <div class="field">
          <label for="baby-select">Kind auswählen:</label>
          <select id="baby-select">
            <option value="" ${currentBaby === "" ? "selected" : ""}>
              Alle Kinder (mit Tab-Umschalter)
            </option>
            ${babies
              .map(
                (b) => `
              <option value="${b.baby_name}" ${
                  currentBaby.toLowerCase() === b.baby_name.toLowerCase() ||
                  currentBaby === b.baby_id
                    ? "selected"
                    : ""
                }>
                Nur ${b.baby_name} (Einzelkarte)
              </option>
            `
              )
              .join("")}
          </select>
        </div>

        <label class="checkbox-row">
          <input type="checkbox" id="chk-nap-list" ${showNapList ? "checked" : ""} />
          Nickerchen-Liste unter dem Kreis anzeigen
        </label>

        <label class="checkbox-row">
          <input type="checkbox" id="chk-actions" ${showActions ? "checked" : ""} />
          Aktions-Buttons (Jetzt / Vor X Min.) anzeigen
        </label>
      </div>
    `;

    const sel = this.shadowRoot.querySelector("#baby-select");
    if (sel) {
      sel.addEventListener("change", (e) => {
        const val = e.target.value;
        const next = { ...this._config };
        delete next.entity;
        delete next.baby_id;
        if (val) {
          next.baby = val;
        } else {
          delete next.baby;
        }
        this._emitConfig(next);
      });
    }

    const chkNap = this.shadowRoot.querySelector("#chk-nap-list");
    if (chkNap) {
      chkNap.addEventListener("change", (e) => {
        this._emitConfig({ ...this._config, show_nap_list: e.target.checked });
      });
    }

    const chkAct = this.shadowRoot.querySelector("#chk-actions");
    if (chkAct) {
      chkAct.addEventListener("change", (e) => {
        this._emitConfig({ ...this._config, show_actions: e.target.checked });
      });
    }
  }
}

if (!customElements.get("napper-circle-card-editor")) {
  customElements.define("napper-circle-card-editor", NapperCircleCardEditor);
}

if (!customElements.get("napper-circle-card")) {
  customElements.define("napper-circle-card", NapperCircleCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "napper-circle-card")) {
  window.customCards.push({
    type: "napper-circle-card",
    name: "Napper Schlafkreis (Baby Sleep Circle)",
    preview: true,
    description: "Zeigt den Napper-Schlafkreis (für alle Kinder oder ein einzelnes Kind) auf Deutsch.",
  });
}
