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
 * The integration serves this file and registers it as a dashboard resource.
 * All values from entity states go into the DOM as text or properties, never
 * as markup.
 *
 *   type: custom:stiga-schedule-card
 *   entity: sensor.stiga_a6v_schedule   # optional, this is the default
 */
const STYLE = `
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
`;

// Element with optional text content; text is never parsed as HTML.
function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

class StigaScheduleCard extends HTMLElement {
  static DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];

  setConfig(config) {
    this._cfg = { entity: config.schedule_entity || "sensor.stiga_a6v_schedule", ...config };
    this._prefix = String(this._cfg.entity).replace(/^sensor\./, "switch.").replace(/_schedule$/, "");
  }

  _switch(day, block) {
    return `${this._prefix}_${day}_${block}`;
  }

  _blocks() {
    const blocks = this._hass.states[this._cfg.entity]?.attributes?.blocks;
    return Array.isArray(blocks) ? blocks : [];
  }

  static _hours(block) {
    const h = (t) => {
      const [hh, mm] = String(t).split(":");
      return `${Number(hh)}${mm === "00" ? "" : ":" + mm}`;
    };
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
      const card = el("ha-card");
      this._body = el("div");
      card.append(this._body);
      this._root.append(el("style", STYLE), card);
    }
    const states = this._hass.states;
    const sensor = states[this._cfg.entity];
    const blocks = this._blocks();
    if (!sensor) {
      this._body.replaceChildren(el("div", `${this._cfg.entity} not found.`, "empty"));
      return;
    }
    if (!blocks.length) {
      this._body.replaceChildren(el("div", "No schedule blocks configured.", "empty"));
      return;
    }

    const table = el("table");
    const head = el("tr");
    head.append(el("th", "Day"));
    for (const b of blocks) {
      const th = el("th", String(b.name));
      th.append(el("small", StigaScheduleCard._hours(b)));
      head.append(th);
    }
    table.append(head);

    for (const d of StigaScheduleCard.DAYS) {
      const row = el("tr");
      row.append(el("td", d[0].toUpperCase() + d.slice(1)));
      for (const b of blocks) {
        const entityId = this._switch(d, b.key);
        const st = states[entityId];
        const input = el("input");
        input.type = "checkbox";
        input.checked = Boolean(st && st.state === "on");
        input.disabled = !st || st.state === "unavailable";
        input.addEventListener("change", () => this._toggle(input, entityId));
        const td = el("td");
        td.append(input);
        row.append(td);
      }
      table.append(row);
    }

    const children = [];
    if (sensor.attributes.enabled === false)
      children.push(el("div", "Schedule is off — the robot only mows when started.", "note"));
    children.push(table);
    this._body.replaceChildren(...children);
  }

  async _toggle(input, entityId) {
    input.disabled = true;
    try {
      await this._hass.callService("switch", input.checked ? "turn_on" : "turn_off",
        { entity_id: entityId });
    } catch (err) {
      console.warn("stiga-schedule-card:", err);
    }
    // Redraw from the entity states, whatever the outcome.
    this._stamp = null;
    this._render();
  }

  getCardSize() { return 5; }
}

// Guarded: an older manually installed copy may already have defined the card.
if (!customElements.get("stiga-schedule-card"))
  customElements.define("stiga-schedule-card", StigaScheduleCard);
