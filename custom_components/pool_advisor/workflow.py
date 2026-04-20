"""Maintenance workflow engine for Pool Chemistry Advisor.

A workflow is a linear sequence of Steps. Each step knows how to render its
body (markdown) given a WorkflowContext (current config + latest readings)
and how the user advances it:

- `advance = "button"`: user presses the "Schritt abgeschlossen" button
- `advance = "analysis"`: user presses the "Analyse durchführen" button
  (which triggers a fresh manual-measurement snapshot)
"""
from __future__ import annotations

from dataclasses import dataclass
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
    """Everything a step needs to render its content."""

    volume_m3: float

    # products (display names + info needed to compute)
    ph_minus_display: str
    ph_plus_display: str
    ta_plus_display: str
    routine_cl_display: str
    shock_display: str
    shock_type: str
    shock_strength_pct: float
    cya_display: str
    cya_strength_pct: float

    # current readings (may be None if not configured / not measured)
    ph_auto: float | None
    ph_manual: float | None
    ta: float | None
    fc: float | None
    cc: float | None
    cya: float | None

    # targets
    ph_target: float
    ta_target: float
    fc_target: float
    cya_target: float


@dataclass(frozen=True)
class Step:
    id: str
    title: str
    advance: str  # "button" or "analysis"
    render: Callable[[WorkflowContext], str]


# ---------- helpers ----------


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
        "dann siehst du die aktuellen Empfehlungen unter *sensor.…empfehlung*."
    )


def _render_measure(ctx: WorkflowContext) -> str:
    return (
        "### Messen\n\n"
        "Alle relevanten Werte mit PoolLab messen und nach HA übertragen:\n\n"
        f"{_measured('pH', ctx.ph_manual, '', '{:.2f}')}\n"
        f"{_measured('Alkalität', ctx.ta, 'mg/l', '{:.0f}')}\n"
        f"{_measured('Freies Chlor (FC)', ctx.fc, 'mg/l', '{:.2f}')}\n"
        f"{_measured('Gebundenes Chlor (CC)', ctx.cc, 'mg/l', '{:.2f}')}\n"
        f"{_measured('Cyanursäure (CYA)', ctx.cya, 'mg/l', '{:.0f}')}\n\n"
        "Dann **Analyse durchführen** drücken — damit weiß der Advisor, was aktuell ist."
    )


def _render_shock(target_fc: float, label: str, include_brush: bool = False):
    def render(ctx: WorkflowContext) -> str:
        body = "### Dosieren\n\n" + _shock_dose_block(ctx, target_fc, label)
        if include_brush:
            body += "\n\nZusätzlich: Wände und Boden gründlich bürsten (2–3×)."
        # CYA preview
        from .const import SHOCK_CYA_PER_PPM_CL, SHOCK_STABILIZED

        if ctx.shock_type in SHOCK_STABILIZED:
            increase = max(0.0, target_fc - (ctx.fc or 0.0))
            cya_add = increase * SHOCK_CYA_PER_PPM_CL.get(ctx.shock_type, 0.9)
            cya_after = (ctx.cya or 0.0) + cya_add
            body += (
                f"\n\n⚠ **Nebeneffekt Cyanursäure**: {ctx.shock_display} bringt "
                f"ca. {cya_add:.0f} mg/l CYA mit ins Wasser. "
                f"CYA nach Dosis ≈ **{cya_after:.0f} mg/l**."
            )
        return body

    return render


def _render_wait(hours: int, note: str | None = None):
    def render(_ctx: WorkflowContext) -> str:
        body = (
            f"### Warten\n\n"
            f"⏳ **{hours} h einwirken lassen.**\n\n"
            "- Filterpumpe durchgehend an\n"
            "- Nicht neu dosieren in dieser Zeit\n"
        )
        if note:
            body += f"\n{note}\n"
        body += "\nNach Ablauf **Schritt abgeschlossen** drücken."
        return body

    return render


