"""
Feed-state entry points for the multicomponent (>=3 component)
distillation feed-phase agent.

See tools/multicomponent-distillation-dialogue-robustness-plan.md, point 3
("Strict layering"): every function here takes only a `feed_state` plus
already-checked, plain structured facts -- never a raw user message, a
model proposal, an `intent`, or a `target_field`. All message-text
interpretation (binding a pending reply, grounding evidence, verifying a
read-only query's target field) happens in the conversation layer
(`multicomponent_distillation_agent.py` / `multicomponent_dialogue.py` /
`multicomponent_grounding.py`) *before* this module is ever called, and
that layer is also the only place that turns this module's plain-data
results into user-facing text -- no formatted question/message strings are
constructed here.

No LLM calls -- this module must never import `ollama` or `openai`.
"""
import copy

from multicomponent_boiling_point import calculate_multicomponent_boiling_point_order
from multicomponent_critical_temperature import evaluate_critical_temperatures
from multicomponent_feed_state import (
    MIN_COMPONENTS,
    assess_candidate_transition,
    assess_feed_state,
    empty_feed_state,
    record_unit,
    record_value,
)
from multicomponent_relative_volatility import calculate_adjacent_relative_volatilities
from multicomponent_shortcut_train import design_direct_shortcut_train
from multicomponent_units import temperature_to_K


def get_known_component_names(feed_state) -> list[str]:
    """The feed's current component identities -- read-only, used by
    `multicomponent_grounding.ground_proposed_update` so a follow-up
    answer isn't required to re-state names already on record."""
    return list(feed_state['component_names'])


