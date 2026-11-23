import { actionsFor, statusClass, reduceError } from 'c/syncConsoleUtils';

describe('syncConsoleUtils', () => {
    it.each([
        ['Dead', false], ['Parked', false], ['Retrying', false],
        ['Acked', true], ['Pending', true], ['Superseded', true], ['Applied', true], ['Ignored_Stale', true]
    ])('retry action for %s disabled=%s', (status, disabled) => {
        expect(actionsFor({ Status__c: status })[0].disabled).toBe(disabled);
    });

    it('colors stuck, in-flight and done messages differently', () => {
        expect(statusClass('Dead')).toBe('slds-text-color_error');
        expect(statusClass('Parked')).toBe('slds-text-color_error');
        expect(statusClass('Retrying')).toBe('slds-text-color_weak');
        expect(statusClass('Acked')).toBe('slds-text-color_success');
    });

    it('reduces Apex, UI API and plain errors to one message', () => {
        expect(reduceError({ body: { message: 'apex says no' } })).toBe('apex says no');
        expect(reduceError({ body: [{ message: 'a' }, { message: 'b' }] })).toBe('a, b');
        expect(reduceError(new Error('plain'))).toBe('plain');
        expect(reduceError(undefined)).toBe('Unknown error');
    });
});
