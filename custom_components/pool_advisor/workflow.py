"""Kontext-abhängige Empfehlungs-Renderer.

Vier Modi, jeweils eine `render(ctx)`-Funktion die eine vollständige
Markdown-Liste zurückgibt. Keine Step-Engine, kein State — alle Einträge
werden live aus dem aktuellen Snapshot berechnet und bekommen ein
Status-Symbol (✅ / ⚠ / ○).

Der User pickt aus der Liste was er tut, in der Reihenfolge die er für
richtig hält. Wenn ein Wert im Ziel liegt, steht dort nur die
Zusammenfassung — keine Dosis-Empfehlung.
"""
from __future__ import annotations

from dataclasses import dataclass

from .calculator import (
    Recommendation,
    shock_dose_grams_or_ml,
)
from .const import (
    SHOCK_CYA_PER_PPM_CL,
    SHOCK_STABILIZED,
    SHOCK_TARGET_ALGEN_LEICHT,
    SHOCK_TARGET_ALGEN_STARK,
    SHOCK_TARGET_ROUTINE,
    SHOCK_TARGET_SCHWARZALGEN,
)


# ---------- Kontext ----------


@dataclass
class WorkflowContext:
    volume_m3: float

    # Produkt-Displaynamen (User-Config)
    ph_minus_display: str
    ph_plus_display: str
    ta_plus_display: str
    routine_cl_display: str
    shock_display: str
    shock_type: str
    shock_strength_pct: float
    cya_display: str
    cya_strength_pct: float

    # Messwerte
    ph_auto: float | None
    ph_manual: float | None
    ta: float | None
    fc: float | None
    cc: float | None
    cya: float | None

    # Targets
    ph_target: float
    ta_target: float
    fc_target: float
    cya_target: float

    ph_min: float = 7.0
    ph_max: float = 7.4
    ta_min: float = 80.0
    ta_max: float = 120.0
    water_temp: float | None = None

    # Thresholds für Color-Coding und Swim-Check
    ph_critical_low: float = 6.8
    ph_critical_high: float = 7.7
    ta_critical_low: float = 60.0
    ta_critical_high: float = 150.0
    fc_critical_low: float = 0.2
    fc_min_val: float = 0.5
    fc_max: float = 1.5
    cc_max: float = 0.2
    cc_shock_at: float = 0.5
    cya_watch_at: float = 50.0
    cya_critical_at: float = 75.0
    ph_calib_threshold: float = 0.2
    redox_drift_threshold: float = 70.0

    # Redox-Ziele
    redox_min: float = 650.0
    redox_target: float = 700.0
    redox_max: float = 750.0

    total_cl: float | None = None
    redox: float | None = None


# ---------- Hilfsfunktionen ----------


def _eff_ph(ctx: WorkflowContext) -> float | None:
    return ctx.ph_manual if ctx.ph_manual is not None else ctx.ph_auto


def _shock_dose(ctx: WorkflowContext, target_fc: float) -> tuple[float, str] | None:
    current_fc = ctx.fc if ctx.fc is not None else 0.0
    return shock_dose_grams_or_ml(
        current_fc=current_fc,
        target_fc=target_fc,
        volume_m3=ctx.volume_m3,
        shock_type=ctx.shock_type,
        shock_strength_pct=ctx.shock_strength_pct,
    )


def _cya_from_shock(ctx: WorkflowContext, target_fc: float) -> float:
    """Erwarteter CYA-Eintrag durch diese Shock-Dosis (falls stabilisiertes Produkt)."""
    if ctx.shock_type not in SHOCK_STABILIZED:
        return 0.0
    increase = max(0.0, target_fc - (ctx.fc or 0.0))
    return increase * SHOCK_CYA_PER_PPM_CL.get(ctx.shock_type, 0.9)


def _val(v: float | None, unit: str, dec: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v:.{dec}f} {unit}".rstrip()


# ---------- Normalbetrieb: nutzt bestehende Recommendation-Objekte ----------


ACTION_ICONS = {
    "ok": "✅",
    "watch": "👁",
    "raise": "⚠",
    "lower": "⚠",
    "shock": "🚨",
    "calibrate": "🎯",
    "no_data": "❔",
}

