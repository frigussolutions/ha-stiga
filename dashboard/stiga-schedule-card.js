/* stiga-schedule-card — weekly mowing schedule as a checkbox grid.
 *
 * One row per weekday, one column per schedule block (e.g. morning 9–13,
 * afternoon 13–17). The blocks come from the `blocks` attribute of the STIGA
 * integration's schedule sensor (configured in the integration's options);
 * each checkbox mirrors and toggles switch.<robot>_<day>_<block>, where
 * <robot> is the schedule sensor's object id without "_schedule". The
 * integration writes the robot's schedule and re-reads it. Mowing times
 * outside the blocks are left alone. A note shows when the schedule is off.
 *
 *   type: custom:stiga-schedule-card
 *   entity: sensor.stiga_a6v_schedule   # optional, this is the default
 */
class StigaScheduleCard extends HTMLElement {
  static DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];

  setConfig(config) {
    this._cfg = { entity: config.schedule_entity || "sensor.stiga_a6v_schedule", ...config };
    this._prefix = this._cfg.entity.replace(/^sensor\./, "switch.").replace(/_schedule$/, "");
  }

  _switch(day, block) {
    return `${this._prefix}_${day}_${block}`;
  }

  _blocks() {
    return this._hass.states[this._cfg.entity]?.attributes?.blocks || [];
  }

  static _hours(block) {
    const h = (t) => { const [hh, mm] = t.split(":"); return `${Number(hh)}${mm === "00" ? "" : ":" + mm}`; };
    return `${h(block.start)}–${h(block.end)}`;
  }

  set hass(hass) {
    this._hass = hass;
    const sensor = hass.states[this._cfg.entity];
    const ids = [];
    for (const d of StigaScheduleCard.DAYS)
      for (const b of this._blocks()) ids.push(this._switch(d, b.key));
    const stamp = (sensor ? sensor.last_updated + JSON.stringify(sensor.attributes.blocks) : "-")
      + ids.map((id) => (hass.states[id] ? hass.states[id].state + hass.states[id].last_updated : "-")).join("|");
    if (stamp === this._stamp) return; // nothing new — skip re-render
    this._stamp = stamp;
    this._render();
  }

  _render() {
    if (!this._root) {
      this._root = this.attachShadow({ mode: "open" });
      this._root.innerHTML = `
        <style>
          ha-card { padding: 8px 16px 12px; }
          table { width: 100%; border-collapse: collapse; }
          th { font-weight: 500; font-size: 13px; color: var(--secondary-text-color);
               padding: 6px 4px; text-align: center; }
          th:first-child, td:first-child { text-align: left; }
          th small { display: block; font-weight: 400; }
          td { padding: 4px; font-size: 14px; text-align: center; }
          tr + tr td { border-top: 1px solid var(--divider-color); }
          input { width: 20px; height: 20px; cursor: pointer;
                  accent-color: var(--primary-color); }
          input:disabled { cursor: progress; opacity: 0.5; }
          .note { padding: 6px 0 4px; font-size: 13px; color: var(--warning-color, #ff9800); }
          .empty { padding: 10px 0; color: var(--secondary-text-color); font-size: 14px; }
        </style>
        <ha-card><div id="body"></div></ha-card>`;
      this._body = this._root.getElementById("body");
    }
    const states = this._hass.states;
    const sensor = states[this._cfg.entity];
    const blocks = this._blocks();
    if (!sensor) {
      this._body.innerHTML = `<div class="empty">${this._cfg.entity} not found.</div>`;
      return;
    }
    if (!blocks.length) {
      this._body.innerHTML = `<div class="empty">No schedule blocks configured.</div>`;
      return;
    }
    const head = blocks
      .map((b) => `<th>${b.name}<small>${StigaScheduleCard._hours(b)}</small></th>`).join("");
    const rows = StigaScheduleCard.DAYS.map((d) => {
      const cells = blocks.map((b) => {
        const st = states[this._switch(d, b.key)];
        const dis = !st || st.state === "unavailable" ? "disabled" : "";
        const chk = st && st.state === "on" ? "checked" : "";
        return `<td><input type="checkbox" data-entity="${this._switch(d, b.key)}" ${chk} ${dis}></td>`;
      }).join("");
      return `<tr><td>${d[0].toUpperCase() + d.slice(1)}</td>${cells}</tr>`;
    }).join("");
    this._body.innerHTML = `
      ${sensor.attributes.enabled === false ? `<div class="note">Schedule is off — the robot only mows when started.</div>` : ""}
      <table><tr><th>Day</th>${head}</tr>${rows}</table>`;
    for (const input of this._body.querySelectorAll("input"))
      input.addEventListener("change", (ev) => this._toggle(ev.target));
  }

  async _toggle(input) {
    input.disabled = true;
    try {
      await this._hass.callService("switch", input.checked ? "turn_on" : "turn_off",
        { entity_id: input.dataset.entity });
    } catch (err) {
      console.warn("stiga-schedule-card:", err);
    }
    // Redraw from the entity states, whatever the outcome.
    this._stamp = null;
    this._render();
  }

  getCardSize() { return 5; }
}
customElements.define("stiga-schedule-card", StigaScheduleCard);