def _render_remeasure_and_evaluate(target_fc: float, label: str):
    def render(ctx: WorkflowContext) -> str:
        body = (
            "### Nachmessen und Bewerten\n\n"
            "PoolLab-Messung, dann **Analyse durchführen**.\n\n"
            "**Aktuelle Werte:**\n\n"
            f"{_measured('FC', ctx.fc, 'mg/l', '{:.2f}')}\n"
            f"{_measured('CC', ctx.cc, 'mg/l', '{:.2f}')}\n"
            f"{_measured('CYA', ctx.cya, 'mg/l', '{:.0f}')}\n"
        )
        # Verdict
        body += "\n**Einschätzung:**\n"
        if ctx.fc is None or ctx.cc is None:
            body += "- Werte fehlen, bitte messen und Analyse neu starten.\n"
        else:
            if ctx.cc <= 0.2 and ctx.fc >= target_fc * 0.5:
                body += "- ✅ Erfolg — Shock hat gewirkt.\n"
                body += "- FC wird in den nächsten Tagen natürlich abbauen.\n"
                body += "- Sobald FC im Zielbereich: zurück auf Normalbetrieb.\n"
            elif ctx.cc > 0.2:
                body += (
                    "- ⚠ CC noch erhöht → Breakpoint nicht erreicht.\n"
                    f"- Wartungsmodus erneut auf *{label}* setzen für zweite Dosis.\n"
                )
            elif ctx.fc < target_fc * 0.3:
                body += (
                    "- ⚠ FC ist stark eingebrochen → hohe Bio-Last.\n"
                    f"- Wartungsmodus erneut auf *{label}* setzen für zweite Dosis.\n"
                )
            if ctx.cya is not None and ctx.cya > 75:
                body += f"- ⚠ CYA {ctx.cya:.0f} mg/l zu hoch — Wasser teiltauschen.\n"
        body += "\n**Schritt abgeschlossen** beendet den Workflow."
        return body

    return render


# --- Frischwasser specific ---


def _render_fw_fill(_ctx: WorkflowContext) -> str:
    return (
        "### Pool befüllen und Filter starten\n\n"
        "- Pool bis Skimmer-Mitte füllen\n"
        "- Filterpumpe auf **Dauerlauf**\n"
        "- Mindestens **2–4 h umwälzen** lassen (CO₂-Ausgasung, Mischung)\n\n"
        "Dann weiter zur Erstmessung."
    )


def _render_fw_ta(ctx: WorkflowContext) -> str:
    if ctx.ta is None:
        return "### TA anpassen\n\nNoch keine TA-Messung. Bitte messen und Analyse neu starten."
    delta = ctx.ta_target - ctx.ta
    if -20 < delta < 20:
        return (
            "### TA anpassen\n\n"
            f"Aktuell **{ctx.ta:.0f} mg/l**, Ziel {ctx.ta_target:.0f} — "
            "bereits passabel, kein Eingreifen nötig.\n\n**Schritt abgeschlossen** drücken."
        )
    if delta > 0:
        from .calculator import G_BICARB_PURE_PER_M3_PER_10_TA

        pure_g = G_BICARB_PURE_PER_M3_PER_10_TA * ctx.volume_m3 * (delta / 10.0)
        return (
            "### TA anheben\n\n"
            f"Aktuell **{ctx.ta:.0f} mg/l**, Ziel **{ctx.ta_target:.0f}** → "
            f"Anhebung um {delta:.0f} mg/l.\n\n"
            f"Dosiere **{pure_g:.0f} g {ctx.ta_plus_display}** (Annahme 99 % Natron).\n\n"
            "- In Eimer Wasser auflösen, verteilen\n"
            "- Filter dauerhaft an\n"
            "- **12–24 h warten**, dann neu messen"
        )
    return (
        "### TA senken\n\n"
        f"Aktuell **{ctx.ta:.0f} mg/l**, Ziel **{ctx.ta_target:.0f}** → "
        f"zu senken um {-delta:.0f} mg/l.\n\n"
        "TA senken ist ein Prozess über Tage:\n"
        "1. pH gezielt auf 7.0 bringen (mit pH−)\n"
        "2. Kräftig belüften (Wasserfall / Düsen nach oben)\n"
        "3. Warten, messen, wiederholen\n\n"
        "Keine einmalige Dosierung möglich. Erfordert Geduld."
    )


