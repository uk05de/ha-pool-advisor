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
CONF_MANUAL_MAX_AGE_H: Final = "manual_max_age_hours"
DEFAULT_PH_CALIB_THRESHOLD = 0.2
DEFAULT_MANUAL_MAX_AGE_H = 24

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
CONF_CC_SHOCK_AT: Final = "cc_shock_at"

CONF_REDOX_MIN: Final = "redox_min"
CONF_REDOX_MAX: Final = "redox_max"
CONF_REDOX_TARGET: Final = "redox_target"

# Critical thresholds (outside which active intervention is recommended;
# between normal min/max and critical the advisor only says "beobachten")
CONF_PH_CRITICAL_LOW: Final = "ph_critical_low"
CONF_PH_CRITICAL_HIGH: Final = "ph_critical_high"
CONF_TA_CRITICAL_LOW: Final = "ta_critical_low"
CONF_TA_CRITICAL_HIGH: Final = "ta_critical_high"
CONF_FC_CRITICAL_LOW: Final = "fc_critical_low"

DEFAULT_PH_CRITICAL_LOW = 6.8
DEFAULT_PH_CRITICAL_HIGH = 7.7
DEFAULT_TA_CRITICAL_LOW = 60.0
DEFAULT_TA_CRITICAL_HIGH = 150.0
DEFAULT_FC_CRITICAL_LOW = 0.2

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
CONF_CYA_TARGET: Final = "cya_target"
CONF_CYA_WATCH_AT: Final = "cya_watch_at"
CONF_CYA_CRITICAL_AT: Final = "cya_critical_at"
DEFAULT_CYA_TARGET: Final = 30.0
DEFAULT_CYA_WATCH_AT: Final = 50.0
DEFAULT_CYA_CRITICAL_AT: Final = 75.0

# Workflow / maintenance mode
CONF_WARTUNGSMODUS: Final = "wartungsmodus"
CONF_WORKFLOW_STEP: Final = "workflow_step"

MODE_NORMAL: Final = "normal"
MODE_SHOCK_ROUTINE: Final = "shock_routine"
MODE_SHOCK_ALGEN_LEICHT: Final = "shock_algen_leicht"
MODE_SHOCK_ALGEN_STARK: Final = "shock_algen_stark"
MODE_SHOCK_SCHWARZALGEN: Final = "shock_schwarzalgen"
MODE_SHOCK_BREAKPOINT: Final = "shock_breakpoint"
MODE_FRISCHWASSER: Final = "frischwasser"
MODE_SAISONSTART: Final = "saisonstart"

WARTUNGSMODI: Final = [
    MODE_NORMAL,
    MODE_SHOCK_ROUTINE,
    MODE_SHOCK_ALGEN_LEICHT,
    MODE_SHOCK_ALGEN_STARK,
    MODE_SHOCK_SCHWARZALGEN,
    MODE_SHOCK_BREAKPOINT,
    MODE_FRISCHWASSER,
    MODE_SAISONSTART,
]

# Shock FC targets per scenario (mg/l absolute)
SHOCK_FC_TARGETS: Final = {
    MODE_SHOCK_ROUTINE: 10.0,
    MODE_SHOCK_ALGEN_LEICHT: 15.0,
    MODE_SHOCK_ALGEN_STARK: 20.0,
    MODE_SHOCK_SCHWARZALGEN: 25.0,
}

# Storage version for persistent workflow state
STORAGE_VERSION: Final = 1
STORAGE_KEY_WORKFLOW: Final = f"{DOMAIN}.workflow"

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

# Dose splitting
CONF_MAX_DOSE_FRACTION: Final = "max_dose_fraction"
CONF_DOSE_INTERVAL_H: Final = "dose_interval_hours"

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

DEFAULT_FC_TARGET_SALT = 0.5
DEFAULT_FC_MIN_SALT = 0.3
DEFAULT_FC_MAX_SALT = 0.8

DEFAULT_FC_TARGET_CLASSIC = 1.0
DEFAULT_FC_MIN_CLASSIC = 0.5
DEFAULT_FC_MAX_CLASSIC = 1.5

DEFAULT_CC_MAX = 0.2
DEFAULT_CC_SHOCK_AT = 0.5

DEFAULT_REDOX_TARGET = 700
DEFAULT_REDOX_MIN = 650
DEFAULT_REDOX_MAX = 750

DEFAULT_MAX_DOSE_FRACTION = 0.5
DEFAULT_DOSE_INTERVAL_H = 6

# --- Signals / events ---
SIGNAL_UPDATE = f"{DOMAIN}_update"