# Farbpalette (moderat gesättigt, Light-/Dark-Theme-tauglich)
COLOR_GREEN = "#81c784"
COLOR_ORANGE = "#f0ad4e"
COLOR_RED = "#d9534f"
COLOR_GREY = "#999999"


# --- Color-Helper pro Parameter ---


def _color_ph_val(ph: float | None, ctx: WorkflowContext) -> str:
    if ph is None:
        return COLOR_GREY
    if ph < ctx.ph_critical_low or ph > ctx.ph_critical_high:
        return COLOR_RED
    if ph < ctx.ph_min or ph > ctx.ph_max:
        return COLOR_ORANGE
    return COLOR_GREEN


def _color_ta_val(ta: float | None, ctx: WorkflowContext) -> str:
    if ta is None:
        return COLOR_GREY
    if ta < ctx.ta_critical_low or ta > ctx.ta_critical_high:
        return COLOR_RED
    if ta < ctx.ta_min or ta > ctx.ta_max:
        return COLOR_ORANGE
    return COLOR_GREEN


def _color_fc_val(fc: float | None, ctx: WorkflowContext) -> str:
    if fc is None:
        return COLOR_GREY
    if fc < ctx.fc_critical_low or fc > 10.0:
        return COLOR_RED
    if fc < ctx.fc_min_val or fc > 3.0:
        return COLOR_RED if fc > 3.0 else COLOR_ORANGE
    if fc > ctx.fc_max:
        return COLOR_ORANGE
    return COLOR_GREEN


def _color_cc_val(cc: float | None, ctx: WorkflowContext) -> str:
    if cc is None:
        return COLOR_GREY
    if cc >= ctx.cc_shock_at:
        return COLOR_RED
    if cc > ctx.cc_max:
        return COLOR_ORANGE
    return COLOR_GREEN


def _color_tc_val(tc: float | None, ctx: WorkflowContext) -> str:
    if tc is None:
        return COLOR_GREY
    # TC = FC + CC; hohe TC = meistens hohe FC
    if tc > 10.0:
        return COLOR_RED
    if tc > 3.0:
        return COLOR_ORANGE
    return COLOR_GREEN


def _color_redox_val(redox: float | None, ctx: WorkflowContext) -> str:
    if redox is None:
        return COLOR_GREY
    if ctx.redox_min <= redox <= ctx.redox_max:
        return COLOR_GREEN
    # Größere Abweichung → rot, leichtes Abweichen → orange
    lo_crit = ctx.redox_min - (ctx.redox_max - ctx.redox_min) * 0.3
    hi_crit = ctx.redox_max + (ctx.redox_max - ctx.redox_min) * 0.3
    if redox < lo_crit or redox > hi_crit:
        return COLOR_RED
    return COLOR_ORANGE


def _color_cya_val(cya: float | None, ctx: WorkflowContext) -> str:
    if cya is None:
        return COLOR_GREY
    if cya >= ctx.cya_critical_at:
        return COLOR_RED
    if cya >= ctx.cya_watch_at:
        return COLOR_ORANGE
    if cya < ctx.cya_target * 0.6:
        return COLOR_RED
    if cya < ctx.cya_target * 0.9:
        return COLOR_ORANGE
    return COLOR_GREEN


def _color_from_action(action: str | None) -> str:
    if action == "ok":
        return COLOR_GREEN
    if action == "watch":
        return COLOR_ORANGE
    if action in ("raise", "lower", "shock", "calibrate"):
        return COLOR_RED
    return COLOR_GREY  # no_data / unknown


def _colored(value: str, color: str) -> str:
    return f'<font color="{color}">{value}</font>'


# --- Swim-Safety ---


def _swim_safety_check(ctx: WorkflowContext) -> bool:
    """True wenn Baden aktuell sicher. Nur der generische Bade-Status;
    Detail-Infos kommen aus gelben Warnungen + Messwerte-Tabelle.
    """
    ph = _eff_ph(ctx)
    if ctx.fc is not None and (ctx.fc > 3.0 or ctx.fc < 0.3):
        return False
    if ctx.cc is not None and ctx.cc > 0.5:
        return False
    if ph is not None and (ph < 6.8 or ph > 7.8):
        return False
    if ctx.cya is not None and ctx.cya > 100:
        return False
    return True


