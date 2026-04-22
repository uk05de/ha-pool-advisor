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
    cya_pre_dose_grams,
    estimate_fc_decay_hours,
    shock_dose_grams_or_ml,
)
from .const import (
    MODE_NORMAL,
    MODE_SAISONSTART,
    MODE_WASSERWECHSEL,
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

    total_cl: float | None = None
    redox: float | None = None


# ---------- Hilfsfunktionen ----------


def _eff_ph(ctx: WorkflowContext) -> float | None:
    return ctx.ph_manual if ctx.ph_manual is not None else ctx.ph_auto


def _ta_dose_g(ctx: WorkflowContext) -> float | None:
    from .calculator import G_BICARB_PURE_PER_M3_PER_10_TA

    if ctx.ta is None:
        return None
    delta = ctx.ta_target - ctx.ta
    if delta <= 0:
        return 0.0
    return G_BICARB_PURE_PER_M3_PER_10_TA * ctx.volume_m3 * (delta / 10.0)


def _ph_dose(ctx: WorkflowContext) -> tuple[str, float] | None:
    """Returns (direction, grams) or None if no action. direction is 'up' or 'down'."""
    from .calculator import (
        G_DRY_ACID_PURE_PER_M3_PER_01_PH,
        G_SODA_PURE_PER_M3_PER_01_PH,
    )

    ph = _eff_ph(ctx)
    if ph is None:
        return None
    if ctx.ph_min <= ph <= ctx.ph_max:
        return None
    delta = ctx.ph_target - ph
    units = abs(delta) / 0.1
    if delta > 0:
        return ("up", G_SODA_PURE_PER_M3_PER_01_PH * ctx.volume_m3 * units)
    return ("down", G_DRY_ACID_PURE_PER_M3_PER_01_PH * ctx.volume_m3 * units)


def _cya_predose_g(ctx: WorkflowContext, shock_target_fc: float) -> float:
    current = ctx.cya if ctx.cya is not None else 0.0
    shock_increase = max(0.0, shock_target_fc - (ctx.fc or 0.0))
    g = cya_pre_dose_grams(
        current_cya=current,
        target_cya=ctx.cya_target,
        shock_fc_increase=shock_increase,
        shock_type=ctx.shock_type,
        volume_m3=ctx.volume_m3,
        cya_strength_pct=ctx.cya_strength_pct,
    )
    return g * 0.8  # 80 % Sicherheitspuffer


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


def _swim_safety_check(ctx: WorkflowContext) -> tuple[bool, set[str]]:
    """Returns (is_safe, keys_that_are_swim_blocking).

    Die claimed-Keys werden von _non_swim_warnings ausgeschlossen, damit
    nichts doppelt als Bade-Alert UND Warning-Alert angezeigt wird. Die
    genauen Gründe stehen ohnehin als Farbe in der Messwerte-Tabelle und
    als blauer Action-Alert.
    """
    claimed: set[str] = set()
    ph = _eff_ph(ctx)
    if ctx.fc is not None and (ctx.fc > 3.0 or ctx.fc < 0.3):
        claimed.add("chlorine")
    if ctx.cc is not None and ctx.cc > 0.5:
        claimed.add("chlorine")
    if ph is not None and (ph < 6.8 or ph > 7.8):
        claimed.add("ph")
    if ctx.cya is not None and ctx.cya > 100:
        claimed.add("cya")
    return len(claimed) == 0, claimed


def _non_swim_warnings(
    ctx: WorkflowContext,
    recs: dict[str, Recommendation],
    claimed: set[str],
) -> list[str]:
    """Sammelt Nicht-Bade-blockierende Baustellen. Keys in `claimed` werden
    übersprungen, weil sie schon als rote Swim-Block-Alerts erscheinen."""
    warnings: list[str] = []
    for key, label in (
        ("ph", "pH"),
        ("alkalinity", "Alkalität"),
        ("cya", "Cyanursäure"),
        ("calibration", "Drift pH Sonde"),
        ("drift_redox", "Drift Redox Sonde"),
    ):
        if key in claimed:
            continue
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
        ("ph", "pH"),
        ("alkalinity", "Alkalität"),
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
            alerts.append(
                "**Cyanursäure senken**: chemisch nicht möglich. Ca. 30 % Wasser teiltauschen, "
                "dann neu messen"
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

    # pH
    ph = _eff_ph(ctx)
    ph_str = _colored(f"{ph:.2f}", _color_ph_val(ph, ctx)) if ph is not None else "—"
    L.append(
        f"| pH | {ph_str} | {ctx.ph_target:.2f} | {ctx.ph_min:.1f} | {ctx.ph_max:.1f} |"
    )

    # Alkalität
    ta_str = (
        _colored(f"{ctx.ta:.0f}", _color_ta_val(ctx.ta, ctx))
        if ctx.ta is not None
        else "—"
    )
    L.append(
        f"| Alkalität (mg/l) | {ta_str} | {ctx.ta_target:.0f} | "
        f"{ctx.ta_min:.0f} | {ctx.ta_max:.0f} |"
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
        (SHOCK_TARGET_ROUTINE, "Routine (präventiv)"),
        (SHOCK_TARGET_ALGEN_LEICHT, "Algen leicht (grünlicher Schleier)"),
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
    """Dynamische Hinweise aus den aktiven Recommendations."""
    notes: list[str] = []
    for key in ("ph", "alkalinity", "chlorine", "cya", "calibration", "drift_redox"):
        rec = recs.get(key)
        if rec and rec.note and rec.action not in ("ok", "no_data"):
            notes.append(rec.note)
    return notes


# --- Hauptrender (unified) ---


def render_normal(ctx: WorkflowContext, recs: dict[str, Recommendation]) -> str:
    lines: list[str] = ["## Pool-Empfehlung", ""]

    # 1. Alerts — Bade-Status als einziger roter Alert (Details siehe Tabelle)
    is_safe, claimed = _swim_safety_check(ctx)
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

    for w in _non_swim_warnings(ctx, recs, claimed):
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


# ---------- Inbetriebnahme-Listen (Wasserwechsel / Saisonstart) ----------


def _inbetriebnahme_list(ctx: WorkflowContext, shock_target_fc: float, shock_label: str, include_brush: bool) -> list[str]:
    L: list[str] = []

    # 1. TA
    if ctx.ta is None:
        L += ["### ❔ 1. Alkalität", "TA noch nicht gemessen.", ""]
    elif ctx.ta_min <= ctx.ta <= ctx.ta_max:
        L += [f"### ✅ 1. Alkalität", f"TA **{ctx.ta:.0f} mg/l** (Ziel {ctx.ta_target:.0f}, Bereich {ctx.ta_min:.0f}–{ctx.ta_max:.0f}).", ""]
    else:
        dose = _ta_dose_g(ctx)
        if dose and dose > 0:
            L += [
                f"### ⚠ 1. Alkalität anheben",
                f"TA **{ctx.ta:.0f} mg/l** — Ziel {ctx.ta_target:.0f}.",
                "",
                f"Dosiere **{dose:.0f} g {ctx.ta_plus_display}** (in Eimer auflösen, verteilen).",
                "Filter 12–24 h durchlaufen, dann neu messen.",
                "",
            ]
        else:
            L += [
                f"### ⚠ 1. Alkalität senken",
                f"TA **{ctx.ta:.0f} mg/l** — Ziel {ctx.ta_target:.0f}.",
                "",
                "Mehrtägiger Prozess: pH auf ~7.0 senken, kräftig belüften, wiederholen.",
                "",
            ]

    # 2. pH grob
    ph = _eff_ph(ctx)
    if ph is None:
        L += ["### ❔ 2. pH grob", "pH noch nicht gemessen.", ""]
    elif ctx.ph_min <= ph <= ctx.ph_max:
        L += [f"### ✅ 2. pH grob", f"pH **{ph:.2f}** (Ziel {ctx.ph_target:.2f}, Bereich {ctx.ph_min:.1f}–{ctx.ph_max:.1f}).", ""]
    else:
        dose = _ph_dose(ctx)
        if dose:
            direction, grams = dose
            if direction == "up":
                L += [
                    f"### ⚠ 2. pH anheben",
                    f"pH **{ph:.2f}** — Ziel {ctx.ph_target:.2f}.",
                    "",
                    f"Dosiere **{grams:.0f} g {ctx.ph_plus_display}**. Filter 4–6 h, neu messen.",
                    "",
                ]
            else:
                L += [
                    f"### ⚠ 2. pH senken",
                    f"pH **{ph:.2f}** — Ziel {ctx.ph_target:.2f}.",
                    "",
                    f"Dosiere **{grams:.0f} g {ctx.ph_minus_display}**. Filter 4–6 h, neu messen.",
                    "",
                    "> Hinweis: erst pH grob einstellen, **dann** Dosierung aktivieren.",
                    "",
                ]

    # 3. pH-System
    L += [
        "### ○ 3. pH-Dosierung in Betrieb",
        "- Elektrode in Pufferlösungen **pH 7 + pH 4** kalibrieren",
        f"- Sollwert **{ctx.ph_target:.1f}** setzen",
        "- Dosierung einschalten",
        "",
    ]

    # 4. CYA
    if ctx.cya is None:
        L += ["### ❔ 4. Cyanursäure", "CYA noch nicht gemessen.", ""]
    elif ctx.cya >= ctx.cya_target * 0.9:
        L += [f"### ✅ 4. Cyanursäure", f"CYA **{ctx.cya:.0f} mg/l** (Ziel {ctx.cya_target:.0f}).", ""]
    else:
        pre_g = _cya_predose_g(ctx, shock_target_fc)
        if pre_g <= 0:
            L += [
                "### ✅ 4. Cyanursäure",
                f"CYA **{ctx.cya:.0f} mg/l** — Shock bringt genug nach, keine Vor-Dosierung nötig.",
                "",
            ]
        else:
            L += [
                "### ⚠ 4. Cyanursäure vor-dosieren",
                f"CYA **{ctx.cya:.0f} mg/l** — Ziel {ctx.cya_target:.0f}.",
                "",
                f"Dosiere **ca. {pre_g:.0f} g {ctx.cya_display}** (80 % Sicherheitspuffer).",
                "In Skimmer-Sockel/Socke geben — langsam löslich. Filter 24–48 h.",
                "",
                f"> Der nachfolgende Shock bringt zusätzlich ~{_cya_from_shock(ctx, shock_target_fc):.0f} mg/l CYA mit.",
                "",
            ]

    # 5. Chlor-System
    L += [
        "### ○ 5. Chlor-Dosierung in Betrieb",
        "- Redox-Elektrode mit **468 mV Prüflösung** kalibrieren",
        "- Redox-Sollwert **700 mV**",
        "- Kanister prüfen, Dosierung einschalten",
        "",
    ]

    # 6. Shock
    dose = _shock_dose(ctx, shock_target_fc)
    fc_now = ctx.fc if ctx.fc is not None else 0.0
    if fc_now >= shock_target_fc * 0.8:
        L += [
            f"### ✅ 6. {shock_label}",
            f"FC **{fc_now:.2f} mg/l** — Ziel {shock_target_fc:.0f} bereits erreicht.",
            "",
        ]
    elif dose is not None and dose[0] > 0:
        amount, unit = dose
        extra = ""
        if ctx.shock_type in SHOCK_STABILIZED:
            extra = f"\n⚠ Bringt ~{_cya_from_shock(ctx, shock_target_fc):.0f} mg/l CYA mit."
        brush_line = "\nZusätzlich Wände und Boden bürsten (2–3×)." if include_brush else ""
        L += [
            f"### ⚠ 6. {shock_label}",
            f"FC **{fc_now:.2f} mg/l** — Ziel {shock_target_fc:.0f}.",
            "",
            f"Dosiere **{amount:.0f} {unit} {ctx.shock_display}**. Filter 24 h durchlaufen.{brush_line}{extra}",
            "",
        ]
    else:
        L += [f"### ❔ 6. {shock_label}", "Shock-Produkt nicht konfiguriert.", ""]

    # 7. Badebetrieb-Freigabe
    L += _swim_ready_block(ctx, nr=7)

    return L


def _swim_ready_block(ctx: WorkflowContext, nr: int | None = None) -> list[str]:
    prefix = f"{nr}. " if nr is not None else ""
    if ctx.fc is None:
        return [f"### ❔ {prefix}Badebetrieb-Freigabe", "FC noch nicht gemessen.", ""]
    reasons: list[str] = []
    # Direkte Reizungsfaktoren
    if ctx.fc > 3.0:
        reasons.append(f"FC **{ctx.fc:.2f}** zu hoch (Ziel ≤ 3.0 mg/l) — reizt Augen/Haut")
    if ctx.fc < 0.3:
        reasons.append(f"FC **{ctx.fc:.2f}** zu niedrig (mind. 0.3 mg/l) — keine Desinfektion")
    if ctx.cc is not None and ctx.cc > 0.5:
        reasons.append(f"CC **{ctx.cc:.2f}** zu hoch (Chloramin-Belastung, reizt)")
    ph = _eff_ph(ctx)
    if ph is not None and (ph < 6.8 or ph > 7.8):
        reasons.append(f"pH **{ph:.2f}** außerhalb 6.8–7.8 — reizt Augen/Haut")
    # Indirekte Sicherheit: CYA-Lock
    if ctx.cya is not None and ctx.cya > 100:
        reasons.append(
            f"CYA **{ctx.cya:.0f}** mg/l zu hoch — Chlorine-Lock, Chlor wirkt nicht mehr "
            "richtig (Wassertausch nötig)"
        )
    elif ctx.cya is not None and ctx.cya > 75 and ctx.fc < 2.0:
        reasons.append(
            f"CYA {ctx.cya:.0f} reduziert Chlor-Wirksamkeit — FC {ctx.fc:.2f} "
            "evtl. zu niedrig für sichere Desinfektion"
        )
    if not reasons:
        return [
            f"### ✅ {prefix}Badebetrieb-Freigabe",
            f"FC {ctx.fc:.2f}, CC {_val(ctx.cc, 'mg/l')}, pH {_val(ph, '')}, "
            f"CYA {_val(ctx.cya, 'mg/l', 0)} — alles im sicheren Bereich. Pool nutzbar.",
            "",
        ]
    # FC-Abklingzeit-Schätzung wenn FC das Hauptproblem ist
    extra = ""
    if ctx.fc > 3.0:
        hours = estimate_fc_decay_hours(
            fc_current=ctx.fc,
            fc_target=3.0,
            cya=ctx.cya,
            water_temp_c=ctx.water_temp,
        )
        if hours is not None and hours > 0:
            lo_d = hours * 0.75 / 24
            hi_d = hours * 1.25 / 24
            if hi_d < 1.5:
                range_str = f"{max(1, int(hours * 0.75))}–{max(2, int(hours * 1.25))} h"
            else:
                range_str = f"{lo_d:.1f}–{hi_d:.1f} Tage"
            extra = f"\n⏳ Geschätzt **~{range_str}** bis FC ≤ 3 (Filter an, Abdeckung ab)."
    return [
        f"### ⚠ {prefix}Badebetrieb-Freigabe",
        "Noch nicht badetauglich:",
        *(f"- {r}" for r in reasons),
        f"{extra}",
        "> Aktives Senken nicht nötig — Filter + UV + Zeit reichen.",
        "",
    ]


def render_wasserwechsel(ctx: WorkflowContext, _recs: dict[str, Recommendation]) -> str:
    L = [
        "## Pool-Empfehlung — Wasserwechsel / Inbetriebnahme",
        "",
        "**Voraussetzungen:** Pool befüllt → Filter 2–4 h gelaufen → PoolLab-Messung übertragen.",
        "",
        "---",
        "",
    ]
    L += _inbetriebnahme_list(ctx, SHOCK_TARGET_ROUTINE, "Routine-Shock", include_brush=False)
    return "\n".join(L)


def render_saisonstart(ctx: WorkflowContext, _recs: dict[str, Recommendation]) -> str:
    L = [
        "## Pool-Empfehlung — Saisonstart nach Winter",
        "",
        "**Voraussetzungen:** Abdeckung ab → inspizieren → **gründlich rückspülen** "
        "(1–3 m³ Verlust, TA/CYA checken) → Filter 2–4 h → messen.",
        "",
        "---",
        "",
    ]
    L += _inbetriebnahme_list(ctx, SHOCK_TARGET_ALGEN_LEICHT, "Shock gegen Bio-Last", include_brush=True)
    return "\n".join(L)


# ---------- Schockchlorung: alle Szenarien zum Auswählen ----------


# ---------- Registry ----------


MODE_RENDERERS: dict[str, callable] = {
    MODE_NORMAL: render_normal,
    MODE_WASSERWECHSEL: render_wasserwechsel,
    MODE_SAISONSTART: render_saisonstart,
}
