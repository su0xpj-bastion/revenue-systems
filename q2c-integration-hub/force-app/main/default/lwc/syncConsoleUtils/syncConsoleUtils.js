// Pure helpers for syncConsole, kept in their own module so they're unit-tested without the DOM.

const RETRYABLE = new Set(['Dead', 'Parked', 'Retrying']);

export function actionsFor(row) {
    return [{ label: 'Retry now', name: 'retry', disabled: !RETRYABLE.has(row.Status__c) }];
}

export function statusClass(status) {
    if (status === 'Dead' || status === 'Parked') {
        return 'slds-text-color_error';
    }
    if (status === 'Retrying' || status === 'Pending') {
        return 'slds-text-color_weak';
    }
    return 'slds-text-color_success';
}

export function reduceError(e) {
    if (!e) {
        return 'Unknown error';
    }
    if (Array.isArray(e.body)) {
        return e.body.map((b) => b.message).join(', ');
    }
    return e.body?.message || e.message || 'Unknown error';
}
