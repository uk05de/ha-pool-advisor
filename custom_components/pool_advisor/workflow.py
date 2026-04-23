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

from dataclasses import dataclass, field
from datetime import datetime

from .calculator import (
    Recommendation,
    method_hint,
    shock_dose_grams_or_ml,
)
from .const import (
    FC_CYA_RATIO_HIGH,
    FC_CYA_RATIO_MIN,
    SHOCK_CYA_PER_PPM_CL,
    SHOCK_STABILIZED,
    SHOCK_TARGET_ALGEN_LEICHT,
    SHOCK_TARGET_ALGEN_STARK,
    SHOCK_TARGET_ROUTINE,
    SHOCK_TARGET_SCHWARZALGEN,
)


def _redox_level_warning(ctx: WorkflowContext) -> str | None:
    """Gelbe Warnung wenn Live-Redox außerhalb der kritischen Schwellen liegt.
    Diagnose-Hinweis auf Elektrode / Kanister / Produktionsrate — keine
    direkte Dosier-Empfehlung (das macht FC).
    """
    if ctx.redox is None:
        return None
    if ctx.redox < ctx.redox_critical_low:
        return (
            f"**Redox**: {ctx.redox:.0f} mV zu niedrig (kritisch < {ctx.redox_critical_low:.0f}) — "
            "Chlor-Kanister der Dosieranlage prüfen (leer?), Produktionsrate der "
            "Elektrolyse erhöhen oder Elektrode-Kalibrierung checken."
        )
    if ctx.redox > ctx.redox_critical_high:
        return (
            f"**Redox**: {ctx.redox:.0f} mV zu hoch (kritisch > {ctx.redox_critical_high:.0f}) — "
            "Überdosierung oder Sondendrift? Manuelles FC nachmessen, ggf. Elektrode neu kalibrieren."
        )
    return None


def _fc_cya_ratio_issue(ctx: WorkflowContext) -> dict | None:
    """Prüft ob FC im Verhältnis zu CYA sinnvoll liegt.

    Rückgabe:
        None wenn alles ok oder eine Messung fehlt.
        dict(direction, fc_suggested, reason) wenn außerhalb des TFP-Bands.
    """
    if ctx.fc is None or ctx.cya is None or ctx.cya <= 0:
        return None
    min_fc = ctx.cya * FC_CYA_RATIO_MIN
    max_fc = ctx.cya * FC_CYA_RATIO_HIGH
    if ctx.fc < min_fc:
        return {
            "direction": "low",
            "fc_suggested": min_fc,
            "reason": (
                f"FC {ctx.fc:.2f} mg/l ist für deinen CYA-Level ({ctx.cya:.0f}) zu niedrig. "
                f"Mindestens ~{min_fc:.2f} mg/l nötig (CYA × {FC_CYA_RATIO_MIN:.2f}), "
                "sonst wird Chlor von CYA gebunden und die Sanitation leidet."
            ),
        }
    if ctx.fc > max_fc:
        return {
            "direction": "high",
            "fc_suggested": max_fc,
            "reason": (
                f"FC {ctx.fc:.2f} mg/l liegt für deinen CYA-Level ({ctx.cya:.0f}) im SLAM-Bereich. "
                f"Komfort-Obergrenze ~{max_fc:.2f} mg/l (CYA × {FC_CYA_RATIO_HIGH:.2f}) — "
                "kurzfristig ok, abwarten bis Chlor abbaut."
            ),
        }
    return None


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
    fc_critical_high: float = 5.0
    fc_min_val: float = 0.5
    fc_max: float = 1.5
    cc_max: float = 0.2
    cc_critical_high: float = 0.5
    cya_min: float = 20.0
    cya_max: float = 50.0
    cya_critical_low: float = 0.0
    cya_critical_high: float = 75.0
    ph_calib_threshold: float = 0.2
    redox_drift_threshold: float = 70.0

    # Redox-Ziele
    redox_min: float = 650.0
    redox_target: float = 700.0
    redox_max: float = 750.0
    redox_critical_low: float = 600.0
    redox_critical_high: float = 800.0

    total_cl: float | None = None
    redox: float | None = None

    # Stale-Tracking je Parameter — Keys: ph_manual, ta, fc, cc, tc, cya
    stale: dict[str, bool] = field(default_factory=dict)
    measured_at: dict[str, datetime | None] = field(default_factory=dict)
    stale_days: dict[str, int] = field(default_factory=dict)


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
COLOR_YELLOW_STALE = "#d9a441"  # Veraltet-Hinweis, deutlich gegen Orange abgesetzt


