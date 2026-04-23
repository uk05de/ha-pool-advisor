"""Constants for Pool Chemistry Advisor."""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "pool_advisor"

# --- Config keys ---
CONF_NAME: Final = "name"
CONF_POOL_VOLUME_M3: Final = "pool_volume_m3"
CONF_CHLORINATION: Final = "chlorination_type"
CONF_PH_DOSING: Final = "ph_dosing_capability"

PH_DOSING_NONE: Final = "none"
PH_DOSING_MINUS: Final = "minus_only"
PH_DOSING_PLUS: Final = "plus_only"
PH_DOSING_BOTH: Final = "both"
PH_DOSING_CHOICES: Final = [
    PH_DOSING_NONE,
    PH_DOSING_MINUS,
    PH_DOSING_PLUS,
    PH_DOSING_BOTH,
]
DEFAULT_PH_DOSING: Final = PH_DOSING_MINUS

# Input entities — automatic (continuous dosing system, e.g. Bayrol)
CONF_ENT_PH_AUTO: Final = "entity_ph_auto"
CONF_ENT_REDOX: Final = "entity_redox"
CONF_ENT_TEMPERATURE: Final = "entity_temperature"

# Input entities — manual (spot checks, e.g. PoolLab)
CONF_ENT_PH_MANUAL: Final = "entity_ph_manual"
CONF_ENT_ALKALINITY: Final = "entity_alkalinity"
CONF_ENT_FREE_CL: Final = "entity_free_chlorine"
CONF_ENT_COMBINED_CL: Final = "entity_combined_chlorine"
CONF_ENT_TOTAL_CL: Final = "entity_total_chlorine"
CONF_ENT_CYANURIC: Final = "entity_cyanuric_acid"

# Calibration
CONF_PH_CALIB_THRESHOLD: Final = "ph_calibration_threshold"
DEFAULT_PH_CALIB_THRESHOLD = 0.2

# Stale-Schwellen je Parameter (in Tagen). Realistischer Rhythmus basierend
# auf Pool-Chemie-Dynamik:
#   CYA  — stabil, baut nicht ab, Änderung nur durch Wasseraustausch
#   TA   — stabil, sinkt leicht über Monate
#   pH   — Drift-Check der Anlage-Elektrode
#   FC/CC/TC — dynamisch aber Anlage regelt autonom; Messung bei Anlass
CONF_STALE_TA_DAYS: Final = "stale_ta_days"
CONF_STALE_PH_MANUAL_DAYS: Final = "stale_ph_manual_days"
CONF_STALE_FC_DAYS: Final = "stale_fc_days"
CONF_STALE_CYA_DAYS: Final = "stale_cya_days"
DEFAULT_STALE_TA_DAYS: Final = 28
DEFAULT_STALE_PH_MANUAL_DAYS: Final = 14
DEFAULT_STALE_FC_DAYS: Final = 14
DEFAULT_STALE_CYA_DAYS: Final = 56

# Targets
CONF_PH_MIN: Final = "ph_min"
CONF_PH_MAX: Final = "ph_max"
CONF_PH_TARGET: Final = "ph_target"

CONF_TA_MIN: Final = "ta_min"
CONF_TA_MAX: Final = "ta_max"
CONF_TA_TARGET: Final = "ta_target"

CONF_FC_MIN: Final = "fc_min"
CONF_FC_MAX: Final = "fc_max"
CONF_FC_TARGET: Final = "fc_target"

CONF_CC_MAX: Final = "cc_max"
CONF_CC_CRITICAL_HIGH: Final = "cc_critical_high"

CONF_REDOX_MIN: Final = "redox_min"
CONF_REDOX_MAX: Final = "redox_max"
CONF_REDOX_TARGET: Final = "redox_target"
CONF_REDOX_CRITICAL_LOW: Final = "redox_critical_low"
CONF_REDOX_CRITICAL_HIGH: Final = "redox_critical_high"

# Critical thresholds (outside which active intervention is recommended;
# between normal min/max and critical the advisor only says "beobachten")
CONF_PH_CRITICAL_LOW: Final = "ph_critical_low"
CONF_PH_CRITICAL_HIGH: Final = "ph_critical_high"
CONF_TA_CRITICAL_LOW: Final = "ta_critical_low"
CONF_TA_CRITICAL_HIGH: Final = "ta_critical_high"
CONF_FC_CRITICAL_LOW: Final = "fc_critical_low"
CONF_FC_CRITICAL_HIGH: Final = "fc_critical_high"

DEFAULT_PH_CRITICAL_LOW = 6.8
DEFAULT_PH_CRITICAL_HIGH = 7.7
DEFAULT_TA_CRITICAL_LOW = 60.0
DEFAULT_TA_CRITICAL_HIGH = 150.0
DEFAULT_FC_CRITICAL_LOW = 0.5
DEFAULT_FC_CRITICAL_HIGH = 10.0

