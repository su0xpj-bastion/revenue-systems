import { createElement } from 'lwc';
import SyncConsole from 'c/syncConsole';
import load from '@salesforce/apex/SyncConsoleController.load';
import retry from '@salesforce/apex/SyncConsoleController.retry';
const ShowToastEventName = 'lightning__showtoast';

jest.mock(
    '@salesforce/apex/SyncConsoleController.load',
    () => {
        const { createApexTestWireAdapter } = require('@salesforce/sfdx-lwc-jest');
        return { default: createApexTestWireAdapter(jest.fn()) };
    },
    { virtual: true }
);
jest.mock('@salesforce/apex/SyncConsoleController.retry', () => ({ default: jest.fn() }), { virtual: true });
jest.mock('@salesforce/apex/SyncConsoleController.resolveBreak', () => ({ default: jest.fn() }), { virtual: true });

const OUT_OF_SYNC = {
    version: 4,
    lastSyncedVersion: 3,
    status: 'Active',
    inSync: false,
    canRetry: true,
    messages: [
        { Id: 'm1', Name: 'SM-00000002', Direction__c: 'Outbound', Target__c: 'Billing', Operation__c: 'upsert_contract',
          Status__c: 'Dead', Entity_Version__c: 4, Attempts__c: 8, Last_Error__c: 'HTTP 401' },
        { Id: 'm0', Name: 'SM-00000001', Direction__c: 'Outbound', Target__c: 'Billing', Operation__c: 'upsert_contract',
          Status__c: 'Acked', Entity_Version__c: 3, Attempts__c: 1 }
    ],
    openBreaks: [{ Id: 'b1', Kind__c: 'Quantity_Mismatch', Line_Key__c: 'c:SEATS', Salesforce_Value__c: '10.00', Billing_Value__c: '7.00' }]
};

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

function mount() {
    const el = createElement('c-sync-console', { is: SyncConsole });
    el.recordId = 'a01000000000001AAA';
    document.body.appendChild(el);
    return el;
}

describe('c-sync-console', () => {
    afterEach(() => {
        while (document.body.firstChild) {
            document.body.removeChild(document.body.firstChild);
        }
        jest.clearAllMocks();
    });

    it('says when Billing is behind and how many messages are stuck', async () => {
        const el = mount();
        load.emit(OUT_OF_SYNC);
        await flush();
        const headline = el.shadowRoot.querySelector('[data-id="headline"]');
        expect(headline.textContent).toBe('Billing behind: Salesforce v4, last acknowledged v3');
        expect(headline.className).toContain('slds-text-color_error');
        expect(el.shadowRoot.querySelector('[data-id="stuck"]').textContent).toBe('1 message(s) need attention.');
        expect(el.shadowRoot.querySelector('[data-id="breaks"]').data).toHaveLength(1);
    });

    it('shows a clean state when in sync with no breaks', async () => {
        const el = mount();
        load.emit({ ...OUT_OF_SYNC, inSync: true, lastSyncedVersion: 4, messages: [], openBreaks: [] });
        await flush();
        expect(el.shadowRoot.querySelector('[data-id="headline"]').textContent).toBe('In sync with Billing at v4');
        expect(el.shadowRoot.querySelector('[data-id="stuck"]')).toBeNull();
        expect(el.shadowRoot.querySelector('[data-id="no-breaks"]')).not.toBeNull();
    });

    it('only operators get the retry column', async () => {
        const el = mount();
        load.emit({ ...OUT_OF_SYNC, canRetry: false });
        await flush();
        const cols = el.shadowRoot.querySelector('[data-id="messages"]').columns;
        expect(cols.some((c) => c.type === 'action')).toBe(false);

        load.emit(OUT_OF_SYNC);
        await flush();
        const opCols = el.shadowRoot.querySelector('[data-id="messages"]').columns;
        expect(opCols.some((c) => c.type === 'action')).toBe(true);
    });

    it('retry calls Apex with the message id and toasts the result', async () => {
        retry.mockResolvedValue('Pending');
        const el = mount();
        load.emit(OUT_OF_SYNC);
        await flush();
        const toast = jest.fn();
        el.addEventListener(ShowToastEventName, toast);

        el.shadowRoot.querySelector('[data-id="messages"]').dispatchEvent(
            new CustomEvent('rowaction', { detail: { action: { name: 'retry' }, row: OUT_OF_SYNC.messages[0] } })
        );
        await flush();
        expect(retry).toHaveBeenCalledWith({ messageId: 'm1' });
        expect(toast.mock.calls[0][0].detail.variant).toBe('success');
        expect(toast.mock.calls[0][0].detail.message).toBe('SM-00000002 re-queued (Pending)');
    });

    it('a server refusal becomes an error toast, not a crash', async () => {
        retry.mockRejectedValue({ body: { message: 'You need the Q2C Sync Operator permission to retry sync messages.' } });
        const el = mount();
        load.emit(OUT_OF_SYNC);
        await flush();
        const toast = jest.fn();
        el.addEventListener(ShowToastEventName, toast);
        el.shadowRoot.querySelector('[data-id="messages"]').dispatchEvent(
            new CustomEvent('rowaction', { detail: { action: { name: 'retry' }, row: OUT_OF_SYNC.messages[0] } })
        );
        await flush();
        expect(toast.mock.calls[0][0].detail.variant).toBe('error');
        expect(toast.mock.calls[0][0].detail.message).toContain('Q2C Sync Operator');
    });

    it('renders the load error', async () => {
        const el = mount();
        load.error({ message: 'insufficient access' });
        await flush();
        expect(el.shadowRoot.querySelector('[data-id="error"]')).not.toBeNull();
    });
});
