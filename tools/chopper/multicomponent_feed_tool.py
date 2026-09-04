"""
Single stateful intake-and-calculate tool for the multicomponent
distillation feed-phase agent.

See tools/multicomponent-distillation-feed-phase-plan.md "3. One
intake-and-calculate tool" and the "Output Boundary" section of
tools/multicomponent-distillation-context.md: this tool accepts partial
feed-specification updates across however many turns it takes, returns
one deterministic `pending_request` while information is missing, and --
once the accumulated feed is complete -- automatically runs the
deterministic VLE calculation and reports ONLY the equilibrium phase and
molar vapor/liquid fractions. It never routes the feed, selects a
separation, or performs any distillation design.

No LLM calls -- this module must never import `ollama` or `openai`.
"""
from multicomponent_feed_phase import calculate_multicomponent_feed_phase
from multicomponent_feed_state import (
    MIN_COMPONENTS,
    apply_user_update,
    assess_feed_state,
    empty_feed_state,
)
from multicomponent_units import (
    SUPPORTED_ENTHALPY_UNITS,
    SUPPORTED_FLOW_UNITS,
    SUPPORTED_PRESSURE_UNITS,
    SUPPORTED_TEMPERATURE_UNITS,
)

# Accumulated feed state for the CURRENT multicomponent feed problem, across
# however many tool calls it takes to fully specify it. A tool-calling model
# cannot be relied on to restate every already-known field on every
# follow-up call, so every call MERGES what it's given into this state and
# the checker runs against the accumulated state, not just the current
# call's arguments.
_feed_state = empty_feed_state()

# tools/multicomponent-distillation-feed-phase-plan.md "3. One
# intake-and-calculate tool" -- one deterministic question (plus, where
# applicable, the fixed list of supported units/choices) per missing-input
# identifier. Built entirely from the fixed unit registry -- never invents
# a unit list.
_PENDING_REQUESTS = {
    'component_names': {
        'field': 'component_names',
        'question': (
            f'Which components are in the feed? At least {MIN_COMPONENTS} '
            'are required.'
        ),
    },
    'feed_quantity': {
        'field': 'component_flows_or_total_flow_and_composition',
        'question': (
            'What is the feed quantity and composition? Give either a '
            'flow rate for every component, or the total feed flow rate '
            'plus fractions for all but one component.'
        ),
    },
    'composition_basis': {
        'field': 'composition_basis',
        'question': 'Is the given composition on a mole or mass basis?',
        'choices': ['mole', 'mass'],
    },
    'flow_units': {
        'field': 'component_flow_units_or_total_flow_units',
        'question': 'What are the units of the feed flow rate?',
        'choices': list(SUPPORTED_FLOW_UNITS),
    },
    'pressure_value': {
        'field': 'pressure',
        'question': 'What is the feed pressure?',
    },
    'pressure_units': {
        'field': 'pressure_units',
        'question': 'What are the units of the feed pressure?',
        'choices': list(SUPPORTED_PRESSURE_UNITS),
    },
    'feed_thermal_condition': {
        'field': 'feed_temperature_or_feed_enthalpy_or_feed_quality',
        'question': (
            'What is the feed thermal condition? Give exactly one of: '
            'temperature, enthalpy, or quality. Never assume the bubble '
            'point.'
        ),
    },
    'feed_temperature_units': {
        'field': 'feed_temperature_units',
        'question': 'What are the units of the feed temperature?',
        'choices': list(SUPPORTED_TEMPERATURE_UNITS),
    },
    'feed_enthalpy_units': {
        'field': 'feed_enthalpy_units',
        'question': 'What are the units of the feed enthalpy?',
        'choices': list(SUPPORTED_ENTHALPY_UNITS),
    },
}


def _pending_request_for(missing_field):
    return _PENDING_REQUESTS.get(missing_field, {
        'field': missing_field,
        'question': f'Please provide {missing_field}.',
    })


def reset_multicomponent_feed_session() -> dict:
    """Clear all previously-remembered inputs for the current multicomponent feed-phase problem, so the next call starts a fresh, unrelated feed from scratch.

    Call this ONLY when the user is clearly switching to a different feed (different components, or they explicitly say to start over) -- not between follow-up turns still refining the same feed.

    Returns:
        {'reset': True, 'message': str} confirming the accumulated state was cleared.
    """
    global _feed_state
    _feed_state = empty_feed_state()
    return {'reset': True, 'message': 'All previously remembered feed inputs have been cleared.'}