def _render_fw_ph(ctx: WorkflowContext) -> str:
    ph = ctx.ph_manual if ctx.ph_manual is not None else ctx.ph_auto
    if ph is None:
        return "### pH grob einstellen\n\nKeine pH-Messung. Bitte messen und Analyse neu starten."
    delta = ctx.ph_target - ph
    if abs(delta) < 0.1:
        return (
            "### pH grob einstellen\n\n"
            f"Aktuell **{ph:.2f}**, Ziel {ctx.ph_target:.2f} — passt bereits.\n\n"
            "Weiter mit Sondenkalibrierung."
        )
    from .calculator import (
        G_DRY_ACID_PURE_PER_M3_PER_01_PH,
        G_SODA_PURE_PER_M3_PER_01_PH,
        ML_HCL_33_PER_M3_PER_01_PH,
    )

    units = abs(delta) / 0.1
    if delta > 0:
        grams = G_SODA_PURE_PER_M3_PER_01_PH * ctx.volume_m3 * units
        body = (
            "### pH anheben\n\n"
            f"Aktuell **{ph:.2f}**, Ziel **{ctx.ph_target:.2f}**.\n\n"
            f"Dosiere **{grams:.0f} g {ctx.ph_plus_display}** (Annahme Soda 99 %).\n\n"
            "- In Eimer lösen, verteilen\n"
            "- Filter an\n"
            "- **4–6 h warten**, neu messen"
        )
    else:
        grams = G_DRY_ACID_PURE_PER_M3_PER_01_PH * ctx.volume_m3 * units
        body = (
            "### pH senken\n\n"
            f"Aktuell **{ph:.2f}**, Ziel **{ctx.ph_target:.2f}**.\n\n"
            f"Dosiere **{grams:.0f} g {ctx.ph_minus_display}** (Annahme Trockensäure).\n\n"
            "_Wenn du Salzsäure flüssig verwendest, ca. {ml:.0f} ml stattdessen._\n\n"
            "- Langsam verteilen, Filter dauerhaft an\n"
            "- **4–6 h warten**, neu messen"
        ).replace("{ml:.0f}", f"{ML_HCL_33_PER_M3_PER_01_PH * ctx.volume_m3 * units:.0f}")
    return body


def _render_fw_calibrate_ph(_ctx: WorkflowContext) -> str:
    return (
        "### pH-Elektrode kalibrieren\n\n"
        "**Bevor du die pH-Dosierung aktivierst:**\n\n"
        "1. Elektrode der Bayrol-Anlage in Pufferlösung **pH 7** → Anlage kalibrieren\n"
        "2. In Pufferlösung **pH 4** → Zweipunkt-Kalibrierung abschließen\n"
        "3. Elektrode zurück ins Probenwasser\n\n"
        "Hinweis: nach langer Lagerung kann die Kalibrierung mehrere Versuche brauchen. "
        "Wenn die Anlage keine stabile Messung liefert → Elektrode ist hinüber, tauschen."
    )


def _render_fw_activate_ph_dosing(ctx: WorkflowContext) -> str:
    return (
        "### pH-Dosierung aktivieren\n\n"
        f"An der Bayrol-Anlage:\n\n"
        f"- pH-Sollwert auf **{ctx.ph_target:.1f}** setzen\n"
        "- pH-Dosierung **einschalten**\n"
        "- Anlage macht ab jetzt die Feinregelung\n\n"
        "Weiter zur Chlor-Vorbereitung."
    )


def _render_fw_cya_predose(ctx: WorkflowContext) -> str:
    current_cya = ctx.cya if ctx.cya is not None else 0.0
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
            "### Cyanursäure vor-dosieren\n\n"
            f"Aktuell CYA **{current_cya:.0f} mg/l**, Ziel {ctx.cya_target:.0f}. "
            "Zusammen mit der anschließenden Shock-Dosis reicht das schon. **Nichts zu dosieren.**\n\n"
            "**Schritt abgeschlossen** drücken."
        )
    return (
        "### Cyanursäure vor-dosieren\n\n"
        f"Aktuell **{current_cya:.0f} mg/l**, Ziel **{ctx.cya_target:.0f}**.\n\n"
        f"Dosiere **ca. {pre_dose_g * 0.8:.0f} g {ctx.cya_display}** "
        f"(80 % der Rechnung als Sicherheitspuffer).\n\n"
        "**Wichtig:** in Skimmer-Sockel (Socke) oder Einsatzkorb geben — löst sich langsam!\n\n"
        "- Filter **24–48 h durchlaufen** lassen bis vollständig gelöst\n"
        "- Erst danach messen (eher am 2. Tag)\n"
        "- Wenn dann noch unter Ziel: nachlegen\n\n"
        "_Hinweis: der anschließende Shock bringt weitere "
        f"~{shock_increase * 0.9:.0f} mg/l CYA mit ein._"
    )


