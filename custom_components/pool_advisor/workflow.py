"""Maintenance workflow engine for Pool Chemistry Advisor.

A workflow is a linear sequence of Steps. Advancement happens when the user
presses the Analyse button:

- `run_analysis()` captures a fresh manual snapshot
- The current step's `satisfied(ctx)` function is evaluated
  - True  → advance to next step
  - False → stay; the step's `render()` produces an updated instruction
            (e.g. remaining dose based on the new measurement)

Acknowledge-only steps (calibration, activate-system, etc.) have
`satisfied = lambda _: True` — they move on as soon as the user confirms
with the Analyse button.

`min_wait_hours` is a *soft* hint: the render shows a warning when the user
advances too fast, but never blocks progress.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from .calculator import cya_pre_dose_grams, shock_dose_grams_or_ml
from .const import (
    MODE_FRISCHWASSER,
    MODE_NORMAL,
    MODE_SAISONSTART,
    MODE_SHOCK_ALGEN_LEICHT,
    MODE_SHOCK_ALGEN_STARK,
    MODE_SHOCK_BREAKPOINT,
    MODE_SHOCK_ROUTINE,
    MODE_SHOCK_SCHWARZALGEN,
    SHOCK_FC_TARGETS,
)


@dataclass
class WorkflowContext:
    """Everything a step needs to render content and evaluate satisfaction."""

    volume_m3: float

    ph_minus_display: str
    ph_plus_display: str
    ta_plus_display: str
    routine_cl_display: str
    shock_display: str
    shock_type: str
    shock_strength_pct: float
    cya_display: str
    cya_strength_pct: float

    ph_auto: float | None
    ph_manual: float | None
    ta: float | None
    fc: float | None
    cc: float | None
    cya: float | None

    ph_target: float
    ta_target: float
    fc_target: float
    cya_target: float

    ph_min: float = 7.0
    ph_max: float = 7.4
    ta_min: float = 80.0
    ta_max: float = 120.0

    # Freshness tracking
    step_started_at: datetime | None = None
    measured_at: dict[str, datetime | None] = field(default_factory=dict)

    def is_fresh(self, key: str) -> bool:
        """True if the named measurement was taken AFTER the current step began."""
        if self.step_started_at is None:
            return False
        at = self.measured_at.get(key)
        return at is not None and at > self.step_started_at

    def any_fresh(self) -> bool:
        """True if any configured measurement was taken after the current step began."""
        return any(self.is_fresh(k) for k in self.measured_at)


def _always(_ctx: WorkflowContext) -> bool:
    return True


@dataclass(frozen=True)
class Step:
    id: str
    title: str
    render: Callable[[WorkflowContext], str]
    # Returns True when the step's goal is met and workflow may advance.
    # Default: always True (acknowledge-only steps).
    satisfied: Callable[[WorkflowContext], bool] = _always
    # Soft warning: if advancing earlier than this many hours since step started,
    # render prepends a hint. Never hard-blocks.
    min_wait_hours: int = 0


# ---------- render helpers ----------


def _measured(label: str, value: float | None, unit: str, fmt: str = "{:.2f}") -> str:
    if value is None:
        return f"- {label}: *—* (nicht gemessen)"
    return f"- {label}: **{fmt.format(value)} {unit}**"


def _shock_dose_block(ctx: WorkflowContext, target_fc: float, scenario_label: str) -> str:
    current_fc = ctx.fc if ctx.fc is not None else 0.0
    dose = shock_dose_grams_or_ml(
        current_fc=current_fc,
        target_fc=target_fc,
        volume_m3=ctx.volume_m3,
        shock_type=ctx.shock_type,
        shock_strength_pct=ctx.shock_strength_pct,
    )
    if dose is None:
        return (
            "⚠ Shock-Produkt unbekannt oder nicht konfiguriert. "
            "Bitte in Einstellungen → Chemikalien eintragen."
        )
    amount, unit = dose
    if amount <= 0:
        return (
            f"FC bereits bei **{current_fc:.2f} mg/l** — Ziel {target_fc:.0f} "
            "erreicht. Nichts mehr zu dosieren."
        )
    fc_info = (
        f"FC aktuell **{current_fc:.2f} mg/l** → Ziel **{target_fc:.0f} mg/l** "
        f"→ Anhebung um {target_fc - current_fc:.1f} mg/l"
    )
    return (
        f"**{scenario_label}** — Dosiere **{amount:.0f} {unit} {ctx.shock_display}**\n\n"
        f"_{fc_info}_\n\n"
        "Vorgehen:\n"
        "- In Eimer mit Poolwasser vollständig auflösen\n"
        "- Über größere Fläche im Becken verteilen (nicht auf einem Punkt!)\n"
        "- Filter dauerhaft an"
    )


# ---------- render functions ----------


def _normal_body(_ctx: WorkflowContext) -> str:
    return (
        "Normalbetrieb — kein Workflow aktiv.\n\n"
        "Nach einer PoolLab-Messung **Analyse durchführen** drücken, "
        "dann siehst du die aktuellen Empfehlungen in der Markdown-Karte."
    )


def _render_measurements(ctx: WorkflowContext) -> str:
    if not ctx.any_fresh():
        header = (
            "### Werte messen\n\n"
            "PoolLab-Messung durchführen, Werte in HA übertragen, dann **Analyse durchführen**.\n\n"
            "_Der Schritt bleibt aktiv bis mindestens eine frische Messung vorliegt._\n\n"
        )
    else:
        header = (
            "### Werte messen\n\n"
            "✅ Frische Messwerte erkannt. **Analyse** für weiter.\n\n"
        )
    header += "**Aktueller Stand:**\n\n"
    return (
        header
        + f"{_measured('pH', ctx.ph_manual, '', '{:.2f}')}\n"
        + f"{_measured('Alkalität', ctx.ta, 'mg/l', '{:.0f}')}\n"
        + f"{_measured('Freies Chlor (FC)', ctx.fc, 'mg/l', '{:.2f}')}\n"
        + f"{_measured('Gebundenes Chlor (CC)', ctx.cc, 'mg/l', '{:.2f}')}\n"
        + f"{_measured('Cyanursäure (CYA)', ctx.cya, 'mg/l', '{:.0f}')}\n"
    )


def _measure_step_satisfied(ctx: WorkflowContext) -> bool:
    """Erstmessung is satisfied only once at least one value has been freshly measured."""
    return ctx.any_fresh()


# --- shock steps ---


def _shock_render(target_fc: float, scenario_label: str, include_brush: bool = False):
    def render(ctx: WorkflowContext) -> str:
        body = "### Dosieren & nachmessen\n\n" + _shock_dose_block(ctx, target_fc, scenario_label)
        if include_brush:
            body += "\n\nZusätzlich: Wände und Boden gründlich bürsten (2–3×)."
        from .const import SHOCK_CYA_PER_PPM_CL, SHOCK_STABILIZED

        if ctx.shock_type in SHOCK_STABILIZED:
            increase = max(0.0, target_fc - (ctx.fc or 0.0))
            cya_add = increase * SHOCK_CYA_PER_PPM_CL.get(ctx.shock_type, 0.9)
            cya_after = (ctx.cya or 0.0) + cya_add
            if increase > 0:
                body += (
                    f"\n\n⚠ **Nebeneffekt Cyanursäure**: {ctx.shock_display} bringt "
                    f"ca. {cya_add:.0f} mg/l CYA mit ins Wasser. "
                    f"CYA nach Dosis ≈ **{cya_after:.0f} mg/l**."
                )
        body += (
            "\n\n---\n"
            "**Nach der Dosierung:** Filter 24h dauerhaft an, dann neu messen und "
            "**Analyse durchführen** drücken. Wenn FC erreicht und CC < 0.2: Schritt erledigt."
        )
        return body

    return render


def _shock_satisfied(target_fc: float):
    def check(ctx: WorkflowContext) -> bool:
        if ctx.fc is None:
            return False
        # Target met when FC reached at least 80% of target AND CC low (if measured)
        fc_ok = ctx.fc >= target_fc * 0.8
        cc_ok = ctx.cc is None or ctx.cc <= 0.2
        return fc_ok and cc_ok

    return check


def _shock_done(target_fc: float, scenario_label: str):
    def render(ctx: WorkflowContext) -> str:
        fc_text = f"{ctx.fc:.2f}" if ctx.fc is not None else "—"
        cc_text = f"{ctx.cc:.2f}" if ctx.cc is not None else "—"
        return (
            f"### ✅ {scenario_label} abgeschlossen\n\n"
            f"FC aktuell {fc_text} mg/l, CC {cc_text} mg/l.\n\n"
            "FC wird in den nächsten Tagen natürlich auf den Zielbereich abfallen, dann übernimmt "
            "die Dosieranlage wieder.\n\n"
            "**Wartungsmodus zurück auf Normalbetrieb setzen** (Analyse-Button einmal drücken)."
        )

    return render


# --- breakpoint ---


def _breakpoint_render(ctx: WorkflowContext) -> str:
    if ctx.cc is None:
        return "### Breakpoint\n\nKein CC-Wert vorhanden. Bitte messen."
    target_fc = max(10.0, ctx.cc * 10.0)
    body = f"### Breakpoint-Dosis\n\nCC **{ctx.cc:.2f} mg/l** → FC-Ziel **{target_fc:.1f} mg/l**.\n\n"
    body += _shock_dose_block(ctx, target_fc, "Breakpoint")
    body += (
        "\n\n---\n"
        "**Nach der Dosis:** Filter 24h an, dann neu messen. CC sollte < 0.2 mg/l sein."
    )
    return body


def _breakpoint_satisfied(ctx: WorkflowContext) -> bool:
    return ctx.cc is not None and ctx.cc <= 0.2


# --- frischwasser steps ---


def _fw_fill_render(_ctx: WorkflowContext) -> str:
    return (
        "### Pool befüllen und Filter starten\n\n"
        "- Pool bis Skimmer-Mitte füllen\n"
        "- Filterpumpe auf **Dauerlauf**\n"
        "- Mindestens **2–4 h umwälzen** lassen (CO₂-Ausgasung, Mischung)\n\n"
        "Dann **Analyse durchführen** (noch ohne Messung — nur Bestätigung)."
    )


def _fw_measure_render(ctx: WorkflowContext) -> str:
    return _render_measurements(ctx)


def _fw_ta_render(ctx: WorkflowContext) -> str:
    if ctx.ta is None:
        return "### TA anpassen\n\nNoch keine TA-Messung. Bitte messen."
    delta = ctx.ta_target - ctx.ta
    if ctx.ta_min <= ctx.ta <= ctx.ta_max:
        return (
            f"### TA anpassen\n\nAktuell **{ctx.ta:.0f} mg/l** — bereits im Zielbereich "
            f"({ctx.ta_min:.0f}–{ctx.ta_max:.0f}). Nichts zu tun. **Analyse** für weiter."
        )
    if delta > 0:
        from .calculator import G_BICARB_PURE_PER_M3_PER_10_TA

        pure_g = G_BICARB_PURE_PER_M3_PER_10_TA * ctx.volume_m3 * (delta / 10.0)
        return (
            "### TA anheben\n\n"
            f"Aktuell **{ctx.ta:.0f} mg/l**, Ziel **{ctx.ta_target:.0f}** → Anhebung um {delta:.0f} mg/l.\n\n"
            f"Dosiere **{pure_g:.0f} g {ctx.ta_plus_display}** (in Eimer auflösen, verteilen).\n\n"
            "⏳ **12–24 h warten**, dann neu messen und Analyse drücken."
        )
    return (
        "### TA senken\n\n"
        f"Aktuell **{ctx.ta:.0f} mg/l**, Ziel **{ctx.ta_target:.0f}**.\n\n"
        "TA senken ist ein mehrtägiger Prozess (pH gezielt senken + belüften + wiederholen). "
        "Keine einmalige Gramm-Empfehlung möglich — siehe Pool-Chemie-Literatur."
    )


def _fw_ta_satisfied(ctx: WorkflowContext) -> bool:
    return ctx.ta is not None and ctx.ta_min <= ctx.ta <= ctx.ta_max


def _fw_ph_render(ctx: WorkflowContext) -> str:
    ph = ctx.ph_manual if ctx.ph_manual is not None else ctx.ph_auto
    if ph is None:
        return "### pH grob einstellen\n\nKeine pH-Messung. Bitte messen."
    delta = ctx.ph_target - ph
    if ctx.ph_min <= ph <= ctx.ph_max:
        return (
            f"### pH grob einstellen\n\nAktuell **{ph:.2f}** — passt "
            f"({ctx.ph_min:.1f}–{ctx.ph_max:.1f}). **Analyse** für weiter."
        )
    from .calculator import (
        G_DRY_ACID_PURE_PER_M3_PER_01_PH,
        G_SODA_PURE_PER_M3_PER_01_PH,
        ML_HCL_33_PER_M3_PER_01_PH,
    )

    units = abs(delta) / 0.1
    if delta > 0:
        grams = G_SODA_PURE_PER_M3_PER_01_PH * ctx.volume_m3 * units
        return (
            "### pH anheben\n\n"
            f"Aktuell **{ph:.2f}**, Ziel **{ctx.ph_target:.2f}**.\n\n"
            f"Dosiere **{grams:.0f} g {ctx.ph_plus_display}**.\n\n"
            "⏳ 4–6 h warten, dann neu messen + Analyse."
        )
    grams = G_DRY_ACID_PURE_PER_M3_PER_01_PH * ctx.volume_m3 * units
    ml = ML_HCL_33_PER_M3_PER_01_PH * ctx.volume_m3 * units
    return (
        "### pH senken\n\n"
        f"Aktuell **{ph:.2f}**, Ziel **{ctx.ph_target:.2f}**.\n\n"
        f"Dosiere **{grams:.0f} g {ctx.ph_minus_display}** (oder ca. {ml:.0f} ml Salzsäure).\n\n"
        "⏳ 4–6 h warten, dann neu messen + Analyse."
    )


def _fw_ph_satisfied(ctx: WorkflowContext) -> bool:
    ph = ctx.ph_manual if ctx.ph_manual is not None else ctx.ph_auto
    return ph is not None and ctx.ph_min <= ph <= ctx.ph_max


def _fw_calib_ph(_ctx: WorkflowContext) -> str:
    return (
        "### pH-Elektrode kalibrieren\n\n"
        "**Bevor die Dosierung aktiviert wird:**\n\n"
        "1. Elektrode in Pufferlösung **pH 7** → an der Anlage kalibrieren\n"
        "2. Dann Pufferlösung **pH 4** → Zweipunkt-Kalibrierung abschließen\n"
        "3. Elektrode zurück ins Probenwasser\n\n"
        "Wenn keine stabile Messung möglich → Elektrode tauschen.\n\n"
        "**Analyse** wenn fertig."
    )


def _fw_activate_ph(ctx: WorkflowContext) -> str:
    return (
        "### pH-Dosierung aktivieren\n\n"
        f"An der Bayrol-Anlage:\n\n"
        f"- pH-Sollwert auf **{ctx.ph_target:.1f}** setzen\n"
        "- pH-Dosierung einschalten\n\n"
        "Anlage übernimmt ab jetzt die Feinregelung.\n\n**Analyse** für weiter."
    )


def _fw_cya_render(ctx: WorkflowContext) -> str:
    current_cya = ctx.cya if ctx.cya is not None else 0.0
    if current_cya >= ctx.cya_target * 0.9:
        return (
            f"### CYA\n\nAktuell **{current_cya:.0f} mg/l**, Ziel {ctx.cya_target:.0f} — ok. "
            "**Analyse** weiter."
        )
    shock_target_fc = SHOCK_FC_TARGETS[MODE_SHOCK_ROUTINE]
    shock_increase = max(0.0, shock_target_fc - (ctx.fc or 0.0))
    pre_dose_g = cya_pre_dose_grams(
        current_cya=current_cya,
        target_cya=ctx.cya_target,
        shock_fc_increase=shock_increase,
        shock_type=ctx.shock_type,
        volume_m3=ctx.volume_m3,
        cya_strength_pct=ctx.cya_strength_pct,
    )
    if pre_dose_g <= 0:
        return (
            f"### CYA\n\nAktuell **{current_cya:.0f} mg/l**, Ziel {ctx.cya_target:.0f}. "
            "Der nachfolgende Shock bringt genug CYA mit. **Analyse** weiter."
        )
    return (
        "### Cyanursäure vor-dosieren\n\n"
        f"Aktuell **{current_cya:.0f} mg/l**, Ziel **{ctx.cya_target:.0f}**.\n\n"
        f"Dosiere **ca. {pre_dose_g * 0.8:.0f} g {ctx.cya_display}** (80 % Sicherheitspuffer).\n\n"
        "**Wichtig:** in Skimmer-Sockel (Socke) oder Einsatzkorb geben — langsam löslich.\n\n"
        "⏳ Filter 24–48 h durchlaufen, dann messen + Analyse.\n\n"
        f"_Hinweis: der nachfolgende Shock bringt ~{shock_increase * 0.9:.0f} mg/l CYA mit._"
    )


def _fw_cya_satisfied(ctx: WorkflowContext) -> bool:
    return ctx.cya is not None and ctx.cya >= ctx.cya_target * 0.6


def _fw_calib_redox(_ctx: WorkflowContext) -> str:
    return (
        "### Redox-Elektrode kalibrieren\n\n"
        "1. Elektrode in **Redox-Prüflösung 468 mV**\n"
        "2. An der Anlage kalibrieren\n"
        "3. Zurück ins Probenwasser\n\n"
        "Redox-Elektroden driften schneller als pH. Nach Winter oft komplett daneben.\n\n"
        "**Analyse** wenn fertig."
    )


def _fw_activate_cl(_ctx: WorkflowContext) -> str:
    return (
        "### Chlor-Dosierung aktivieren\n\n"
        "An der Bayrol-Anlage:\n\n"
        "- Chlor-Kanister prüfen (voll? Haltbarkeit?)\n"
        "- **Redox-Sollwert 700 mV**\n"
        "- Dosierung einschalten — pausiert noch, bis FC abbaut\n\n"
        "**Analyse** weiter."
    )


def _fw_shock_render(ctx: WorkflowContext) -> str:
    return _shock_render(
        SHOCK_FC_TARGETS[MODE_SHOCK_ROUTINE], "Routine-Shock (Inbetriebnahme)"
    )(ctx)


_fw_shock_satisfied = _shock_satisfied(SHOCK_FC_TARGETS[MODE_SHOCK_ROUTINE])


def _fw_done(_ctx: WorkflowContext) -> str:
    return (
        "### ✅ Inbetriebnahme abgeschlossen\n\n"
        "Pool ist eingefahren. Ab jetzt Normalbetrieb:\n\n"
        "- Tägliche PoolLab-Messung\n"
        "- Analyse durchführen\n"
        "- Empfehlungen folgen\n\n"
        "**Wartungsmodus jetzt auf Normalbetrieb setzen.**"
    )


# ---------- workflow definitions ----------


def _shock_workflow(target_fc: float, scenario_label: str, include_brush: bool = False) -> list[Step]:
    return [
        Step("measure", "Messen", _render_measurements),
        Step(
            "dose",
            "Dosieren & Nachmessen",
            _shock_render(target_fc, scenario_label, include_brush),
            satisfied=_shock_satisfied(target_fc),
            min_wait_hours=24,
        ),
        Step("done", "Fertig", _shock_done(target_fc, scenario_label)),
    ]


WORKFLOWS: dict[str, list[Step]] = {
    MODE_NORMAL: [Step("normal", "Normalbetrieb", _normal_body)],
    MODE_SHOCK_ROUTINE: _shock_workflow(SHOCK_FC_TARGETS[MODE_SHOCK_ROUTINE], "Shock Routine"),
    MODE_SHOCK_ALGEN_LEICHT: _shock_workflow(
        SHOCK_FC_TARGETS[MODE_SHOCK_ALGEN_LEICHT], "Shock Algen leicht", include_brush=True
    ),
    MODE_SHOCK_ALGEN_STARK: _shock_workflow(
        SHOCK_FC_TARGETS[MODE_SHOCK_ALGEN_STARK], "Shock Algen stark", include_brush=True
    ),
    MODE_SHOCK_SCHWARZALGEN: _shock_workflow(
        SHOCK_FC_TARGETS[MODE_SHOCK_SCHWARZALGEN], "Shock Schwarzalgen", include_brush=True
    ),
    MODE_SHOCK_BREAKPOINT: [
        Step("measure", "Messen", _render_measurements),
        Step(
            "dose",
            "Breakpoint-Dosis",
            _breakpoint_render,
            satisfied=_breakpoint_satisfied,
            min_wait_hours=24,
        ),
        Step("done", "Fertig", _shock_done(0, "Breakpoint")),
    ],
    MODE_FRISCHWASSER: [
        Step("fill", "Befüllen & Filter", _fw_fill_render),
        Step("measure1", "Erstmessung", _fw_measure_render, satisfied=_measure_step_satisfied),
        Step("ta", "TA anpassen", _fw_ta_render, satisfied=_fw_ta_satisfied, min_wait_hours=12),
        Step("ph", "pH grob", _fw_ph_render, satisfied=_fw_ph_satisfied, min_wait_hours=4),
        Step("calib_ph", "pH-Sonde kalibrieren", _fw_calib_ph),
        Step("activate_ph", "pH-Dosierung an", _fw_activate_ph),
        Step("cya", "CYA vor-dosieren", _fw_cya_render, satisfied=_fw_cya_satisfied, min_wait_hours=24),
        Step("calib_redox", "Redox-Sonde kalibrieren", _fw_calib_redox),
        Step("activate_cl", "Chlor-Dosierung an", _fw_activate_cl),
        Step("shock", "Routine-Shock", _fw_shock_render, satisfied=_fw_shock_satisfied, min_wait_hours=24),
        Step("done", "Fertig", _fw_done),
    ],
    MODE_SAISONSTART: [
        Step("measure", "Erstmessung", _fw_measure_render, satisfied=_measure_step_satisfied),
        Step(
            "shock",
            "Shock gegen Bio-Last",
            _shock_render(SHOCK_FC_TARGETS[MODE_SHOCK_ALGEN_LEICHT], "Shock Saisonstart", include_brush=True),
            satisfied=_shock_satisfied(SHOCK_FC_TARGETS[MODE_SHOCK_ALGEN_LEICHT]),
            min_wait_hours=24,
        ),
        Step("ph_remeasure", "pH nach Ausgasung prüfen", _fw_measure_render, satisfied=_measure_step_satisfied, min_wait_hours=24),
        Step("calib_ph", "pH-Sonde kalibrieren", _fw_calib_ph),
        Step("ph", "pH grob", _fw_ph_render, satisfied=_fw_ph_satisfied, min_wait_hours=4),
        Step("activate_ph", "pH-Dosierung an", _fw_activate_ph),
        Step("calib_redox", "Redox-Sonde kalibrieren", _fw_calib_redox),
        Step("activate_cl", "Chlor-Dosierung an", _fw_activate_cl),
        Step("done", "Fertig", _fw_done),
    ],
}


def get_workflow(mode: str) -> list[Step]:
    return WORKFLOWS.get(mode, WORKFLOWS[MODE_NORMAL])


def step_count(mode: str) -> int:
    return len(get_workflow(mode))