# --- Stale-Mapping ---

# Logisches Parameter-Key → Label-Anzeige in Warnung und Tabelle
_STALE_LABELS: dict[str, str] = {
    "ta": "Alkalität",
    "ph_manual": "pH (Photometer)",
    "fc": "Chlor frei",
    "cc": "Chlor gebunden",
    "tc": "Chlor gesamt",
    "cya": "Cyanursäure",
}


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
    if fc < ctx.fc_critical_low or fc > ctx.fc_critical_high:
        return COLOR_RED
    if fc < ctx.fc_min_val or fc > ctx.fc_max:
        return COLOR_ORANGE
    return COLOR_GREEN


def _color_cc_val(cc: float | None, ctx: WorkflowContext) -> str:
    if cc is None:
        return COLOR_GREY
    if cc >= ctx.cc_critical_high:
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
    if redox < ctx.redox_critical_low or redox > ctx.redox_critical_high:
        return COLOR_RED
    if redox < ctx.redox_min or redox > ctx.redox_max:
        return COLOR_ORANGE
    return COLOR_GREEN


def _color_cya_val(cya: float | None, ctx: WorkflowContext) -> str:
    if cya is None:
        return COLOR_GREY
    # Kritisch hoch oder (nur wenn aktiviert) kritisch niedrig → rot
    if cya >= ctx.cya_critical_high:
        return COLOR_RED
    if ctx.cya_critical_low > 0 and cya < ctx.cya_critical_low:
        return COLOR_RED
    # Außerhalb Zielbereich aber nicht kritisch → orange
    if cya < ctx.cya_min or cya > ctx.cya_max:
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
    if ctx.fc is not None and (ctx.fc > ctx.fc_critical_high or ctx.fc < ctx.fc_critical_low):
        return False
    if ctx.cc is not None and ctx.cc >= ctx.cc_critical_high:
        return False
    if ph is not None and (ph < ctx.ph_critical_low or ph > ctx.ph_critical_high):
        return False
    if ctx.cya is not None and ctx.cya > 100:
        return False
    return True


def _stale_warnings(ctx: WorkflowContext) -> list[str]:
    """Konsolidierter gelber Alert pro veraltetem Parameter.

    Zeigt Label + Alter in Tagen + konfiguriertes Limit. Wenn keine Messung
    vorhanden ist (kein `measured_at`), entsteht kein Warning — das ist
    Normalzustand vor dem ersten Testen.
    """
    parts: list[str] = []
    now = datetime.now().astimezone()
    for key, label in _STALE_LABELS.items():
        if not ctx.stale.get(key):
            continue
        measured = ctx.measured_at.get(key)
        if measured is None:
            continue
        age_days = (now - measured).total_seconds() / 86400.0
        limit = ctx.stale_days.get(key, 0)
        parts.append(
            f"**{label}**: Messung vor {age_days:.0f} Tagen "
            f"(Schwelle {limit} d) — neu messen empfohlen"
        )
    if not parts:
        return []
    body = "<br>".join(parts)
    return [f'<ha-alert alert-type="warning">Veraltete Messwerte<br>{body}</ha-alert>']