def _param_warnings(
    ctx: WorkflowContext,
    recs: dict[str, Recommendation],
) -> list[str]:
    """Gelbe Parameter-Warnungen aus allen aktiven Recommendations.

    Jeder Parameter mit action != ok/no_data erzeugt einen Warning-Alert
    mit der spezifischen Reason-Zeile. Doppelungen zum roten Bade-Alert
    gibt es nicht, weil der nur generisch "Nicht baden" sagt.
    """
    warnings: list[str] = []
    for key, label in (
        ("alkalinity", "Alkalität"),
        ("ph", "pH"),
        ("cya", "Cyanursäure"),
        ("chlorine", "Chlor"),
        ("calibration", "Drift pH Sonde"),
        ("drift_redox", "Drift Redox Sonde"),
    ):
        rec = recs.get(key)
        if rec is None or rec.action in ("ok", "no_data"):
            continue
        warnings.append(f"**{label}**: {rec.reason}")
    return warnings


def _format_steps_inline(steps) -> str:
    """Fasst Dose-Steps als kompakte Zeile zusammen.

    Bei ≥ 3 gleich großen Teildosen: "Dosiere N × X Einheit Produkt,
    alle Y h (gesamt Z)" statt langer Aufzählung.
    """
    if not steps:
        return ""
    amounts = {s.amount for s in steps}
    if len(steps) >= 3 and len(amounts) == 1:
        s = steps[0]
        n = len(steps)
        wait = steps[0].wait_hours or 0
        total = s.amount * n
        wait_str = f" alle {wait} h" if wait > 0 else ""
        return (
            f"Dosiere **{n}× {s.amount:g} {s.unit}** {s.product}"
            f"{wait_str} (gesamt ~{total:g} {s.unit}, ~{(n - 1) * wait} h Gesamtdauer)"
        )
    parts: list[str] = []
    for i, s in enumerate(steps, 1):
        parts.append(f"**{s.amount:g} {s.unit}** {s.product}")
        if s.wait_hours > 0 and i < len(steps):
            parts.append(f"{s.wait_hours} h warten")
    return "Dosiere " + " → ".join(parts)


def _action_recommendations(ctx: WorkflowContext, recs: dict[str, Recommendation]) -> list[str]:
    """Konkrete Handlungsanweisungen als Info-Alert (blau)."""
    alerts: list[str] = []

    for key, label in (
        ("alkalinity", "Alkalität"),
        ("ph", "pH"),
        ("cya", "Cyanursäure"),
    ):
        rec = recs.get(key)
        if rec is None or rec.action in ("ok", "no_data", "watch"):
            continue
        if rec.steps:
            alerts.append(f"**{label}**: {_format_steps_inline(rec.steps)}")
        elif rec.action == "lower" and key == "alkalinity":
            alerts.append(
                "**Alkalität senken**: mehrtägiger Prozess — pH gezielt auf ~7.0 senken, "
                "kräftig belüften (Düsen nach oben / Wasserfall), täglich wiederholen und neu messen"
            )
        elif rec.action == "lower" and key == "cya":
            # CYA nur durch Verdünnung senkbar: f = 1 − target/current
            if ctx.cya is not None and ctx.cya > ctx.cya_target:
                f = 1.0 - (ctx.cya_target / ctx.cya)
                percent = f * 100
                liters = ctx.volume_m3 * f * 1000
                msg = (
                    f"**Cyanursäure senken**: chemisch nicht möglich, nur durch Verdünnung. "
                    f"Ca. **{percent:.0f} % Wasser teiltauschen** "
                    f"(≈ {liters:.0f} L bei {ctx.volume_m3:.0f} m³ Pool) um auf Ziel "
                    f"{ctx.cya_target:.0f} mg/l zu kommen, dann neu messen."
                )
                if percent > 50:
                    msg += (
                        " Achtung großer Austausch — besser in 2–3 Etappen über mehrere Tage "
                        "splitten, nicht auf einmal."
                    )
                # Frischwasser bringt FC=0 mit — Sanitation muss neu aufgebaut werden
                if percent >= 30:
                    msg += (
                        " Nach dem Austausch **Routine-Shock empfohlen** (siehe Shock-Tabelle), "
                        "da Frischwasser FC=0 mitbringt und die Dosieranlage Zeit braucht."
                    )
                alerts.append(msg)
            else:
                alerts.append(
                    "**Cyanursäure senken**: chemisch nicht möglich, nur durch Wasser-Teiltausch. "
                    "Messung erneuern, dann Verdünnungs-Menge berechnen."
                )

    # Chlor-Aktionen: Breakpoint bei hohem CC, oder Routine-Dosis bei niedrigem FC.
    # Konkrete Dosen stehen in der Shock-Szenarien-Tabelle unten — hier nur
    # Kurzempfehlung.
    cl_rec = recs.get("chlorine")
    if cl_rec is not None and cl_rec.steps:
        if cl_rec.action == "shock":
            alerts.append("**Chlor (Breakpoint)**: Schockchlorung siehe Tabelle empfohlen.")
        elif cl_rec.action == "raise":
            alerts.append("**Chlor**: Routine-Shock siehe Tabelle empfohlen.")

    # Kalibrierungs-Handlungen
    cal = recs.get("calibration")
    if cal is not None and cal.action == "calibrate":
        alerts.append(
            "**pH-Elektrode kalibrieren**: mit Pufferlösungen pH 7 und pH 4 an der "
            "Dosieranlage nachjustieren"
        )
    dr = recs.get("drift_redox")
    if dr is not None and dr.action == "calibrate":
        alerts.append(
            "**Redox-Elektrode kalibrieren**: mit Prüflösung 468 mV an der Dosieranlage "
            "nachjustieren"
        )

    return alerts