def advance_feed_state(feed_state, checked_facts, turn_number=None, evidence=None):
    """
    Apply already-checked facts to `feed_state` via a transactional
    candidate/commit (Section 8), then run the deterministic boiling-point
    ordering and ideal-liquid relative-volatility calculation if the
    resulting feed is complete.

    Parameters
    ----------
    feed_state : dict
        The session's current committed feed state.
    checked_facts : dict
        Plain field values the conversation layer has already bound and
        grounded -- the same shape `apply_user_update` accepts.
    turn_number, evidence :
        Passed straight through to `assess_candidate_transition` for
        provenance stamping.

    Returns
    -------
    dict with keys:
        'feed_state'        : the new committed state (unchanged from the
                               input if nothing was accepted).
        'accepted_groups' / 'rejected_groups' : from the transaction.
        'complete'           : bool.
        'valid'              : bool.
        'conflicts' / 'validation_errors'      : list[dict] -- empty unless
                               a rejected group has issues to report.
        'missing_field'      : the first `missing_inputs()` identifier, or
                               None once ready or complete -- a raw
                               identifier, NOT a formatted question; the
                               conversation layer turns this into user-
                               facing text via
                               `multicomponent_dialogue.pending_request_for`.
        'boiling_point_order' : only when complete -- the internal full
                               `calculate_multicomponent_boiling_point_order`
                               result dict (order, per-component values,
                               ties, property source, reference pressure).
        'product_specification': the current default assumption that every
                               component is required as an individual product.
        'critical_temperature_check': every component Tc and any component
                               for which the feed temperature exceeds Tc.
        'relative_volatility': component Psat values at feed temperature and
                               ideal-liquid relative volatility for internally
                               ordered adjacent pairs.
        'shortcut_train': optimized direct ShortcutColumn train after all
                               product minimum mole purities are available.
        'error'              : only if the calculation itself failed (also
                               present alongside a failed 'boiling_point_order').
    """
    transition = assess_candidate_transition(
        feed_state, checked_facts, turn_number=turn_number, evidence=evidence,
    )
    assessment = assess_feed_state(transition['committed_state'])
    committed = assessment['state']

    base = {
        'feed_state': committed,
        'accepted_groups': transition['accepted_groups'],
        'rejected_groups': transition['rejected_groups'],
    }

    if transition['conflicts']:
        return {
            **base, 'complete': False, 'valid': False,
            'conflicts': transition['conflicts'], 'validation_errors': [],
            'missing_field': None,
        }

    if transition['validation_errors']:
        return {
            **base, 'complete': False, 'valid': False,
            'conflicts': [], 'validation_errors': transition['validation_errors'],
            'missing_field': None,
        }

    if not assessment['ready']:
        missing = assessment['missing_inputs']
        return {
            **base, 'complete': False, 'valid': True,
            'conflicts': [], 'validation_errors': [],
            'missing_field': missing[0] if missing else None,
        }

    boiling_result = calculate_multicomponent_boiling_point_order(committed['component_names'])
    if not boiling_result['valid']:
        return {
            **base, 'complete': False, 'valid': False,
            'conflicts': [], 'validation_errors': [], 'missing_field': None,
            'error': boiling_result.get('error'), 'error_message': boiling_result.get('message'),
            'boiling_point_order': boiling_result,
        }

    temperature_K = temperature_to_K(
        record_value(committed['feed_temperature']),
        record_unit(committed['feed_temperature']),
    )
    products = [[name] for name in committed['component_names']]
    product_specification = {
        'assumption': 'all_components_separate_individual_products',
        'number_of_products': len(products),
        'products': products,
    }
    critical_result = evaluate_critical_temperatures(
        committed['component_names'], temperature_K,
    )
    if not critical_result['valid']:
        return {
            **base, 'complete': False, 'valid': False,
            'conflicts': [], 'validation_errors': [], 'missing_field': None,
            'error': critical_result.get('error'),
            'error_message': critical_result.get('message'),
            'boiling_point_order': boiling_result,
            'product_specification': product_specification,
            'critical_temperature_check': critical_result,
        }

    if not critical_result['ordinary_distillation_feasible']:
        return {
            **base, 'complete': True, 'valid': True,
            'conflicts': [], 'validation_errors': [], 'missing_field': None,
            'boiling_point_order': boiling_result,
            'product_specification': product_specification,
            'critical_temperature_check': critical_result,
            'ordinary_distillation_feasible': False,
            'relative_volatility': None,
        }

    volatility_result = calculate_adjacent_relative_volatilities(
        committed['component_names'], boiling_result['order_low_to_high'], temperature_K,
    )
    if not volatility_result['valid']:
        return {
            **base, 'complete': False, 'valid': False,
            'conflicts': [], 'validation_errors': [], 'missing_field': None,
            'error': volatility_result.get('error'),
            'error_message': volatility_result.get('message'),
            'boiling_point_order': boiling_result,
            'relative_volatility': volatility_result,
        }

    close_pairs = [
        pair for pair in volatility_result['adjacent_pairs']
        if pair['relative_volatility'] < 1.05
    ]
    if close_pairs:
        return {
            **base, 'complete': True, 'valid': True,
            'conflicts': [], 'validation_errors': [], 'missing_field': None,
            'boiling_point_order': boiling_result,
            'product_specification': product_specification,
            'critical_temperature_check': critical_result,
            'ordinary_distillation_feasible': False,
            'relative_volatility': volatility_result,
            'close_relative_volatility_pairs': close_pairs,
            'shortcut_train': None,
        }

    purities = committed.get('product_purities') or {}
    if not all(name in purities for name in committed['component_names']):
        return {
            **base, 'complete': False, 'valid': True,
            'conflicts': [], 'validation_errors': [],
            'missing_field': 'product_purities',
            'boiling_point_order': boiling_result,
            'product_specification': product_specification,
            'critical_temperature_check': critical_result,
            'ordinary_distillation_feasible': True,
            'relative_volatility': volatility_result,
            'close_relative_volatility_pairs': [],
        }

    train_result = design_direct_shortcut_train(
        committed, boiling_result['order_low_to_high'],
    )
    if not train_result['valid']:
        return {
            **base, 'complete': False, 'valid': False,
            'conflicts': [], 'validation_errors': [], 'missing_field': None,
            'error': train_result.get('error'),
            'error_message': train_result.get('message'),
            'boiling_point_order': boiling_result,
            'product_specification': product_specification,
            'critical_temperature_check': critical_result,
            'ordinary_distillation_feasible': True,
            'relative_volatility': volatility_result,
            'close_relative_volatility_pairs': [],
            'shortcut_train': train_result,
        }

    return {
        **base, 'complete': True, 'valid': True,
        'conflicts': [], 'validation_errors': [], 'missing_field': None,
        'boiling_point_order': boiling_result,
        'product_specification': product_specification,
        'critical_temperature_check': critical_result,
        'ordinary_distillation_feasible': True,
        'relative_volatility': volatility_result,
        'close_relative_volatility_pairs': [],
        'shortcut_train': train_result,
    }


def query_feed_state(feed_state, target_field):
    """
    Read-only lookup. Takes `target_field` already verified by
    `multicomponent_grounding.ground_query_target_field` -- this function
    trusts its caller, since verifying a message actually asked about a
    field is a text-interpretation job that belongs in the conversation
    layer, not here. Never mutates `feed_state`; never runs
    `assess_feed_state`'s ready/VLE path.
    """
    return copy.deepcopy(feed_state)


def update_multicomponent_feed(feed_state, turn_number=None, evidence=None, **checked_facts):
    """Thin wrapper over `advance_feed_state` for narrow direct-call
    tests; not used by the normal agent path, which threads `feed_state`
    through a session explicitly (see `multicomponent_distillation_agent.py`)."""
    return advance_feed_state(feed_state, checked_facts, turn_number=turn_number, evidence=evidence)


def reset_multicomponent_feed_session() -> dict:
    """A fresh, empty feed state -- for "the user is clearly switching to
    a different feed" (see `multicomponent_dialogue`'s `reset` intent
    handling in the agent)."""
    return empty_feed_state()
