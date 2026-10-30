/**
 * Napper Timeline Card for Home Assistant Lovelace
 * Vertical timeline view showing:
 * - Aufwachzeit (Morning Wake Up)
 * - 1. Nickerchen, 2. Nickerchen, ... (only planned/predicted or tracked naps)
 * - Schlafenszeit (Night Sleep)
 * - Visual marker for the current ongoing point in time
 * - Bottom action buttons: Aufwachen, Nickerchen starten, Schlafen starten
 */

class NapperCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._selectedEntityId = null;
    this._busyAction = null;
  }

  static getConfigElement() {
    return document.createElement("napper-card-editor");
  }

  static getStubConfig() {
    return {
      baby: "",
      show_actions: true,
    };
  }

  setConfig(config) {
    const safeConfig = config && typeof config === "object" ? config : {};
    const hasFixedChild = Boolean(
      safeConfig.baby || safeConfig.child || safeConfig.baby_id || safeConfig.entity
    );
    this._config = {
      show_actions: true,
      show_baby_tabs: !hasFixedChild,
      show_header: false,
      ...safeConfig,
    };
    if (safeConfig.entity) {
      this._selectedEntityId = safeConfig.entity;
    } else if (hasFixedChild) {
      this._selectedEntityId = null;
    }
    try {
      this._render();
    } catch (err) {
      console.error("NapperCard render error in setConfig:", err);
    }
  }

  set hass(hass) {
    this._hass = hass;
    try {
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
    } catch (err) {
      console.error("NapperCard render error in set hass:", err);
    }
  }

  getCardSize() {
    return 5;
  }

  _findAllBabyEntities(hass) {
    if (!hass || !hass.states) return [];
    const byBabyId = new Map();
    for (const [eid, stateObj] of Object.entries(hass.states)) {
      const summary = stateObj?.attributes?.summary;
      if (summary && summary.baby_id) {
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

    if (this._config.entity && hass.states[this._config.entity]) {
      const configuredState = hass.states[this._config.entity];
      if (configuredState.attributes?.summary) {
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

  _formatDurationCompact(minutes) {
    const mins = Math.max(0, Math.round(Number(minutes) || 0));
    if (mins < 60) {
      return `${mins}m`;
    }
    const h = Math.floor(mins / 60);
    const rem = mins % 60;
    return rem === 0 ? `${h}h` : `${h}h ${rem}m`;
  }

  _formatNowTime() {
    const now = new Date();
    const hh = String(now.getHours()).padStart(2, "0");
    const mm = String(now.getMinutes()).padStart(2, "0");
    return `${hh}:${mm}`;
  }

  async _callNapperService(serviceName, babyId) {
    if (!this._hass || !babyId || this._busyAction) return;
    this._busyAction = serviceName;
    this._render();
    try {
      await this._hass.callService("napper", serviceName, {
        baby_id: babyId,
      });
    } catch (err) {
      console.error("Napper service call failed:", err);
    } finally {
      setTimeout(() => {
        this._busyAction = null;
        this._render();
      }, 600);
    }
  }

  _buildTimelineItems(summary) {
    const nowMs = Date.now();
    const wakeUp = summary.wake_up || {};
    const bedtime = summary.bedtime || {};
    const upcoming = summary.upcoming_event || {};
    const naps = Array.isArray(summary.naps) ? summary.naps : [];
    const isNightSleeping =
      Boolean(bedtime.is_open) ||
      (Boolean(summary.is_sleeping) && summary.sleep_state_de === "Nachtschlaf");

    // Night-sleep view: Schlafenszeit on top, predicted Aufwachzeit on the bottom
    if (isNightSleeping) {
      const bedMs = bedtime.iso ? Date.parse(bedtime.iso) : null;
      const predictedWakeTime =
        (upcoming.type === "WAKE_UP" && upcoming.target_time) ||
        wakeUp.time ||
        "--:--";
      const predictedWakeIso =
        (upcoming.type === "WAKE_UP" && upcoming.target_iso) || wakeUp.iso;
      const wakeMs = predictedWakeIso ? Date.parse(predictedWakeIso) : null;
      const elapsedSuffix =
        bedtime.duration_minutes > 0
          ? `  •  ${this._formatDurationCompact(bedtime.duration_minutes)}`
          : "";
      const pausedSuffix =
        bedtime.is_paused || summary.is_night_sleep_paused
          ? "  •  pausiert"
          : "";

      return [
        {
          id: "bedtime",
          type: "bedtime",
          icon: "🌙",
          title: "Schlafenszeit",
          subtitle: `${bedtime.time || "--:--"}${elapsedSuffix}${pausedSuffix}`,
          state: "ongoing",
          startMs: bedMs,
          endMs: bedMs,
        },
        {
          id: "wake_up",
          type: "wake_up",
          icon: "☀️",
          title: "Aufwachzeit",
          subtitle: predictedWakeTime,
          state: "future",
          startMs: wakeMs,
          endMs: wakeMs,
        },
      ];
    }

    const items = [];

    // 1. Aufwachzeit ("Morning Wake Up")
    const wakeMs = wakeUp.iso ? Date.parse(wakeUp.iso) : null;
    const wakeInPast = Boolean(
      wakeUp.is_tracked || (wakeMs !== null && !isNaN(wakeMs) && wakeMs <= nowMs)
    );
    items.push({
      id: "wake_up",
      type: "wake_up",
      icon: "☀️",
      title: "Aufwachzeit",
      subtitle: wakeUp.time || "--:--",
      state: wakeInPast ? "past" : "future",
      startMs: wakeMs,
      endMs: wakeMs,
    });

    // 2. All planned or tracked Naps ("1. Nickerchen", "2. Nickerchen", etc.)
    naps.forEach((nap, idx) => {
      if (!nap || (!nap.start_time && !nap.end_time)) return;
      if (nap.status === "nicht_geplant" || nap.geplant === false) return;

      const napNum = nap.nap_number || idx + 1;
      const startMs = nap.start_iso ? Date.parse(nap.start_iso) : null;
      const endMs = nap.end_iso ? Date.parse(nap.end_iso) : startMs;
      const isOpen = Boolean(nap.is_open);
      const isTracked = Boolean(nap.is_tracked);

      let state = "future";
      let icon = "⏳";
      let subtitle = "";

      if (isOpen) {
        state = "ongoing";
        icon = "💤";
        const elapsed = this._formatDurationCompact(nap.duration_minutes);
        const expected = this._formatDurationCompact(
          nap.expected_duration_minutes || nap.duration_minutes
        );
        const pausedLabel = nap.is_paused ? "  •  pausiert" : "";
        subtitle = `${nap.start_time} - ${nap.end_time}  •  ${elapsed} (~${expected})${pausedLabel}`;
      } else if (isTracked) {
        state = "past";
        icon = "💤";
        const dur = this._formatDurationCompact(nap.duration_minutes);
        subtitle = `${nap.start_time} - ${nap.end_time}  •  ${dur}`;
      } else {
        state = "future";
        icon = "⏳";
        const dur = this._formatDurationCompact(
          nap.expected_duration_minutes || nap.duration_minutes
        );
        subtitle = `${nap.start_time} - ${nap.end_time}  •  ~${dur}`;
      }

      items.push({
        id: `nap_${napNum}`,
        type: "nap",
        icon,
        title: `${napNum}. Nickerchen`,
        subtitle,
        state,
        startMs,
        endMs,
      });
    });

    // 3. Schlafenszeit ("Night Sleep")
    const bedMs = bedtime.iso ? Date.parse(bedtime.iso) : null;
    const bedOngoing = Boolean(bedtime.is_open || isNightSleeping);
    const bedInPast = Boolean(bedtime.is_tracked && !bedOngoing);
    items.push({
      id: "bedtime",
      type: "bedtime",
      icon: "🌙",
      title: "Schlafenszeit",
      subtitle: bedtime.time || "--:--",
      state: bedOngoing ? "ongoing" : bedInPast ? "past" : "future",
      startMs: bedMs,
      endMs: bedMs,
    });

    // Determine where the current ongoing point in time is located:
    // - If an item has state === "ongoing", that item itself is marked as current.
    // - Otherwise, find the transition between the last "past" item and the first "future" item
    //   and mark `showNowAfter: true` on the last past item (or before the first item if none is past).
    const hasOngoingItem = items.some((it) => it.state === "ongoing");
    if (!hasOngoingItem) {
      let lastPastIdx = -1;
      for (let i = 0; i < items.length; i++) {
        if (items[i].state === "past") {
          lastPastIdx = i;
        }
      }
      if (lastPastIdx >= 0 && lastPastIdx < items.length - 1) {
        items[lastPastIdx].showNowAfter = true;
      } else if (lastPastIdx === -1 && items.length > 0) {
        items[0].showNowBefore = true;
      }
    }

    return items;
  }

  _render() {
    if (!this.shadowRoot) return;
    const stateObj = this._getActiveStateObj();
    if (!stateObj || !stateObj.attributes?.summary) {
      this.shadowRoot.innerHTML = `
        <ha-card style="padding:22px;">
          <div>Napper-Daten werden geladen…</div>
        </ha-card>
      `;
      return;
    }

    const summary = stateObj.attributes.summary;
    const allBabies = this._findAllBabyEntities(this._hass);
    const babyId = summary.baby_id;
    const babyName = summary.baby_name || "Baby";
    const isSleeping = Boolean(summary.is_sleeping);
    const isNapActive =
      Boolean(summary.is_nap_active) ||
      (isSleeping && summary.sleep_state_de === "Nickerchen");
    const isNapPaused = Boolean(summary.is_nap_paused);
    const isNightSleepActive =
      Boolean(summary.is_night_sleep_active) ||
      Boolean(summary.bedtime?.is_open) ||
      (isSleeping && summary.sleep_state_de === "Nachtschlaf");
    const isNightSleepPaused = Boolean(
      summary.is_night_sleep_paused || summary.bedtime?.is_paused
    );
    const timelineItems = this._buildTimelineItems(summary);

    // Build only the currently relevant action buttons (hide all disabled buttons)
    const actionButtons = [];
    if (isNapActive) {
      if (isNapPaused) {
        actionButtons.push({
          action: "resume_nap",
          icon: "▶️",
          label: "Nickerchen fortsetzen",
          title: "Pausiertes Nickerchen fortsetzen",
          highlighted: true,
        });
      } else {
        actionButtons.push({
          action: "pause_nap",
          icon: "⏸️",
          label: "Nickerchen pausieren",
          title: "Laufendes Nickerchen pausieren",
          highlighted: false,
        });
      }
      actionButtons.push({
        action: "wake_up",
        icon: "☀️",
        label: "Aufwachen",
        title: "Aktuelles Nickerchen beenden",
        highlighted: !isNapPaused,
      });
    } else if (isNightSleepActive) {
      if (isNightSleepPaused) {
        actionButtons.push({
          action: "resume_sleep",
          icon: "▶️",
          label: "Schlafen fortsetzen",
          title: "Nächtliches Aufwachen beenden und Nachtschlaf fortsetzen",
          highlighted: true,
        });
      } else {
        actionButtons.push({
          action: "pause_sleep",
          icon: "⏸️",
          label: "Schlafen pausieren",
          title: "Nächtliches Aufwachen starten",
          highlighted: false,
        });
      }
      actionButtons.push({
        action: "wake_up",
        icon: "☀️",
        label: "Aufwachen",
        title: "Nachtschlaf beenden (Morgens aufgewacht)",
        highlighted: !isNightSleepPaused,
      });
    } else {
      actionButtons.push(
        {
          action: "start_nap",
          icon: "💤",
          label: "Nickerchen",
          title: "Nickerchen starten",
          highlighted: true,
        },
        {
          action: "start_sleep",
          icon: "🌙",
          label: "Schlafen",
          title: "Nachtschlaf starten",
          highlighted: false,
        }
      );
    }

    const showTabs = Boolean(this._config.show_baby_tabs && allBabies.length > 1);
    const showHeader = Boolean(this._config.show_header && !showTabs);

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          font-family: var(--paper-font-body1_-_font-family, -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif);
        }
        ha-card {
          background: var(--ha-card-background, var(--card-background-color, #ffffff));
          color: var(--primary-text-color, #1c1c1e);
          border-radius: var(--ha-card-border-radius, 12px);
          padding: 22px 20px 16px;
          box-shadow: var(--ha-card-box-shadow, none);
          border-width: var(--ha-card-border-width, 1px);
          border-style: solid;
          border-color: var(--ha-card-border-color, var(--divider-color, rgba(0, 0, 0, 0.12)));
          box-sizing: border-box;
        }
        .baby-tabs {
          display: flex;
          gap: 8px;
          margin-bottom: 18px;
          flex-wrap: wrap;
        }
        .baby-tab {
          background: var(--secondary-background-color, rgba(127, 127, 127, 0.08));
          border: 1px solid var(--divider-color, rgba(127, 127, 127, 0.22));
          color: var(--secondary-text-color, #6e6e73);
          border-radius: 999px;
          padding: 5px 14px;
          font-size: 13px;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.15s ease;
        }
        .baby-tab.active {
          background: color-mix(in srgb, var(--primary-color, #03a9f4) 15%, transparent);
          border-color: var(--primary-color, #03a9f4);
          color: var(--primary-text-color, #1c1c1e);
        }
        .card-header-title {
          font-size: 16px;
          font-weight: 700;
          color: var(--primary-text-color, #1c1c1e);
          margin-bottom: 16px;
        }
        .timeline {
          display: flex;
          flex-direction: column;
          position: relative;
        }
        .timeline-item {
          display: flex;
          align-items: flex-start;
          gap: 16px;
          position: relative;
          padding-bottom: 22px;
        }
        .timeline-item:last-child {
          padding-bottom: 4px;
        }
        /* Vertical line connecting the circles */
        .timeline-item:not(:last-child)::after {
          content: "";
          position: absolute;
          left: 19px;
          top: 38px;
          bottom: 0;
          width: 1.5px;
          transform: translateX(-50%);
          background: var(--divider-color, rgba(127, 127, 127, 0.25));
          z-index: 1;
        }
        .timeline-item.state-past:not(:last-child)::after {
          background: var(--primary-color, #03a9f4);
          opacity: 0.35;
        }
        .icon-circle {
          width: 38px;
          height: 38px;
          border-radius: 50%;
          background: var(--secondary-background-color, rgba(127, 127, 127, 0.08));
          border: 1.5px solid var(--divider-color, rgba(127, 127, 127, 0.28));
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
          font-size: 17px;
          line-height: 1;
          position: relative;
          z-index: 2;
          box-sizing: border-box;
        }
        .timeline-item.state-ongoing .icon-circle {
          border-color: var(--primary-color, #03a9f4);
          background: color-mix(in srgb, var(--primary-color, #03a9f4) 14%, transparent);
          box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary-color, #03a9f4) 18%, transparent);
        }
        .item-content {
          display: flex;
          flex-direction: column;
          justify-content: center;
          min-height: 38px;
          flex: 1;
        }
        .item-title-row {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 2px;
        }
        .item-title {
          font-size: 15.5px;
          font-weight: 700;
          color: var(--primary-text-color, #1c1c1e);
          line-height: 1.25;
        }
        .timeline-item.state-future .item-title {
          font-weight: 600;
          font-style: italic;
          color: var(--secondary-text-color, #6e6e73);
        }
        .item-subtitle {
          font-size: 14px;
          font-weight: 400;
          color: var(--secondary-text-color, #6e6e73);
          line-height: 1.3;
          font-variant-numeric: tabular-nums;
        }
        .timeline-item.state-future .item-subtitle {
          font-style: italic;
          color: var(--secondary-text-color, #8e8e93);
          opacity: 0.85;
        }
        .timeline-item.state-ongoing .item-subtitle {
          color: var(--primary-color, #0288d1);
          font-weight: 500;
        }
        .pulse-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: var(--primary-color, #03a9f4);
          box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary-color, #03a9f4) 22%, transparent);
          flex-shrink: 0;
        }
        /* Current point in time dot between past and future events */
        .now-marker {
          display: flex;
          align-items: center;
          position: relative;
          padding-bottom: 14px;
          margin-top: -8px;
        }
        .now-marker::after {
          content: "";
          position: absolute;
          left: 19px;
          top: 10px;
          bottom: 0;
          width: 1.5px;
          transform: translateX(-50%);
          background: var(--divider-color, rgba(127, 127, 127, 0.25));
          z-index: 1;
        }
        .now-dot-wrap {
          width: 38px;
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
          z-index: 2;
        }
        .now-dot {
          width: 9px;
          height: 9px;
          border-radius: 50%;
          background: var(--primary-color, #03a9f4);
          box-shadow: 0 0 0 4px color-mix(in srgb, var(--primary-color, #03a9f4) 22%, transparent);
        }
        .divider {
          height: 1px;
          background: var(--divider-color, rgba(127, 127, 127, 0.2));
          margin: 16px 0 12px;
        }
        .actions-bar {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(0, 1fr));
          gap: 8px;
          align-items: stretch;
        }
        .action-btn {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 8px;
          padding: 12px 6px;
          border-radius: 10px;
          border: none;
          background: transparent;
          color: var(--primary-color, #0288d1);
          cursor: pointer;
          transition: background 0.15s ease, opacity 0.15s ease;
          text-align: center;
        }
        .action-btn.highlighted:not(:disabled) {
          background: color-mix(in srgb, var(--primary-color, #03a9f4) 12%, transparent);
        }
        .action-btn:hover:not(:disabled) {
          background: color-mix(in srgb, var(--primary-color, #03a9f4) 20%, transparent);
        }
        .action-btn:disabled {
          opacity: 0.35;
          cursor: not-allowed;
        }
        .action-icon {
          font-size: 19px;
          line-height: 1;
        }
        .action-label {
          font-size: 12px;
          font-weight: 700;
          letter-spacing: 0.5px;
          color: var(--primary-color, #0288d1);
          text-transform: uppercase;
          line-height: 1.2;
        }
      </style>

      <ha-card>
        ${
          showTabs
            ? `
          <div class="baby-tabs">
            ${allBabies
              .map((st) => {
                const s = st.attributes.summary;
                const active = st.entity_id === stateObj.entity_id;
                return `
                  <button class="baby-tab ${active ? "active" : ""}" data-entity="${st.entity_id}">
                    ${s.baby_name}
                  </button>
                `;
              })
              .join("")}
          </div>
        `
            : showHeader
            ? `<div class="card-header-title">${babyName}</div>`
            : ""
        }

        <div class="timeline">
          ${timelineItems
            .map((item) => {
              const nowRowHtml = `
                <div class="now-marker">
                  <div class="now-dot-wrap">
                    <div class="now-dot"></div>
                  </div>
                </div>
              `;

              const itemHtml = `
                <div class="timeline-item state-${item.state}">
                  <div class="icon-circle">
                    <span>${item.icon}</span>
                  </div>
                  <div class="item-content">
                    <div class="item-title-row">
                      <span class="item-title">${item.title}</span>
                      ${item.state === "ongoing" ? `<span class="pulse-dot"></span>` : ""}
                    </div>
                    <div class="item-subtitle">${item.subtitle}</div>
                  </div>
                </div>
              `;

              if (item.showNowBefore) {
                return nowRowHtml + itemHtml;
              }
              if (item.showNowAfter) {
                return itemHtml + nowRowHtml;
              }
              return itemHtml;
            })
            .join("")}
        </div>

        ${
          this._config.show_actions !== false && actionButtons.length > 0
            ? `
          <div class="divider"></div>
          <div class="actions-bar">
            ${actionButtons
              .map(
                (btn) => `
              <button class="action-btn ${btn.highlighted ? "highlighted" : ""}"
                      data-action="${btn.action}"
                      ${this._busyAction ? "disabled" : ""}
                      title="${btn.title}">
                <span class="action-icon">${btn.icon}</span>
                <span class="action-label">${btn.label}</span>
              </button>
            `
              )
              .join("")}
          </div>
        `
            : ""
        }
      </ha-card>
    `;

    if (showTabs) {
      this.shadowRoot.querySelectorAll(".baby-tab").forEach((btn) => {
        btn.addEventListener("click", () => {
          this._selectedEntityId = btn.getAttribute("data-entity");
          this._render();
        });
      });
    }

    this.shadowRoot.querySelectorAll(".action-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const action = btn.getAttribute("data-action");
        if (action) {
          this._callNapperService(action, babyId);
        }
      });
    });
  }
}

class NapperCardEditor extends HTMLElement {
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
      if (s && s.baby_id && !byId.has(s.baby_id)) {
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
    const showActions = this._config.show_actions !== false;
    const showHeader = Boolean(this._config.show_header);

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
          <input type="checkbox" id="chk-header" ${showHeader ? "checked" : ""} />
          Name des Kindes als Überschrift anzeigen
        </label>

        <label class="checkbox-row">
          <input type="checkbox" id="chk-actions" ${showActions ? "checked" : ""} />
          Aktions-Buttons (Aufwachen / Nickerchen / Schlafen) anzeigen
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

    const chkHeader = this.shadowRoot.querySelector("#chk-header");
    if (chkHeader) {
      chkHeader.addEventListener("change", (e) => {
        this._emitConfig({ ...this._config, show_header: e.target.checked });
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

if (!customElements.get("napper-card-editor")) {
  customElements.define("napper-card-editor", NapperCardEditor);
}
if (!customElements.get("napper-circle-card-editor")) {
  customElements.define(
    "napper-circle-card-editor",
    class extends NapperCardEditor {}
  );
}

if (!customElements.get("napper-card")) {
  customElements.define("napper-card", NapperCard);
}
if (!customElements.get("napper-circle-card")) {
  customElements.define("napper-circle-card", class extends NapperCard {});
}

// Recover any Lovelace cards that timed out (>2000ms on mobile app cold start)
// before this module finished loading.
function _rebuildTimedOutNapperCards(root = document) {
  if (!root || !root.querySelectorAll) return;
  try {
    const allElements = root.querySelectorAll("*");
    for (const el of allElements) {
      const tag = el.tagName ? el.tagName.toLowerCase() : "";
      if (tag === "hui-error-card") {
        el.dispatchEvent(
          new CustomEvent("ll-rebuild", { bubbles: true, composed: true })
        );
      } else if (tag === "hui-card") {
        const cfgType = String(el._config?.type || "").toLowerCase();
        if (
          cfgType === "custom:napper-card" ||
          cfgType === "custom:napper-circle-card"
        ) {
          const innerTag = el._element?.tagName
            ? el._element.tagName.toLowerCase()
            : "";
          if (!el._element || innerTag === "hui-error-card") {
            if (typeof el._loadElement === "function" && el._config) {
              el._loadElement(el._config);
            } else if (typeof el.load === "function") {
              el.load();
            } else {
              el.dispatchEvent(
                new CustomEvent("ll-rebuild", { bubbles: true, composed: true })
              );
            }
          }
        }
      }
      if (el.shadowRoot) {
        _rebuildTimedOutNapperCards(el.shadowRoot);
      }
    }
  } catch (_err) {
    // Ignore DOM traversal errors
  }
}

_rebuildTimedOutNapperCards();
for (const delay of [100, 500, 1500, 3000]) {
  setTimeout(() => _rebuildTimedOutNapperCards(), delay);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "napper-card")) {
  window.customCards.push({
    type: "napper-card",
    name: "Napper Schlafplan",
    preview: true,
    description:
      "Zeigt Aufwachzeit, Nickerchen, Schlafenszeit und Aktions-Buttons im Napper-Design.",
  });
}