# --- Tabelle ---


def _values_table(ctx: WorkflowContext, recs: dict[str, Recommendation]) -> list[str]:
    L: list[str] = [
        "| Messwert | Aktuell | Ziel | Min | Max |",
        "|----------|---------|------|-----|-----|",
    ]

    # Alkalität (Puffer — kommt zuerst in der Chemie-Reihenfolge)
    ta_str = (
        _colored(f"{ctx.ta:.0f}", _color_ta_val(ctx.ta, ctx))
        if ctx.ta is not None
        else "—"
    )
    L.append(
        f"| Alkalität (mg/l) | {ta_str} | {ctx.ta_target:.0f} | "
        f"{ctx.ta_min:.0f} | {ctx.ta_max:.0f} |"
    )

    # pH Manuell (PoolLab-Photometer)
    ph_m = ctx.ph_manual
    ph_m_str = _colored(f"{ph_m:.2f}", _color_ph_val(ph_m, ctx)) if ph_m is not None else "—"
    L.append(
        f"| pH Manuell | {ph_m_str} | {ctx.ph_target:.2f} | {ctx.ph_min:.1f} | {ctx.ph_max:.1f} |"
    )

    # pH Dosieranlage (Bayrol-Elektrode, live)
    ph_a = ctx.ph_auto
    ph_a_str = _colored(f"{ph_a:.2f}", _color_ph_val(ph_a, ctx)) if ph_a is not None else "—"
    L.append(
        f"| pH Dosieranlage | {ph_a_str} | {ctx.ph_target:.2f} | {ctx.ph_min:.1f} | {ctx.ph_max:.1f} |"
    )

    # Cyanursäure
    cya_str = (
        _colored(f"{ctx.cya:.0f}", _color_cya_val(ctx.cya, ctx))
        if ctx.cya is not None
        else "—"
    )
    L.append(
        f"| Cyanursäure (mg/l) | {cya_str} | {ctx.cya_target:.0f} | "
        f"{ctx.cya_watch_at:.0f} | {ctx.cya_critical_at:.0f} |"
    )

    # Chlor frei (FC)
    fc_str = (
        _colored(f"{ctx.fc:.2f}", _color_fc_val(ctx.fc, ctx))
        if ctx.fc is not None
        else "—"
    )
    L.append(
        f"| Chlor frei (mg/l) | {fc_str} | {ctx.fc_target:.2f} | "
        f"{ctx.fc_min_val:.2f} | {ctx.fc_max:.2f} |"
    )

    # Chlor gebunden (CC)
    cc_str = (
        _colored(f"{ctx.cc:.2f}", _color_cc_val(ctx.cc, ctx))
        if ctx.cc is not None
        else "—"
    )
    L.append(f"| Chlor geb. (mg/l) | {cc_str} | — | — | {ctx.cc_max:.2f} |")

    # Chlor gesamt (TC)
    tc_str = (
        _colored(f"{ctx.total_cl:.2f}", _color_tc_val(ctx.total_cl, ctx))
        if ctx.total_cl is not None
        else "—"
    )
    L.append(f"| Chlor gesamt (mg/l) | {tc_str} | — | — | — |")

    # Redox Dosieranlage (Bayrol-Elektrode, live)
    redox_str = (
        _colored(f"{ctx.redox:.0f}", _color_redox_val(ctx.redox, ctx))
        if ctx.redox is not None
        else "—"
    )
    L.append(
        f"| Redox Dosieranlage (mV) | {redox_str} | {ctx.redox_target:.0f} | "
        f"{ctx.redox_min:.0f} | {ctx.redox_max:.0f} |"
    )

    # Redox Berechnet (aus FC + pH + CYA)
    redox_exp_val: float | None = None
    ph_for_exp = _eff_ph(ctx)
    if ctx.fc is not None and ph_for_exp is not None:
        from .calculator import expected_redox_mv

        cya_for_exp = ctx.cya if ctx.cya is not None else 30.0
        redox_exp_val = expected_redox_mv(
            free_cl=ctx.fc, ph=ph_for_exp, cya=cya_for_exp
        )
    redox_exp_str = f"{redox_exp_val:.0f}" if redox_exp_val is not None else "—"
    L.append(f"| Redox Berechnet (mV) | {redox_exp_str} | — | — | — |")

    # Drift pH Sonde
    calib = recs.get("calibration")
    if calib is not None and calib.delta is not None:
        color = _color_from_action(calib.action)
        delta_str = _colored(f"{calib.delta:+.2f}", color)
    else:
        delta_str = "—"
    L.append(
        f"| Drift pH Sonde | {delta_str} | 0.00 | — | ±{ctx.ph_calib_threshold:.2f} |"
    )

    # Drift Redox Sonde
    dr = recs.get("drift_redox")
    if dr is not None and dr.delta is not None:
        color = _color_from_action(dr.action)
        delta_str = _colored(f"{dr.delta:+.0f} mV", color)
    else:
        delta_str = "—"
    L.append(
        f"| Drift Redox Sonde | {delta_str} | 0 mV | — | ±{ctx.redox_drift_threshold:.0f} mV |"
    )

    L.append("")
    return L