# FC/CYA-Verhältnis-Schwellen (TFP-Guideline, chemie-hart)
# Zu niedrig: Chlor wird von CYA gebunden, Sanitation leidet
# Zu hoch (Richtung SLAM-Level): Reizung relativ zum CYA-Puffer
FC_CYA_RATIO_MIN: Final = 0.05
FC_CYA_RATIO_HIGH: Final = 0.40

# Chemicals
CONF_PH_MINUS_TYPE: Final = "ph_minus_type"
CONF_PH_MINUS_STRENGTH: Final = "ph_minus_strength"
CONF_PH_MINUS_NAME: Final = "ph_minus_name"
CONF_PH_PLUS_TYPE: Final = "ph_plus_type"
CONF_PH_PLUS_STRENGTH: Final = "ph_plus_strength"
CONF_PH_PLUS_NAME: Final = "ph_plus_name"
CONF_TA_PLUS_TYPE: Final = "ta_plus_type"
CONF_TA_PLUS_STRENGTH: Final = "ta_plus_strength"
CONF_TA_PLUS_NAME: Final = "ta_plus_name"
CONF_ROUTINE_CL_TYPE: Final = "routine_cl_type"
CONF_ROUTINE_CL_STRENGTH: Final = "routine_cl_strength"
CONF_ROUTINE_CL_NAME: Final = "routine_cl_name"
CONF_SHOCK_TYPE: Final = "shock_type"
CONF_SHOCK_STRENGTH: Final = "shock_strength"
CONF_SHOCK_NAME: Final = "shock_name"

# Pure cyanuric acid product (separate from shock product that may also bring CYA)
CONF_CYA_TYPE: Final = "cya_type"
CONF_CYA_STRENGTH: Final = "cya_strength"
CONF_CYA_NAME: Final = "cya_name"

CYA_PURE: Final = "cyanuric_acid"
CYA_CHOICES: Final = [CYA_PURE]
DEFAULT_CYA_STRENGTH: Final = 99.0

# CYA targets & warning thresholds
CONF_CYA_MIN: Final = "cya_min"
CONF_CYA_TARGET: Final = "cya_target"
CONF_CYA_MAX: Final = "cya_max"
CONF_CYA_CRITICAL_LOW: Final = "cya_critical_low"
CONF_CYA_CRITICAL_HIGH: Final = "cya_critical_high"
DEFAULT_CYA_MIN: Final = 20.0
DEFAULT_CYA_TARGET: Final = 30.0
DEFAULT_CYA_MAX: Final = 50.0
DEFAULT_CYA_CRITICAL_LOW: Final = 0.0  # 0 = "never critical low" — user kann's erhöhen
DEFAULT_CYA_CRITICAL_HIGH: Final = 75.0

# Shock-FC-Zielwerte je Szenario (mg/l absolut)
SHOCK_TARGET_ROUTINE: Final = 10.0
SHOCK_TARGET_ALGEN_LEICHT: Final = 15.0
SHOCK_TARGET_ALGEN_STARK: Final = 20.0
SHOCK_TARGET_SCHWARZALGEN: Final = 25.0

# Redox drift — plausibility check based on FC + pH + CYA
CONF_REDOX_DRIFT_THRESHOLD: Final = "redox_drift_threshold"
DEFAULT_REDOX_DRIFT_THRESHOLD: Final = 70.0  # mV

# --- Test mode ---
CONF_TEST_MODE: Final = "test_mode"
CONF_TEST_PH_AUTO: Final = "test_ph_auto"
CONF_TEST_PH_MANUAL: Final = "test_ph_manual"
CONF_TEST_REDOX: Final = "test_redox"
CONF_TEST_TEMPERATURE: Final = "test_temperature"
CONF_TEST_ALKALINITY: Final = "test_alkalinity"
CONF_TEST_FREE_CL: Final = "test_free_chlorine"
CONF_TEST_COMBINED_CL: Final = "test_combined_chlorine"
CONF_TEST_TOTAL_CL: Final = "test_total_chlorine"
CONF_TEST_CYANURIC: Final = "test_cyanuric_acid"

TEST_VALUE_MAP: Final = {
    CONF_ENT_PH_AUTO: CONF_TEST_PH_AUTO,
    CONF_ENT_PH_MANUAL: CONF_TEST_PH_MANUAL,
    CONF_ENT_REDOX: CONF_TEST_REDOX,
    CONF_ENT_TEMPERATURE: CONF_TEST_TEMPERATURE,
    CONF_ENT_ALKALINITY: CONF_TEST_ALKALINITY,
    CONF_ENT_FREE_CL: CONF_TEST_FREE_CL,
    CONF_ENT_COMBINED_CL: CONF_TEST_COMBINED_CL,
    CONF_ENT_TOTAL_CL: CONF_TEST_TOTAL_CL,
    CONF_ENT_CYANURIC: CONF_TEST_CYANURIC,
}

