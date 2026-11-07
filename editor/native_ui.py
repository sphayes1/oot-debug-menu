"""Pure presentation for native request receipts; does not perform game IO."""


def whole_heart_maximum(units):
    return max(12, min(80, units)) // 4 * 4


def native_message(receipt):
    field = receipt.get('field', 'GameData')
    state = receipt.get('state')
    if state == 'queued_effect_unverified':
        return f'{field} request queued. Gameplay effect is not yet verified.', False
    if state == 'busy_no_changes':
        return f'{field} request was busy; no changes made. No automatic retry.', False
    if state == 'uncertain_no_retry':
        return f'{field} outcome is uncertain. Do not repeat the request; inspect its audit.', True
    return f'{field} request refused or unrecognized. No automatic retry; inspect its audit.', True