# --- Shock-Szenarien-Tabelle (permanent) ---


def _scenario_row(ctx: WorkflowContext, target_fc: float, label: str) -> str:
    dose = _shock_dose(ctx, target_fc)
    if dose is None:
        return f"| {label} | {target_fc:.1f} mg/l | — | — |"
    amount, unit = dose
    cya_add = _cya_from_shock(ctx, target_fc)
    cya_str = f"+{cya_add:.1f}" if cya_add > 0 else "—"
    if amount <= 0:
        return f"| {label} | {target_fc:.1f} mg/l | Ziel bereits erreicht | — |"
    return f"| {label} | {target_fc:.1f} mg/l | {amount:.0f} {unit} {ctx.shock_display} | {cya_str} |"


def _scenarios_table(ctx: WorkflowContext) -> list[str]:
    L = [
        "| Szenario | FC-Ziel | Dosis | CYA-Anstieg (mg/l) |",
        "|----------|--------:|------:|-------------------:|",
    ]
    # Breakpoint nur wenn CC erhöht (Schwelle = cc_shock_at). Ziel ist strikt 10× CC.
    if ctx.cc is not None and ctx.cc >= ctx.cc_shock_at:
        target = ctx.cc * 10.0
        L.append(_scenario_row(ctx, target, f"Breakpoint (10× CC = {target:.1f})"))
    for target, label in (
        (SHOCK_TARGET_ROUTINE, "Routine (präventiv, Wasserwechsel / Inbetriebnahme)"),
        (SHOCK_TARGET_ALGEN_LEICHT, "Algen leicht (grünlicher Schleier, Saisonstart)"),
        (SHOCK_TARGET_ALGEN_STARK, "Algen stark (grüne Brühe)"),
        (SHOCK_TARGET_SCHWARZALGEN, "Schwarzalgen (schwarze Punkte)"),
    ):
        L.append(_scenario_row(ctx, target, label))
    L.append("")
    return L


