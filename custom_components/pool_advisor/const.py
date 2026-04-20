"""Constants for Pool Chemistry Advisor."""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "pool_advisor"

# --- Config keys ---
CONF_NAME: Final = "name"
CONF_POOL_VOLUME_M3: Final = "pool_volume_m3"
CONF_CHLORINATION: Final = "chlorination_type"

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

# Chemicals
CONF_PH_MINUS_TYPE: Final = "ph_minus_type"
CONF_PH_MINUS_STRENGTH: Final = "ph_minus_strength"
CONF_PH_PLUS_TYPE: Final = "ph_plus_type"
CONF_PH_PLUS_STRENGTH: Final = "ph_plus_strength"
CONF_TA_PLUS_TYPE: Final = "ta_plus_type"
CONF_TA_PLUS_STRENGTH: Final = "ta_plus_strength"
CONF_SHOCK_TYPE: Final = "shock_type"
CONF_SHOCK_STRENGTH: Final = "shock_strength"

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
