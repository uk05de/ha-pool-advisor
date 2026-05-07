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
from datetime import datetime as _datetime

from .calculator import (
    Recommendation,
    compute_cya_exchange,
    compute_ph_minus_dose,
    format_steps_short,
    format_total_hours,
    method_hint,
    method_plain,
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
    TA_PLUS_BICARB,
)


def _redox_critical_banner(ctx: WorkflowContext) -> str | None:
    """Roter Status-Banner wenn Redox außerhalb critical-Band.
    Details liegen in der Note (Format D)."""
    if ctx.redox is None:
        return None
    if ctx.redox < ctx.redox_critical_low:
        return (
            f"**Redox**: {ctx.redox:.0f} mV zu niedrig (kritisch < {ctx.redox_critical_low:.0f}) "
            "— zu wenig aktives Chlor im Wasser"
        )
    if ctx.redox > ctx.redox_critical_high:
        return (
            f"**Redox**: {ctx.redox:.0f} mV zu hoch (kritisch > {ctx.redox_critical_high:.0f}) "
            "— Überdosierung oder Sondendrift"
        )
    return None


def _redox_watch_banner(ctx: WorkflowContext) -> str | None:
    """Gelber Banner wenn Redox mild außerhalb min/max aber nicht kritisch."""
    if ctx.redox is None:
        return None
    if ctx.redox_critical_low <= ctx.redox < ctx.redox_min:
        return f"**Redox**: {ctx.redox:.0f} mV niedrig — Dosieranlage sollte selbst nachregeln"
    if ctx.redox_max < ctx.redox <= ctx.redox_critical_high:
        return f"**Redox**: {ctx.redox:.0f} mV hoch — Anlage pausiert, sollte selbst abklingen"
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
                f"FC {ctx.fc:.2f} mg/l zu niedrig für CYA {ctx.cya:.0f} mg/l "
                f"(min ~{min_fc:.2f})"
            ),
        }
    if ctx.fc > max_fc:
        return {
            "direction": "high",
            "fc_suggested": max_fc,
            "reason": (
                f"FC {ctx.fc:.2f} mg/l zu hoch für CYA {ctx.cya:.0f} mg/l "
                f"(max ~{max_fc:.2f})"
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
    measured_at: dict[str, _datetime | None] = field(default_factory=dict)
    stale_days: dict[str, int] = field(default_factory=dict)

    # pH-Minus-Konfig (für Format C TA-Senkung — Erst-Dosis berechnen):
    ph_minus_type: str = ""
    ph_minus_strength_pct: float = 0.0


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


def _status_short(reason: str | None) -> str:
    """Extrahiert den Status-Teil (vor dem ersten em-Dash) aus rec.reason."""
    if not reason:
        return ""
    return reason.split(" — ")[0].strip()


# --- Per-Parameter Banner-Composer (jeder liefert (severity, text) oder None) ---


def _banner_ta(rec: Recommendation, ctx: WorkflowContext) -> tuple[str, str] | None:
    if rec is None or rec.action in ("ok", "no_data"):
        return None
    status = _status_short(rec.reason)
    if rec.action == "watch":
        return "info", f"**Alkalität**: {status} — beobachten"
    if rec.action == "raise" and rec.steps:
        return (
            "critical" if rec.is_critical else "warning",
            f"**Alkalität**: {status} — Dosiere {format_steps_short(rec.steps)}",
        )
    if rec.action == "lower":
        return (
            "critical" if rec.is_critical else "warning",
            f"**Alkalität**: {status} — TA-Senkung starten",
        )
    return None


def _banner_ph(rec: Recommendation, ctx: WorkflowContext) -> tuple[str, str] | None:
    if rec is None or rec.action in ("ok", "no_data"):
        return None
    status = _status_short(rec.reason)
    if rec.action == "watch":
        return "info", f"**pH**: {status} — Dosieranlage regelt, beobachten"
    if rec.steps:
        return (
            "critical" if rec.is_critical else "warning",
            f"**pH**: {status} — Dosiere {format_steps_short(rec.steps)}",
        )
    return None


def _banner_cya(rec: Recommendation, ctx: WorkflowContext) -> tuple[str, str] | None:
    if rec is None or rec.action in ("ok", "no_data"):
        return None
    status = _status_short(rec.reason)
    severity = "critical" if rec.is_critical else "warning"
    if rec.action == "raise" and rec.steps:
        return severity, f"**Cyanursäure**: {status} — Dosiere {format_steps_short(rec.steps)}"
    if rec.action == "lower":
        return severity, f"**Cyanursäure**: {status} — Wasserteilwechsel"
    return None


def _banner_chlorine(rec: Recommendation, ctx: WorkflowContext) -> tuple[str, str] | None:
    if rec is None or rec.action in ("ok", "no_data"):
        return None
    status = _status_short(rec.reason)
    if rec.action == "shock" and rec.steps:
        return "critical", (
            f"**Chlor**: {status} — Breakpoint-Shock: {format_steps_short(rec.steps)}"
        )
    if rec.action == "raise" and rec.steps:
        return (
            "critical" if rec.is_critical else "warning",
            f"**Chlor**: {status} — Routine-Shock: {format_steps_short(rec.steps)}",
        )
    if rec.action == "lower":
        return "critical", f"**Chlor**: {status} — nicht baden, abwarten"
    if rec.action == "watch":
        # rec.reason enthält bereits Status + Tail ("niedrig — beobachten" etc.)
        return "info", f"**Chlor**: {rec.reason}"
    return None


def _banner_ratio(ctx: WorkflowContext) -> tuple[str, str] | None:
    """FC/CYA-Verhältnis — nur wenn CYA frisch."""
    if ctx.stale.get("cya"):
        return None
    issue = _fc_cya_ratio_issue(ctx)
    if issue is None:
        return None
    if issue["direction"] == "low":
        text = (
            f"**FC/CYA**: {issue['reason']} — Sollwert auf "
            f"~{issue['fc_suggested']:.2f} mg/l anheben oder CYA senken"
        )
    else:
        text = f"**FC/CYA**: {issue['reason']} — abwarten, Chlor klingt ab"
    return "warning", text


def _banner_redox_level(ctx: WorkflowContext) -> tuple[str, str] | None:
    """Redox Level — kritisch rot oder mild blau."""
    if ctx.redox is None:
        return None
    if ctx.redox < ctx.redox_critical_low:
        return "critical", (
            f"**Redox**: {ctx.redox:.0f} mV zu niedrig "
            f"(kritisch < {ctx.redox_critical_low:.0f}) — Kanister / Produktion / Elektrode prüfen"
        )
    if ctx.redox > ctx.redox_critical_high:
        return "critical", (
            f"**Redox**: {ctx.redox:.0f} mV zu hoch "
            f"(kritisch > {ctx.redox_critical_high:.0f}) — FC manuell prüfen, Elektrode ggf. kalibrieren"
        )
    if ctx.redox_critical_low <= ctx.redox < ctx.redox_min:
        return "info", (
            f"**Redox**: {ctx.redox:.0f} mV leicht niedrig — Dosieranlage regelt, beobachten"
        )
    if ctx.redox_max < ctx.redox <= ctx.redox_critical_high:
        return "info", (
            f"**Redox**: {ctx.redox:.0f} mV leicht hoch — Anlage pausiert, beobachten"
        )
    return None


def _banner_drift(rec: Recommendation, label: str) -> tuple[str, str] | None:
    if rec is None or rec.action != "calibrate":
        return None
    return "warning", f"**{label}**: {rec.reason} — Elektrode kalibrieren"


def _banner_stale_list(ctx: WorkflowContext) -> list[tuple[str, str]]:
    """Pro stalem Parameter ein eigener Banner — Severity nach
    Überschreitungs-% (> 50 % → rot, sonst gelb)."""
    out: list[tuple[str, str]] = []
    now = _datetime.now().astimezone()
    for key, label in _STALE_LABELS.items():
        if not ctx.stale.get(key):
            continue
        measured = ctx.measured_at.get(key)
        if measured is None:
            continue
        age_days = (now - measured).total_seconds() / 86400.0
        limit = ctx.stale_days.get(key, 0)
        if limit <= 0:
            continue
        overdue_days = age_days - limit
        overdue_pct = overdue_days / limit
        if overdue_pct > 0.5:
            severity = "critical"
            tail = "— **dringend** neu messen"
        else:
            severity = "warning"
            tail = "— neu messen"
        out.append((
            severity,
            f"**{label}**: Messung {overdue_days:.0f} Tage überfällig "
            f"(Schwelle {limit} d) {tail}",
        ))
    return out


def _build_banners(
    ctx: WorkflowContext, recs: dict[str, Recommendation]
) -> list[tuple[str, str]]:
    """Liefert alle Parameter-Banner als (severity, text)-Liste.

    Reihenfolge innerhalb einer Severity: TA → pH → CYA → Chlor → Ratio →
    Redox → Drifts → Stale. Severity-Sortierung macht render_normal.
    """
    banners: list[tuple[str, str]] = []

    for builder in (
        lambda: _banner_ta(recs.get("alkalinity"), ctx),
        lambda: _banner_ph(recs.get("ph"), ctx),
        lambda: _banner_cya(recs.get("cya"), ctx),
        lambda: _banner_chlorine(recs.get("chlorine"), ctx),
        lambda: _banner_ratio(ctx),
        lambda: _banner_redox_level(ctx),
        lambda: _banner_drift(recs.get("calibration"), "Drift pH Sonde"),
        lambda: _banner_drift(recs.get("drift_redox"), "Drift Redox Sonde"),
    ):
        b = builder()
        if b is not None:
            banners.append(b)

    banners.extend(_banner_stale_list(ctx))
    return banners


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
    """Konkrete Handlungsanweisungen als Info-Alert (blau).
    Reihenfolge: TA → pH → CYA → Chlor → Drifts."""
    alerts: list[str] = []

    # TA
    ta_rec = recs.get("alkalinity")
    if ta_rec is not None and ta_rec.action not in ("ok", "no_data", "watch"):
        if ta_rec.steps:
            alerts.append(f"**Alkalität**: Dosiere {format_steps_short(ta_rec.steps)}")
        elif ta_rec.action == "lower":
            alerts.append(
                "**Alkalität**: TA-Senkung starten — mehrtägiger Prozess, Anleitung "
                "unter der Messwerte-Tabelle."
            )

    # pH
    ph_rec = recs.get("ph")
    if ph_rec is not None and ph_rec.action not in ("ok", "no_data", "watch") and ph_rec.steps:
        alerts.append(f"**pH**: Dosiere {format_steps_short(ph_rec.steps)}")

    # CYA
    cya_rec = recs.get("cya")
    if cya_rec is not None and cya_rec.action not in ("ok", "no_data", "watch"):
        if cya_rec.action == "raise" and cya_rec.steps:
            alerts.append(
                f"**Cyanursäure**: Dosiere {format_steps_short(cya_rec.steps)}"
            )
        elif cya_rec.action == "lower":
            alerts.append(
                "**Cyanursäure**: Wasserteilwechsel starten — Anleitung unter der Messwerte-Tabelle."
            )

    # Chlor — konkrete Dosis inline (Shock-Tabelle nur für manuelle Szenarien)
    cl_rec = recs.get("chlorine")
    if cl_rec is not None:
        if cl_rec.action == "shock" and cl_rec.steps:
            alerts.append(
                f"**Chlor**: Breakpoint-Chlorung — {format_steps_short(cl_rec.steps)}"
            )
        elif cl_rec.action == "raise" and cl_rec.steps:
            alerts.append(
                f"**Chlor**: Routine-Shock — {format_steps_short(cl_rec.steps)}"
            )
        elif cl_rec.action == "lower":
            # FC zu hoch — kein aktiver Eingriff, nur abwarten
            alerts.append(
                "**Chlor**: Abwarten bis FC abklingt — kein aktiver Eingriff möglich."
            )

    # FC/CYA-Verhältnis
    ratio_issue = _fc_cya_ratio_issue(ctx)
    if ratio_issue is not None:
        if ratio_issue["direction"] == "low":
            alerts.append(
                f"**Chlor/CYA**: FC-Ziel an CYA anpassen — Sollwert auf "
                f"~{ratio_issue['fc_suggested']:.2f} mg/l anheben oder CYA senken."
            )
        else:  # high
            alerts.append(
                "**Chlor/CYA**: FC abwarten — Chlor baut sich durch UV und Verbrauch ab."
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
    # CC wird aus FC und TC berechnet — Stale-Status erbt von FC/TC, kein
    # eigener Stale-Key.
    L.append(_row("Chlor geb. (mg/l)", cc_str, "—", "—", f"{ctx.cc_max:.2f}", None))

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
    """User-getriggerte Shock-Szenarien (Breakpoint ist auto-empfohlen wenn nötig
    und erscheint dann als konkrete Dosis in Blau + Note — nicht mehr hier)."""
    L = [
        "| Szenario | FC-Ziel | Dosis | CYA-Anstieg (mg/l) |",
        "|----------|--------:|------:|-------------------:|",
    ]
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


def _bullet(label: str, value: str) -> str:
    return f"- **{label}**: {value}"


def _note_ta_raise(rec: Recommendation, ctx: WorkflowContext) -> str:
    """Format A — TA anheben (Natron, Eimer, während-Dosierung-Pumpe)."""
    lines = [rec.why or "TA zu niedrig."]
    lines.append(_bullet("Dosierung", format_steps_short(rec.steps)))
    lines.append(_bullet("Einfüllung", method_plain(TA_PLUS_BICARB)))
    lines.append(_bullet("Pumpe", "während der Dosierung durchgehend"))
    h = format_total_hours(rec.steps)
    lines.append(_bullet("Messung", f"~{h} h nach der letzten Dosis"))
    return "\n".join(lines)


def _note_ta_lower(rec: Recommendation, ctx: WorkflowContext) -> str:
    """Format C — TA senken (mehrtägiger pH-down + Belüftungs-Prozess)."""
    lines = [rec.why or "TA zu hoch, senken."]
    # Erst-Dosis pH-down berechnen (wenn pH-Wert + Konfig vorhanden)
    ph = ctx.ph_manual if ctx.ph_manual is not None else ctx.ph_auto
    step1 = ""
    if ph is not None and ph > 7.0 and ctx.ph_minus_type and ctx.ph_minus_strength_pct > 0:
        steps = compute_ph_minus_dose(
            current=ph,
            target=7.0,
            volume_m3=ctx.volume_m3,
            ph_minus_type=ctx.ph_minus_type,
            ph_minus_strength_pct=ctx.ph_minus_strength_pct,
            ph_minus_display=ctx.ph_minus_display,
        )
        if steps:
            dose = format_steps_short(steps)
            step1 = (
                f"**pH auf 7.0 dosieren**: bei aktuellem pH {ph:.2f} → {dose}, "
                f"{method_plain(ctx.ph_minus_type)}"
            )
    elif ph is not None and ph <= 7.0:
        step1 = f"**pH ist bereits ≤ 7.0** ({ph:.2f}) — heute kein pH-Down nötig, direkt zu Schritt 2"
    else:
        step1 = (
            "**pH auf 7.0 dosieren**: mit deinem pH-Minus-Produkt gezielt auf ~7.0. "
            "Dosis richtet sich nach aktuellem pH-Wert."
        )
    lines.append(f"1. {step1}")
    lines.append(
        "2. **24 h belüften**: Abdeckung ab, Düsen nach oben / Wasserfall / Luftsprudler, "
        "Filter dauerhaft laufen"
    )
    lines.append(
        "3. **Täglich pH + TA messen**. pH > 7.0 → zurück zu Schritt 1 (Dosis an aktuellen pH anpassen)"
    )
    lines.append(
        "4. **TA ≈ Ziel** erreicht → pH mit pH+ wieder auf Ziel-pH"
    )
    return "\n".join(lines)


def _note_ph_dose(rec: Recommendation, ctx: WorkflowContext) -> str:
    """Format A — pH raise/lower."""
    lines = [rec.why or "pH außerhalb Zielbereich."]
    lines.append(_bullet("Dosierung", format_steps_short(rec.steps)))
    # Produkt-Typ für method_plain: aus dem ersten Step ableitbar, aber einfacher:
    # anhand action direkt wählen
    if rec.action == "lower":
        # pH- (dry_acid oder HCl) — method hängt von ctx.ph_minus_type
        method = method_plain(ctx.ph_minus_type) if ctx.ph_minus_type else ""
    else:
        # pH+ (soda)
        method = method_plain("soda_ash_na2co3")
    if method:
        lines.append(_bullet("Einfüllung", method))
    lines.append(_bullet("Pumpe", "während der Dosierung durchgehend"))
    h = format_total_hours(rec.steps)
    lines.append(_bullet("Messung", f"~{h} h nach der letzten Dosis"))
    return "\n".join(lines)


def _note_cya_raise(rec: Recommendation, ctx: WorkflowContext) -> str:
    """Format A (Socke-Variante) — CYA anheben."""
    lines = [rec.why or "CYA zu niedrig."]
    lines.append(_bullet("Dosierung", format_steps_short(rec.steps)))
    lines.append(_bullet("Einfüllung", "in Skimmer- oder Filter-Socke aufhängen"))
    lines.append(_bullet("Pumpe", "24–48 h durchgehend"))
    lines.append(_bullet("Messung", "nach 3–5 Tagen (Granulat löst sich langsam)"))
    lines.append(
        "Menge enthält 80 % Sicherheitspuffer — CYA baut nicht ab und ist nur durch "
        "Wasserwechsel senkbar, daher lieber zu wenig als zu viel. Bei Bedarf nach der "
        "Messung nachlegen."
    )
    return "\n".join(lines)


def _note_cya_lower(rec: Recommendation, ctx: WorkflowContext) -> str:
    """Format B — CYA senken per Wasserteilwechsel."""
    lines = [rec.why or "CYA zu hoch."]
    if ctx.cya is not None and ctx.cya > ctx.cya_target:
        ex = compute_cya_exchange(
            current=ctx.cya, target=ctx.cya_target, volume_m3=ctx.volume_m3
        )
        lines.append(_bullet(
            "Aktion",
            f"ca. **{ex['percent']:.0f} % Wasser teiltauschen** "
            f"(≈ {ex['liters']:.0f} L bei {ctx.volume_m3:.0f} m³) um auf Ziel "
            f"{ctx.cya_target:.0f} mg/l zu kommen",
        ))
        if ex.get("needs_etappen"):
            lines.append(_bullet(
                "Verteilung", "in 2–3 Etappen über mehrere Tage (> 50 % Austausch)"
            ))
        if ex.get("needs_post_shock"):
            lines.append(_bullet(
                "Nachher",
                "Routine-Shock (Frischwasser bringt FC=0, Dosieranlage braucht Zeit)",
            ))
        lines.append(_bullet("Messung", "nach dem Tausch"))
    else:
        lines.append(_bullet("Aktion", "Messung erneuern, dann Verdünnungs-Menge berechnen"))
    # Langfrist-Hinweis bei critical high
    if rec.is_critical:
        lines.append(
            "Langfristig: häufige Dichlor-Shocks meiden — auf Flüssig-Chlor (NaOCl) oder "
            "Calciumhypochlorit umstellen, um CYA stabil zu halten."
        )
    return "\n".join(lines)


def _note_chlorine(rec: Recommendation, ctx: WorkflowContext) -> str | None:
    """Format A/Watch — Chlor (shock, raise, watch)."""
    if rec.action in ("shock", "raise"):
        # Format A mit shock_type-spezifischer method
        shock_t = ctx.shock_type if rec.action == "shock" else ctx.shock_type  # routine uses same type by default
        lines = [rec.why or "Chlor-Action."]
        lines.append(_bullet("Dosierung", format_steps_short(rec.steps)))
        method = method_plain(shock_t) if shock_t else ""
        if method:
            lines.append(_bullet("Einfüllung", method))
        lines.append(_bullet("Pumpe", "durchgehend während und mindestens 24 h nach der Dosierung"))
        h = format_total_hours(rec.steps)
        if h > 0:
            lines.append(_bullet("Messung", f"~{h} h nach der letzten Dosis, dann FC + CC prüfen"))
        else:
            lines.append(_bullet("Messung", "24–48 h nach der Dosierung, dann FC + CC prüfen"))
        # Zusatz-Hinweis (z.B. CYA-Warnung aus rec.note)
        if rec.note:
            lines.append(rec.note)
        return "\n".join(lines)
    if rec.action == "watch":
        # State B: FC niedrig oder FC hoch oder CC watch — kurzer Hinweis
        # rec.why enthält Erklärung + decay
        if rec.why:
            return rec.why
        return None
    if rec.action == "lower":
        # FC zu hoch, nicht baden
        lines = [rec.why or "FC zu hoch."]
        lines.append(_bullet("Aktion", "abwarten, Abdeckung ab, Pumpe läuft durchgehend"))
        lines.append(_bullet("Dosieranlage", "pausiert automatisch (Redox-Sollwert erreicht)"))
        lines.append(_bullet("Messung", "täglich, bis FC wieder im Zielbereich"))
        return "\n".join(lines)
    return None


def _note_redox_level(ctx: WorkflowContext) -> str | None:
    """Format D — Redox Diagnose bei critical."""
    if ctx.redox is None:
        return None
    if ctx.redox < ctx.redox_critical_low:
        lines = [
            f"Zu niedriger Redox ({ctx.redox:.0f} mV, kritisch < {ctx.redox_critical_low:.0f}) "
            "heißt zu wenig aktives Chlor — entweder liefert die Dosieranlage nicht, oder "
            "die Elektrode driftet und zeigt zu wenig an."
        ]
        lines.append(_bullet(
            "Chlor-Kanister prüfen",
            "leer oder fast leer? → tauschen und Produktionsrate hochstellen",
        ))
        lines.append(_bullet(
            "Produktionsrate erhöhen", "falls noch Reserve da"
        ))
        lines.append(_bullet(
            "Elektrode kalibrieren",
            "mit Prüflösung 468 mV, wenn Kanister ok und Dosierung läuft",
        ))
        lines.append(_bullet(
            "Messung", "nach jedem Schritt ~30 Min warten, dann Redox erneut prüfen"
        ))
        return "\n".join(lines)
    if ctx.redox > ctx.redox_critical_high:
        lines = [
            f"Zu hoher Redox ({ctx.redox:.0f} mV, kritisch > {ctx.redox_critical_high:.0f}) "
            "heißt entweder tatsächliche Chlor-Überdosierung oder Sondendrift. Der FC-Wert "
            "verrät, welcher Fall vorliegt."
        ]
        lines.append(_bullet(
            "FC manuell messen",
            "stimmt hoher FC mit hohem Redox überein? → echte Überdosierung, "
            "Sollwert der Anlage senken oder Produktionsrate reduzieren",
        ))
        lines.append(_bullet(
            "FC normal",
            "Sondendrift — Redox-Elektrode mit Prüflösung 468 mV kalibrieren",
        ))
        lines.append(_bullet(
            "Messung",
            "nach Kalibrierung oder Sollwert-Änderung ~30 Min warten und erneut prüfen",
        ))
        return "\n".join(lines)
    return None


def _note_drift_ph(rec: Recommendation, ctx: WorkflowContext) -> str | None:
    """Format D — pH Sonden-Drift."""
    if rec.action != "calibrate":
        return None
    delta_str = f"{rec.delta:+.2f}" if rec.delta is not None else "?"
    lines = [
        f"Die Anlagen-Elektrode weicht vom manuellen Photometer-Wert um {delta_str} ab "
        f"(Schwelle ±{ctx.ph_calib_threshold:.2f}). Die Anlage dosiert auf Basis ihres "
        "eigenen falschen Messwerts — solange die Drift besteht, reguliert sie nicht mehr "
        "aufs echte Ziel."
    ]
    lines.append(_bullet(
        "Kalibrieren",
        "an der Dosieranlage mit Pufferlösungen pH 7 und pH 4 (2-Punkt-Kalibrierung)",
    ))
    lines.append(_bullet(
        "Zwischenzeitlich",
        "Photometer-Wert als Wahrheit nehmen, Anlage-Sollwert NICHT blind nachführen",
    ))
    lines.append(_bullet(
        "Messung",
        "nach Kalibrierung ~30 Min abwarten, dann pH (Anlage) und pH (manuell) erneut vergleichen",
    ))
    return "\n".join(lines)


def _note_drift_redox(rec: Recommendation, ctx: WorkflowContext) -> str | None:
    """Format D — Redox Sonden-Drift."""
    if rec.action != "calibrate":
        return None
    delta_str = f"{rec.delta:+.0f}" if rec.delta is not None else "?"
    lines = [
        f"Der gemessene Redox weicht vom chemisch erwarteten Wert um {delta_str} mV ab "
        f"(Schwelle ±{ctx.redox_drift_threshold:.0f} mV). Die Elektrode zeigt verzerrt an — "
        "die Anlage regelt auf ein falsches Bild."
    ]
    lines.append(_bullet(
        "Kalibrieren",
        "an der Dosieranlage mit Prüflösung 468 mV (1-Punkt-Kalibrierung)",
    ))
    lines.append(_bullet(
        "Messung",
        "nach Kalibrierung ~30 Min abwarten, dann Redox erneut mit dem berechneten Wert "
        "in der Messwert-Tabelle vergleichen",
    ))
    return "\n".join(lines)


def _measurement_notes(ctx: WorkflowContext, recs: dict[str, Recommendation]) -> list[str]:
    """Dispatcht zu den per-Parameter Note-Composern (Format A/B/C/D).

    Reihenfolge: TA → pH → CYA → Chlor → FC/CYA-Ratio → Redox → Drifts.
    """
    notes: list[str] = []

    def _push(label: str, body: str | None) -> None:
        if body:
            notes.append(f"**{label}**: {body}")

    # TA
    ta_rec = recs.get("alkalinity")
    if ta_rec is not None:
        if ta_rec.action == "raise":
            _push("Alkalität", _note_ta_raise(ta_rec, ctx))
        elif ta_rec.action == "lower":
            _push("Alkalität", _note_ta_lower(ta_rec, ctx))

    # pH (raise/lower mit Dosis; watch hat keine Note)
    ph_rec = recs.get("ph")
    if ph_rec is not None and ph_rec.action in ("raise", "lower") and ph_rec.steps:
        _push("pH", _note_ph_dose(ph_rec, ctx))

    # CYA
    cya_rec = recs.get("cya")
    if cya_rec is not None:
        if cya_rec.action == "raise":
            _push("Cyanursäure", _note_cya_raise(cya_rec, ctx))
        elif cya_rec.action == "lower":
            _push("Cyanursäure", _note_cya_lower(cya_rec, ctx))

    # Chlor
    cl_rec = recs.get("chlorine")
    if cl_rec is not None:
        _push("Chlor", _note_chlorine(cl_rec, ctx))

    # FC/CYA Ratio
    ratio_explain = _fc_cya_ratio_explanation(ctx)
    if ratio_explain:
        notes.append(ratio_explain)

    # Redox Level (critical)
    _push("Redox", _note_redox_level(ctx))

    # Drifts
    cal_rec = recs.get("calibration")
    if cal_rec is not None:
        _push("Drift pH Sonde", _note_drift_ph(cal_rec, ctx))
    dr_rec = recs.get("drift_redox")
    if dr_rec is not None:
        _push("Drift Redox Sonde", _note_drift_redox(dr_rec, ctx))

    return notes


def _fc_cya_ratio_explanation(ctx: WorkflowContext) -> str | None:
    """Strukturierte Note unter der Tabelle bei FC/CYA-Ratio-Auffälligkeit."""
    issue = _fc_cya_ratio_issue(ctx)
    if issue is None:
        return None
    if issue["direction"] == "low":
        lines = [
            "**FC/CYA-Verhältnis**: Chlor wird durch CYA reversibel gebunden — bei zu viel "
            "CYA pro FC reicht die aktive HOCl-Fraktion nicht mehr zum Keime-Töten.",
            _bullet(
                "Ziel",
                f"FC ≥ CYA × {FC_CYA_RATIO_MIN:.2f} = "
                f"{issue['fc_suggested']:.2f} mg/l bei CYA {ctx.cya:.0f}",
            ),
            _bullet(
                "Option 1",
                "Dosieranlagen-Sollwert (Redox oder FC) anheben, bis FC im Zielbereich",
            ),
            _bullet(
                "Option 2", "CYA senken per Wasserteilwechsel (dauerhafter)"
            ),
            _bullet(
                "Messung", "nach Anpassung 24 h abwarten, dann FC manuell prüfen"
            ),
        ]
        return "\n".join(lines)
    # direction == "high"
    lines = [
        "**FC/CYA-Verhältnis**: FC deutlich über Komfort-Obergrenze (SLAM-Niveau) — "
        "kurzfristig nicht gefährlich, aber Reizung möglich.",
        _bullet(
            "Komfort-Obergrenze",
            f"FC ≤ CYA × {FC_CYA_RATIO_HIGH:.2f} = "
            f"{issue['fc_suggested']:.2f} mg/l bei CYA {ctx.cya:.0f}",
        ),
        _bullet("Aktion", "abwarten bis FC durch UV und Verbrauch abklingt"),
        _bullet(
            "Dosieranlage",
            "pausiert meist automatisch, sonst Sollwert kurz reduzieren",
        ),
        _bullet(
            "Wiederholung",
            "wenn öfter auftretend, FC-Target oder CYA überprüfen",
        ),
    ]
    return "\n".join(lines)


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

    # Banner: Status + Action in einem. Reihenfolge rot → gelb → blau,
    # innerhalb je Chemie-Priorität (TA → pH → CYA → Chlor → Ratio → Redox
    # → Drifts → Stale).
    banners = _build_banners(ctx, recs)
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    banners.sort(key=lambda sb: severity_order.get(sb[0], 99))
    alert_type = {"critical": "error", "warning": "warning", "info": "info"}
    for severity, text in banners:
        lines.append(f'<ha-alert alert-type="{alert_type[severity]}">{text}</ha-alert>')
        lines.append("")

    # 2. Messwerte-Tabelle
    lines.append("---")
    lines.append("")
    lines.append(f"**Messwerte** ({ctx.volume_m3:.0f} m³):")
    lines.append("")
    lines += _values_table(ctx, recs)

    # Hinweise unter der Messwerte-Tabelle (Multi-Line Blockquote)
    notes_below = list(_measurement_notes(ctx, recs))
    for n in notes_below:
        for line in n.split("\n"):
            lines.append(f"> {line}")
        lines.append(">")
    if notes_below:
        lines.append("")

    # 3. Shock-Szenarien-Tabelle — manuelle Szenarien (Algen, präventiv).
    # Auto-empfohlene Shocks (Breakpoint, Routine bei FC-krit-low) stehen
    # bereits als konkrete Dosis in Blau + Note.
    lines.append("---")
    lines.append("")
    lines.append("**Shock-Szenarien bei Bedarf** (user-getriggert, z.B. Algen oder Saisonstart):")
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