def update_multicomponent_feed(
    component_names: list[str] | None = None,
    add_component_names: list[str] | None = None,
    component_flows: dict[str, float] | None = None,
    component_flow_units: str | None = None,
    total_flow: float | None = None,
    total_flow_units: str | None = None,
    composition: dict[str, float] | None = None,
    composition_basis: str | None = None,
    pressure: float | None = None,
    pressure_units: str | None = None,
    feed_temperature: float | None = None,
    feed_temperature_units: str | None = None,
    feed_enthalpy: float | None = None,
    feed_enthalpy_units: str | None = None,
    feed_quality: float | None = None,
) -> dict:
    """WRITE-and-calculate operation for a multicomponent (>=3 component) feed-phase problem. Merges newly-stated facts into the accumulated feed state, then either returns exactly one pending_request naming the next genuinely missing input, or -- once the feed is fully specified -- automatically runs the deterministic BioSTEAM VLE calculation and returns ONLY the equilibrium phase and molar vapor/liquid fractions.

    Call this ONLY when the current user message states new feed information. This tool REMEMBERS every field given so far in this conversation about the current feed -- do not repeat components, quantities, pressure, or thermal condition already established; just pass whatever is new. Call reset_multicomponent_feed_session() only when the user switches to a genuinely different feed.

    Never invent a value for any argument the user has not stated. In particular: never assume the feed thermal condition (temperature/enthalpy/quality) or default it to the bubble point; never guess a composition basis (mole vs mass); never guess a unit; never invent a missing component.

    Args:
        component_names: The FULL, current list of component names (>= 3), e.g. ["Water", "Ethanol", "Methanol"]. Replaces any previously-known list and clears any previously-known flows/composition (they described the old feed). Do not populate this with invented numbers -- just the names.
        add_component_names: Component name(s) to ADD to the already-established list without touching known quantities -- use when the user answers "please name the third component" with just a bare name.
        component_flows: Per-component flow rates actually stated this turn, e.g. {"Water": 30, "Ethanol": 40}. Give only what was actually stated -- never infer a value for a component not named.
        component_flow_units: Units for component_flows -- one of "kmol/hr", "mol/hr", "kg/hr". Pass it in the same call as component_flows whenever the user states both together.
        total_flow: The TOTAL feed flow rate, ONLY if the user explicitly described it as the total feed -- never set this from a single component's stated flow rate.
        total_flow_units: Units for total_flow -- one of "kmol/hr", "mol/hr", "kg/hr".
        composition: Mole or mass fraction(s) actually stated this turn, e.g. {"Water": 0.5}. Give only what was stated -- never compute or guess the remaining fraction(s) yourself.
        composition_basis: "mole" or "mass" -- required whenever composition is used; never guess this even if it seems obvious.
        pressure: Feed pressure value.
        pressure_units: Units for pressure -- one of "Pa", "kPa", "bar", "atm".
        feed_temperature: Feed temperature value. Give at most one of feed_temperature/feed_enthalpy/feed_quality -- never assume the feed is at its bubble point.
        feed_temperature_units: Units for feed_temperature -- one of "K", "degC".
        feed_enthalpy: Total feed stream enthalpy value. Alternative to feed_temperature/feed_quality.
        feed_enthalpy_units: Units for feed_enthalpy -- only "kJ/hr" is supported.
        feed_quality: Feed vapor fraction/quality, 0 to 1 (0 = saturated liquid, 1 = saturated vapor). Alternative to feed_temperature/feed_enthalpy.

    Returns:
        While information is still missing or invalid: {'complete': False, 'valid': bool, 'pending_request': {'field', 'question', 'choices'?} or None, 'conflicts': [...], 'validation_errors': [...], 'message': str}. Relay pending_request['question'] (and 'choices' if present) to the user verbatim or with only minor wording changes -- never invent a different missing field, and never ask for something not named in pending_request.
        Once complete: {'complete': True, 'valid': True, 'phase': 'liquid'|'vapor'|'vapor_liquid', 'vapor_fraction': float, 'liquid_fraction': float, 'message': str}. Report ONLY the phase and the two fractions -- never route the feed, select a separation, or perform any distillation design from this result.
        If the calculation itself fails once the feed looked complete (e.g. BioSTEAM does not recognize a stated component name): {'complete': False, 'valid': False, 'error': str, 'message': str}.
    """
    global _feed_state

    new_fields = dict(
        component_names=component_names, add_component_names=add_component_names,
        component_flows=component_flows, component_flow_units=component_flow_units,
        total_flow=total_flow, total_flow_units=total_flow_units,
        composition=composition, composition_basis=composition_basis,
        pressure=pressure, pressure_units=pressure_units,
        feed_temperature=feed_temperature, feed_temperature_units=feed_temperature_units,
        feed_enthalpy=feed_enthalpy, feed_enthalpy_units=feed_enthalpy_units,
        feed_quality=feed_quality,
    )
    _feed_state = apply_user_update(_feed_state, new_fields)

    assessment = assess_feed_state(_feed_state)
    _feed_state = assessment['state']

    if assessment['conflicts']:
        return {
            'complete': False, 'valid': False, 'pending_request': None,
            'conflicts': assessment['conflicts'], 'validation_errors': [],
            'message': (
                'Conflicting feed information was given: '
                + ' '.join(assessment['conflicts'])
            ),
        }

    if assessment['validation_errors']:
        return {
            'complete': False, 'valid': False, 'pending_request': None,
            'conflicts': [], 'validation_errors': assessment['validation_errors'],
            'message': (
                'The feed information given is invalid: '
                + ' '.join(assessment['validation_errors'])
            ),
        }

    if not assessment['ready']:
        missing = assessment['missing_inputs']
        pending = _pending_request_for(missing[0]) if missing else None
        return {
            'complete': False, 'valid': True, 'pending_request': pending,
            'conflicts': [], 'validation_errors': [],
            'message': pending['question'] if pending else 'More information is needed.',
        }

    result = calculate_multicomponent_feed_phase(_feed_state)
    if not result.get('valid'):
        return {
            'complete': False, 'valid': False,
            'error': result.get('error'), 'message': result.get('message'),
        }

    return {
        'complete': True, 'valid': True,
        'phase': result['phase'],
        'vapor_fraction': result['vapor_fraction'],
        'liquid_fraction': result['liquid_fraction'],
        'message': result['message'],
    }


TOOLS = [update_multicomponent_feed, reset_multicomponent_feed_session]
TOOL_FUNCTIONS = {
    'update_multicomponent_feed': update_multicomponent_feed,
    'reset_multicomponent_feed_session': reset_multicomponent_feed_session,
}