def _render_fw_calibrate_redox(_ctx: WorkflowContext) -> str:
    return (
        "### Redox-Elektrode kalibrieren\n\n"
        "1. Elektrode in **Redox-Prüflösung 468 mV**\n"
        "2. An der Anlage kalibrieren / Offset prüfen\n"
        "3. Zurück ins Probenwasser\n\n"
        "Hinweis: Redox-Elektroden driften schneller als pH-Elektroden. "
        "Nach Winter oft komplett daneben."
    )


def _render_fw_activate_cl_dosing(_ctx: WorkflowContext) -> str:
    return (
        "### Chlor-Dosierung aktivieren\n\n"
        "An der Bayrol-Anlage:\n\n"
        "- Kanister der Chlor-Dosierung prüfen (voll? Haltbarkeit?)\n"
        "- **Redox-Sollwert auf 700 mV**\n"
        "- Dosierung einschalten — pausiert noch, bis FC abbaut\n\n"
        "Weiter zum Schock."
    )


def _render_fw_done(_ctx: WorkflowContext) -> str:
    return (
        "### Inbetriebnahme abgeschlossen 🎉\n\n"
        "Der Pool ist eingefahren. Weiter geht's im Normalbetrieb:\n\n"
        "- Täglich einmal PoolLab-Messung\n"
        "- Analyse durchführen\n"
        "- Empfehlungen folgen\n\n"
        "**Wartungsmodus jetzt auf *Normalbetrieb* zurücksetzen.**"
    )


# ---------- workflow definitions ----------


def _shock_workflow(mode_key: str, target_fc: float, label: str, brush: bool = False) -> list[Step]:
    return [
        Step(f"{mode_key}_measure", "Messen", "analysis", _render_measure),
        Step(f"{mode_key}_dose", "Dosieren", "button", _render_shock(target_fc, label, brush)),
        Step(f"{mode_key}_wait", "Einwirken", "button", _render_wait(24)),
        Step(f"{mode_key}_remeasure", "Nachmessen", "analysis", _render_measure),
        Step(f"{mode_key}_eval", "Bewerten", "button", _render_remeasure_and_evaluate(target_fc, label)),
    ]


def _breakpoint_render_dose(ctx: WorkflowContext) -> str:
    if ctx.cc is None:
        return (
            "### Breakpoint-Dosis\n\n"
            "Kein CC-Wert vorhanden. Bitte messen und Analyse neu starten."
        )
    target_fc = max(10.0, ctx.cc * 10.0)
    return (
        "### Breakpoint-Dosis\n\n"
        f"CC **{ctx.cc:.2f} mg/l** → 10× Regel → FC-Ziel **{target_fc:.1f} mg/l**.\n\n"
        + _shock_dose_block(ctx, target_fc, "Breakpoint")
    )


def _breakpoint_eval(ctx: WorkflowContext) -> str:
    if ctx.cc is None:
        return "Kein CC-Wert. Messen und Analyse neu starten."
    body = (
        "### Nachmessen und Bewerten\n\n"
        f"{_measured('FC', ctx.fc, 'mg/l', '{:.2f}')}\n"
        f"{_measured('CC', ctx.cc, 'mg/l', '{:.2f}')}\n\n"
    )
    if ctx.cc <= 0.2:
        body += "- ✅ CC unter 0.2 mg/l — Breakpoint erreicht.\n"
    else:
        body += f"- ⚠ CC **{ctx.cc:.2f}** noch über Schwelle — Modus erneut starten für zweite Dosis.\n"
    return body