def _param_warnings(
    ctx: WorkflowContext,
    recs: dict[str, Recommendation],
) -> tuple[list[str], list[str]]:
    """Splitet Parameter-Warnungen in (rot=critical, gelb=warning).

    Reihenfolge TA → pH → CYA → Chlor → FC/CYA-Ratio → Redox → Drifts,
    so dass der User von oben nach unten abarbeiten kann.
    """
    critical: list[str] = []
    warning: list[str] = []

    def _push(label: str, rec: Recommendation) -> None:
        line = f"**{label}**: {rec.reason}"
        (critical if rec.is_critical else warning).append(line)

    for key, label in (
        ("alkalinity", "Alkalität"),
        ("ph", "pH"),
        ("cya", "Cyanursäure"),
        ("chlorine", "Chlor"),
    ):
        rec = recs.get(key)
        if rec is None or rec.action in ("ok", "no_data"):
            continue
        _push(label, rec)

    # FC/CYA-Verhältnis (chemie-basiert, nie critical — reine Warnung)
    ratio_issue = _fc_cya_ratio_issue(ctx)
    if ratio_issue is not None:
        warning.append(f"**FC/CYA-Verhältnis**: {ratio_issue['reason']}")

    # Redox-Level (außerhalb critical-Band) → rot
    redox_warn = _redox_level_warning(ctx)
    if redox_warn is not None:
        critical.append(redox_warn)

    # Drifts zum Schluss
    for key, label in (
        ("calibration", "Drift pH Sonde"),
        ("drift_redox", "Drift Redox Sonde"),
    ):
        rec = recs.get(key)
        if rec is None or rec.action in ("ok", "no_data"):
            continue
        _push(label, rec)

    return critical, warning