def _scenario_notes(ctx: WorkflowContext) -> list[str]:
    """Statische Hinweise zur Shock-Tabelle. Keine Messwert-abhängige Info."""
    notes: list[str] = [
        "Nach einer Dosis: Filter 24 h dauerhaft laufen lassen, dann neu messen. "
        "Algen-Szenarien zusätzlich Wände und Boden bürsten (2–3×); Schwarzalgen "
        "mechanisch + ggf. mehrtägiger Prozess.",
    ]
    if ctx.shock_type in SHOCK_STABILIZED:
        notes.append(
            f"{ctx.shock_display} ist stabilisiert — jede Dosis erhöht CYA "
            "(siehe Spalte rechts). Bei häufigem Shock steigt CYA stetig. Ab "
            "CYA > 75 mg/l Wasserteilwechsel oder Wechsel zu Flüssig-Chlor / "
            "Calciumhypochlorit erwägen."
        )
    return notes


def _measurement_notes(recs: dict[str, Recommendation]) -> list[str]:
    """Dynamische Hinweise aus den aktiven Recommendations.

    Chlor-Notes bei action=shock/raise werden übersprungen — die CYA-Warnung
    steht schon unter der Shock-Szenarien-Tabelle (via _scenario_notes).
    Nur Chlor-watch-Notes (z.B. Decay-Schätzung bei FC-Überdosis) bleiben,
    weil die sich auf die Wartezeit beziehen, nicht auf Dosieren.
    """
    notes: list[str] = []
    for key, label in (
        ("alkalinity", "Alkalität"),
        ("ph", "pH"),
        ("cya", "Cyanursäure"),
        ("chlorine", "Chlor"),
        ("calibration", "Drift pH Sonde"),
        ("drift_redox", "Drift Redox Sonde"),
    ):
        rec = recs.get(key)
        if rec is None or rec.note is None or rec.action in ("ok", "no_data"):
            continue
        if key == "chlorine" and rec.action in ("shock", "raise"):
            continue
        notes.append(f"**{label}**: {rec.note}")
    return notes


# --- Hauptrender (unified) ---


def render_normal(ctx: WorkflowContext, recs: dict[str, Recommendation]) -> str:
    # Kein Haupttitel — die HA-Markdown-Card hat ohnehin eine Überschrift.
    lines: list[str] = []

    # 1. Alerts — Bade-Status als einziger roter Alert
    is_safe = _swim_safety_check(ctx)
    if not is_safe:
        lines.append(
            '<ha-alert alert-type="error">Nicht baden — Werte außerhalb Bade-Bereich!</ha-alert>'
        )
        lines.append("")
    else:
        lines.append(
            '<ha-alert alert-type="success">Badefreigabe erteilt — alles im sicheren Bereich</ha-alert>'
        )
        lines.append("")

    # Gelbe Parameter-Warnungen für alle nicht-OK-Parameter
    for w in _param_warnings(ctx, recs):
        lines.append(f'<ha-alert alert-type="warning">{w}</ha-alert>')
        lines.append("")

    # Blaue Info-Alerts mit konkreten Handlungsanweisungen
    for a in _action_recommendations(ctx, recs):
        lines.append(f'<ha-alert alert-type="info">{a}</ha-alert>')
        lines.append("")

    # 2. Messwerte-Tabelle
    lines.append("---")
    lines.append("")
    lines.append(f"**Messwerte** ({ctx.volume_m3:.0f} m³):")
    lines.append("")
    lines += _values_table(ctx, recs)

    # Hinweise unter der Messwerte-Tabelle
    for n in _measurement_notes(recs):
        lines.append(f"> {n}")
        lines.append(">")
    if _measurement_notes(recs):
        lines.append("")

    # 3. Shock-Szenarien-Tabelle (permanent)
    lines.append("---")
    lines.append("")
    lines.append("**Shock-Szenarien** (falls gewünscht oder nötig):")
    lines.append("")
    lines += _scenarios_table(ctx)

    # Hinweise unter der Shock-Tabelle
    for n in _scenario_notes(ctx):
        lines.append(f"> {n}")
        lines.append(">")

    return "\n".join(lines)


# render_normal ist die einzige öffentliche Render-Funktion; für
# Rückwärts-Kompatibilität einfach als `render` aliased.
render = render_normal