WORKFLOWS: dict[str, list[Step]] = {
    MODE_NORMAL: [Step("normal", "Normalbetrieb", "button", _normal_body)],
    MODE_SHOCK_ROUTINE: _shock_workflow(
        MODE_SHOCK_ROUTINE, SHOCK_FC_TARGETS[MODE_SHOCK_ROUTINE], "Shock Routine"
    ),
    MODE_SHOCK_ALGEN_LEICHT: _shock_workflow(
        MODE_SHOCK_ALGEN_LEICHT,
        SHOCK_FC_TARGETS[MODE_SHOCK_ALGEN_LEICHT],
        "Shock Algen leicht",
        brush=True,
    ),
    MODE_SHOCK_ALGEN_STARK: _shock_workflow(
        MODE_SHOCK_ALGEN_STARK,
        SHOCK_FC_TARGETS[MODE_SHOCK_ALGEN_STARK],
        "Shock Algen stark",
        brush=True,
    ),
    MODE_SHOCK_SCHWARZALGEN: _shock_workflow(
        MODE_SHOCK_SCHWARZALGEN,
        SHOCK_FC_TARGETS[MODE_SHOCK_SCHWARZALGEN],
        "Shock Schwarzalgen",
        brush=True,
    ),
    MODE_SHOCK_BREAKPOINT: [
        Step("bp_measure", "Messen", "analysis", _render_measure),
        Step("bp_dose", "Breakpoint-Dosis", "button", _breakpoint_render_dose),
        Step("bp_wait", "Einwirken", "button", _render_wait(24)),
        Step("bp_remeasure", "Nachmessen", "analysis", _render_measure),
        Step("bp_eval", "Bewerten", "button", _breakpoint_eval),
    ],
    MODE_FRISCHWASSER: [
        Step("fw_fill", "Befüllen", "button", _render_fw_fill),
        Step("fw_measure1", "Erstmessung", "analysis", _render_measure),
        Step("fw_ta", "TA anpassen", "button", _render_fw_ta),
        Step("fw_wait_ta", "TA einschwingen", "button", _render_wait(24, "TA braucht 12–24 h bis zum Gleichgewicht.")),
        Step("fw_measure2", "TA-Nachmessung", "analysis", _render_measure),
        Step("fw_ph", "pH grob einstellen", "button", _render_fw_ph),
        Step("fw_wait_ph", "pH einschwingen", "button", _render_wait(6)),
        Step("fw_measure3", "pH-Nachmessung", "analysis", _render_measure),
        Step("fw_calibrate_ph", "pH-Sonde kalibrieren", "button", _render_fw_calibrate_ph),
        Step("fw_activate_ph", "pH-Dosierung an", "button", _render_fw_activate_ph_dosing),
        Step("fw_cya", "CYA vor-dosieren", "button", _render_fw_cya_predose),
        Step("fw_wait_cya", "CYA lösen", "button", _render_wait(48, "Stabilisator braucht 24–48 h im Skimmer-Sockel bis er voll gelöst ist.")),
        Step("fw_calibrate_redox", "Redox-Sonde kalibrieren", "button", _render_fw_calibrate_redox),
        Step("fw_activate_cl", "Chlor-Dosierung an", "button", _render_fw_activate_cl_dosing),
        Step("fw_shock_measure", "Pre-Shock-Messung", "analysis", _render_measure),
        Step("fw_shock", "Routine-Shock", "button", _render_shock(SHOCK_FC_TARGETS[MODE_SHOCK_ROUTINE], "Shock Routine")),
        Step("fw_done", "Fertig", "button", _render_fw_done),
    ],
    MODE_SAISONSTART: [
        Step("ss_inspect", "Sichtprüfung & Erstmessung", "analysis", _render_measure),
        Step("ss_shock_algen", "Bei Biobelastung: Shock", "button", _render_shock(SHOCK_FC_TARGETS[MODE_SHOCK_ALGEN_LEICHT], "Shock Saisonstart", include_brush=True)),
        Step("ss_wait", "24 h einwirken", "button", _render_wait(24)),
        Step("ss_measure_ph", "pH messen nach Ausgasung", "analysis", _render_measure),
        Step("ss_calibrate_ph", "pH-Sonde kalibrieren", "button", _render_fw_calibrate_ph),
        Step("ss_ph_adjust", "pH grob einstellen", "button", _render_fw_ph),
        Step("ss_activate_ph", "pH-Dosierung an", "button", _render_fw_activate_ph_dosing),
        Step("ss_calibrate_redox", "Redox-Sonde kalibrieren", "button", _render_fw_calibrate_redox),
        Step("ss_activate_cl", "Chlor-Dosierung an", "button", _render_fw_activate_cl_dosing),
        Step("ss_done", "Fertig", "button", _render_fw_done),
    ],
}


def get_workflow(mode: str) -> list[Step]:
    return WORKFLOWS.get(mode, WORKFLOWS[MODE_NORMAL])


def step_count(mode: str) -> int:
    return len(get_workflow(mode))