def _format_steps_inline(steps) -> str:
    """Fasst Dose-Steps als kompakte Zeile zusammen.

    Bei ≥ 3 gleich großen Teildosen: "Dosiere N × X Einheit Produkt,
    alle Y h (gesamt Z, ~M h bis Kontroll-Messung)" statt langer Aufzählung.
    Gesamtzeit = n × wait (letzte Dosis + nochmal wait bis nachmessen).
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
        total_h = n * wait
        return (
            f"Dosiere **{n}× {s.amount:g} {s.unit}** {s.product}"
            f"{wait_str} (gesamt ~{total:g} {s.unit}, ~{total_h} h bis Kontroll-Messung)"
        )
    parts: list[str] = []
    for i, s in enumerate(steps, 1):
        parts.append(f"**{s.amount:g} {s.unit}** {s.product}")
        if s.wait_hours > 0 and i < len(steps):
            parts.append(f"{s.wait_hours} h warten")
    # Letzter Step hat wait_hours=0; aber User muss nach letzter Dosis nochmal
    # Wartezeit abwarten bis Messung Sinn ergibt — also interval addieren.
    if len(steps) >= 2 and steps[0].wait_hours > 0:
        parts.append(f"dann {steps[0].wait_hours} h bis Kontroll-Messung")
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

    # Chlor-Aktionen: WAS im Banner, WIE in der Shock-Tabelle, WARUM unter Chem-Tabelle.
    cl_rec = recs.get("chlorine")
    if cl_rec is not None and cl_rec.steps:
        if cl_rec.action == "shock":
            alerts.append(
                "**Chlor**: Breakpoint-Chlorung durchführen — siehe Shock-Tabelle unten."
            )
        elif cl_rec.action == "raise":
            alerts.append(
                "**Chlor**: Routine-Shock durchführen — siehe Shock-Tabelle unten."
            )

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

    ratio_issue = _fc_cya_ratio_issue(ctx)
    ratio_affected = {"fc", "cya"} if ratio_issue else set()

    def _row(label: str, actual: str, ziel: str, mn: str, mx: str, stale_key: str | None) -> str:
        # Aktuell-Zelle behält ihre Status-Farbe; restliche Zellen und das Label
        # werden gelb wenn der Messwert veraltet ist ODER das FC/CYA-Verhältnis
        # für diese Zeile auffällig ist.
        is_yellow = (
            (stale_key is not None and ctx.stale.get(stale_key))
            or (stale_key in ratio_affected)
        )
        if is_yellow:
            label = _colored(label, COLOR_YELLOW_STALE)
            ziel = _colored(ziel, COLOR_YELLOW_STALE) if ziel != "—" else ziel
            mn = _colored(mn, COLOR_YELLOW_STALE) if mn != "—" else mn
            mx = _colored(mx, COLOR_YELLOW_STALE) if mx != "—" else mx
        return f"| {label} | {actual} | {ziel} | {mn} | {mx} |"

    # Alkalität (Puffer — kommt zuerst in der Chemie-Reihenfolge)
    ta_str = (
        _colored(f"{ctx.ta:.0f}", _color_ta_val(ctx.ta, ctx))
        if ctx.ta is not None
        else "—"
    )
    L.append(_row(
        "Alkalität (mg/l)", ta_str, f"{ctx.ta_target:.0f}",
        f"{ctx.ta_min:.0f}", f"{ctx.ta_max:.0f}", "ta",
    ))

    # pH Manuell (PoolLab-Photometer)
    ph_m = ctx.ph_manual
    ph_m_str = _colored(f"{ph_m:.2f}", _color_ph_val(ph_m, ctx)) if ph_m is not None else "—"
    L.append(_row(
        "pH Manuell", ph_m_str, f"{ctx.ph_target:.2f}",
        f"{ctx.ph_min:.1f}", f"{ctx.ph_max:.1f}", "ph_manual",
    ))

    # pH Dosieranlage (Bayrol-Elektrode, live — kein Stale-Check, ist ohnehin live)
    ph_a = ctx.ph_auto
    ph_a_str = _colored(f"{ph_a:.2f}", _color_ph_val(ph_a, ctx)) if ph_a is not None else "—"
    L.append(_row(
        "pH Dosieranlage", ph_a_str, f"{ctx.ph_target:.2f}",
        f"{ctx.ph_min:.1f}", f"{ctx.ph_max:.1f}", None,
    ))

    # Cyanursäure
    cya_str = (
        _colored(f"{ctx.cya:.0f}", _color_cya_val(ctx.cya, ctx))
        if ctx.cya is not None
        else "—"
    )
    L.append(_row(
        "Cyanursäure (mg/l)", cya_str, f"{ctx.cya_target:.0f}",
        f"{ctx.cya_min:.0f}", f"{ctx.cya_max:.0f}", "cya",
    ))

    # Chlor frei (FC)
    fc_str = (
        _colored(f"{ctx.fc:.2f}", _color_fc_val(ctx.fc, ctx))
        if ctx.fc is not None
        else "—"
    )
    L.append(_row(
        "Chlor frei (mg/l)", fc_str, f"{ctx.fc_target:.2f}",
        f"{ctx.fc_min_val:.2f}", f"{ctx.fc_max:.2f}", "fc",
    ))

    # Chlor gebunden (CC)
    cc_str = (
        _colored(f"{ctx.cc:.2f}", _color_cc_val(ctx.cc, ctx))
        if ctx.cc is not None
        else "—"
    )
    L.append(_row("Chlor geb. (mg/l)", cc_str, "—", "—", f"{ctx.cc_max:.2f}", "cc"))

    # Chlor gesamt (TC)
    tc_str = (
        _colored(f"{ctx.total_cl:.2f}", _color_tc_val(ctx.total_cl, ctx))
        if ctx.total_cl is not None
        else "—"
    )
    L.append(_row("Chlor gesamt (mg/l)", tc_str, "—", "—", "—", "tc"))

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
    # Breakpoint nur wenn CC erhöht (Schwelle = cc_critical_high). Ziel ist strikt 10× CC.
    if ctx.cc is not None and ctx.cc >= ctx.cc_critical_high:
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
    method = method_hint(ctx.shock_type) if ctx.shock_type else None
    if method:
        notes.append(f"**Anwendung {ctx.shock_display}**: {method}")
    if ctx.shock_type in SHOCK_STABILIZED:
        notes.append(
            f"{ctx.shock_display} ist stabilisiert — jede Dosis erhöht CYA "
            "(siehe Spalte rechts). Bei häufigem Shock steigt CYA stetig. Ab "
            "CYA > 75 mg/l Wasserteilwechsel oder Wechsel zu Flüssig-Chlor / "
            "Calciumhypochlorit erwägen."
        )
    return notes


def _safety_rules() -> list[str]:
    """Generelle Sicherheitsregeln beim manuellen Dosieren — immer zeigen."""
    return [
        "**Sicherheitsregeln beim manuellen Dosieren**",
        "• **Immer nur eine Chemikalie pro Eimer und Dosiervorgang.** "
        "Nach jeder Dosis Zirkulation abwarten, neu messen, erst dann nächste Chemikalie.",
        "• **Erst Wasser in den Eimer, dann die Säure/Chemikalie** — niemals umgekehrt (Spritzgefahr).",
        "• **Niemals zwei Pool-Chemikalien zusammenkippen** — Säure + Chlor = Chlorgas, "
        "Dichlor + Cal-Hypo = exotherme Reaktion. Eimer nach jeder Anwendung ausspülen, "
        "nicht 'nachfüllen'.",
    ]


def _measurement_notes(recs: dict[str, Recommendation]) -> list[str]:
    """Dynamische Hinweise aus den aktiven Recommendations — unter der Tabelle."""
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
        notes.append(f"**{label}**: {rec.note}")
    return notes


def _fc_cya_ratio_explanation(ctx: WorkflowContext) -> str | None:
    """Erklärungs-Text unter der Tabelle wenn das FC/CYA-Verhältnis auffällig ist."""
    issue = _fc_cya_ratio_issue(ctx)
    if issue is None:
        return None
    if issue["direction"] == "low":
        return (
            f"**FC/CYA-Hinweis**: bei CYA {ctx.cya:.0f} mg/l sollte FC ≥ "
            f"**{issue['fc_suggested']:.2f} mg/l** sein (TFP-Faustregel CYA × "
            f"{FC_CYA_RATIO_MIN:.2f}). Aktuell ist Chlor größtenteils an CYA gebunden; "
            "die aktive HOCl-Fraktion reicht nicht zum sauber-halten. Routinedosis anheben "
            "oder Produktionsrate der Dosieranlage steigern."
        )
    # direction == "high"
    return (
        f"**FC/CYA-Hinweis**: bei CYA {ctx.cya:.0f} mg/l liegt die Komfort-Obergrenze bei "
        f"**~{issue['fc_suggested']:.2f} mg/l** (CYA × {FC_CYA_RATIO_HIGH:.2f}). Aktuell "
        "höher — Chlor-Dosierung pausieren lassen und warten, bis FC durch UV/Verbrauch abklingt. "
        "Nur bei SLAM-Prozess (Algen/Kontamination) gewollt."
    )


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

    # Strikte Reihenfolge: rot → gelb → blau.
    # 1) Rote Parameter-Warnungen (MUSS) in Chemie-Reihenfolge
    # 2) Stale-Warnungen + gelbe Parameter-Warnungen (SOLLTE)
    # 3) Blaue Handlungsempfehlungen (Chemie-Reihenfolge via _action_recommendations)
    critical_warnings, yellow_warnings = _param_warnings(ctx, recs)
    for w in critical_warnings:
        lines.append(f'<ha-alert alert-type="error">{w}</ha-alert>')
        lines.append("")
    for a in _stale_warnings(ctx):
        lines.append(a)
        lines.append("")
    for w in yellow_warnings:
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
    notes_below = list(_measurement_notes(recs))
    ratio_explain = _fc_cya_ratio_explanation(ctx)
    if ratio_explain:
        notes_below.append(ratio_explain)
    for n in notes_below:
        lines.append(f"> {n}")
        lines.append(">")
    if notes_below:
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

    # Generelle Sicherheits-Regeln beim manuellen Dosieren
    lines.append("")
    lines.append("---")
    lines.append("")
    for n in _safety_rules():
        lines.append(n)
        lines.append("")

    return "\n".join(lines)


# render_normal ist die einzige öffentliche Render-Funktion; für
# Rückwärts-Kompatibilität einfach als `render` aliased.
render = render_normal