# Human-friendly fallback labels when user hasn't set a product name.
PRODUCT_LABELS: Final = {
    "dry_acid_nahso4": "Trockensäure (NaHSO₄)",
    "muriatic_acid_hcl": "Salzsäure (HCl)",
    "soda_ash_na2co3": "Soda (Na₂CO₃)",
    "sodium_bicarbonate_nahco3": "Natron (NaHCO₃)",
    "dichlor": "Dichlor-Granulat",
    "calcium_hypochlorite": "Kalziumhypochlorit",
    "sodium_hypochlorite": "Flüssig-Chlor (NaOCl)",
    "cyanuric_acid": "Cyanursäure (Stabilisator)",
}

# --- Choice values ---
CHLORINATION_SALT: Final = "salt_electrolysis"
CHLORINATION_CLASSIC: Final = "classic"
CHLORINATION_CHOICES: Final = [CHLORINATION_SALT, CHLORINATION_CLASSIC]

PH_MINUS_DRY_ACID: Final = "dry_acid_nahso4"     # Natriumhydrogensulfat
PH_MINUS_HCL: Final = "muriatic_acid_hcl"         # Salzsäure (flüssig)
PH_MINUS_CHOICES: Final = [PH_MINUS_DRY_ACID, PH_MINUS_HCL]

PH_PLUS_SODA: Final = "soda_ash_na2co3"           # Soda
PH_PLUS_CHOICES: Final = [PH_PLUS_SODA]

TA_PLUS_BICARB: Final = "sodium_bicarbonate_nahco3"
TA_PLUS_CHOICES: Final = [TA_PLUS_BICARB]

SHOCK_DICHLOR: Final = "dichlor"                  # ~56% active Cl, brings CYA
SHOCK_CAL_HYPO: Final = "calcium_hypochlorite"    # ~65% active Cl, brings calcium
SHOCK_NAOCL_LIQUID: Final = "sodium_hypochlorite" # ~13% active Cl (liquid), neutral
SHOCK_CHOICES: Final = [SHOCK_DICHLOR, SHOCK_CAL_HYPO, SHOCK_NAOCL_LIQUID]

# Shock products that add cyanuric acid (stabilizer) as a side-effect.
SHOCK_STABILIZED: Final = frozenset({SHOCK_DICHLOR})
# Approx. CYA added per 1 mg/l free Cl dosed, for each stabilized type.
SHOCK_CYA_PER_PPM_CL: Final = {SHOCK_DICHLOR: 0.9}

# --- Defaults (percent active for the product itself) ---
DEFAULT_STRENGTH = {
    PH_MINUS_DRY_ACID: 95.0,
    PH_MINUS_HCL: 33.0,
    PH_PLUS_SODA: 99.0,
    TA_PLUS_BICARB: 99.0,
    SHOCK_DICHLOR: 56.0,
    SHOCK_CAL_HYPO: 65.0,
    SHOCK_NAOCL_LIQUID: 13.0,
}

# --- Target defaults ---
DEFAULT_PH_TARGET = 7.2
DEFAULT_PH_MIN = 7.0
DEFAULT_PH_MAX = 7.4

DEFAULT_TA_TARGET = 100.0
DEFAULT_TA_MIN = 80.0
DEFAULT_TA_MAX = 120.0

# FC-Defaults nach TFP-Faustregel bei Referenz-CYA 30 mg/l:
#   min = CYA × 0.05 = 1.5, target = CYA × 0.075 = 2.25, max = CYA × 0.15 = 4.5
# System überschreibt diese Werte dynamisch bei anderem CYA (nach oben),
# daher sind sie der "Boden" für Pools mit niedrigem/ohne CYA.
DEFAULT_FC_MIN = 1.5
DEFAULT_FC_TARGET = 2.25
DEFAULT_FC_MAX = 4.5

# Alte Salt/Classic-Defaults — bleiben als Aliases für Rückwärtskompatibilität
# mit bestehender config_flow-Logik. Neuer Code nutzt DEFAULT_FC_* (oben).
DEFAULT_FC_TARGET_SALT = DEFAULT_FC_TARGET
DEFAULT_FC_MIN_SALT = DEFAULT_FC_MIN
DEFAULT_FC_MAX_SALT = DEFAULT_FC_MAX

DEFAULT_FC_TARGET_CLASSIC = DEFAULT_FC_TARGET
DEFAULT_FC_MIN_CLASSIC = DEFAULT_FC_MIN
DEFAULT_FC_MAX_CLASSIC = DEFAULT_FC_MAX

DEFAULT_CC_MAX = 0.2
DEFAULT_CC_CRITICAL_HIGH = 0.5

DEFAULT_REDOX_TARGET = 700
DEFAULT_REDOX_MIN = 650
DEFAULT_REDOX_MAX = 750
DEFAULT_REDOX_CRITICAL_LOW = 600
DEFAULT_REDOX_CRITICAL_HIGH = 800

# --- Signals / events ---
SIGNAL_UPDATE = f"{DOMAIN}_update"
