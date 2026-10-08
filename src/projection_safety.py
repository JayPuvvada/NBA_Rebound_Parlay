"""Conservative reconciliation of safety signals before issuing a prediction."""


def projection_eligibility(projection):
    """Require model authorization; never overwrite another explicit veto.

    Producers may expose safety metadata at several levels. Missing optional
    contexts remain compatible, but any explicit restriction or degraded source
    wins over an optimistic metadata flag. Preserve warnings from all contexts.
    """
    metadata = projection.get('metadata')
    metadata = metadata if isinstance(metadata, dict) else {}
    signal = metadata.get('prediction_eligible')
    eligible = signal is True
    limitations = []

    def add_warnings(context):
        nonlocal eligible
        value = context.get('limitations')
        if value is None:
            return
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            eligible = False
            limitations.append('projection safety warnings were malformed; analysis-only')
            return
        limitations.extend(value)

    if signal is not True and signal is not False:
        limitations.append('projection safety metadata did not explicitly authorize a live pick')
    contexts = [metadata, projection]
    freshness = projection.get('data_freshness')
    if isinstance(freshness, dict):
        contexts.append(freshness)
    elif freshness is not None:
        eligible = False
        limitations.append('projection freshness metadata was not structured; analysis-only')
    for context in contexts:
        add_warnings(context)
        if 'prediction_eligible' in context and context['prediction_eligible'] is not True:
            eligible = False
            # Existing producers generally explain their own veto. Add a
            # reason only when the conflicting context provides none.
            if context is not metadata and not context.get('limitations'):
                limitations.append('an upstream safety flag did not authorize a live pick')
        source = context.get('projection_inputs')
        if source is not None:
            if isinstance(source, dict):
                add_warnings(source)
            if not isinstance(source, dict) or source.get('status') != 'primary':
                eligible = False
                limitations.append('projection input source was not verified as primary; analysis-only')
    return eligible, list(dict.fromkeys(limitations))
