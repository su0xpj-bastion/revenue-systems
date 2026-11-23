import { LightningElement, api, wire } from 'lwc';
import { refreshApex } from '@salesforce/apex';
import { ShowToastEvent } from 'lightning/platformShowToastEvent';
import load from '@salesforce/apex/SyncConsoleController.load';
import retry from '@salesforce/apex/SyncConsoleController.retry';
import resolveBreak from '@salesforce/apex/SyncConsoleController.resolveBreak';
import { actionsFor, statusClass, reduceError } from 'c/syncConsoleUtils';

const MESSAGE_COLUMNS = [
    { label: 'Message', fieldName: 'Name', initialWidth: 120 },
    { label: 'Direction', fieldName: 'Direction__c', initialWidth: 100 },
    { label: 'Target', fieldName: 'Target__c', initialWidth: 90 },
    { label: 'Operation', fieldName: 'Operation__c' },
    { label: 'Version', fieldName: 'Entity_Version__c', type: 'number', initialWidth: 80 },
    { label: 'Status', fieldName: 'Status__c', initialWidth: 120, cellAttributes: { class: { fieldName: 'statusClass' } } },
    { label: 'Attempts', fieldName: 'Attempts__c', type: 'number', initialWidth: 90 },
    { label: 'Last error', fieldName: 'Last_Error__c', wrapText: true }
];

const BREAK_COLUMNS = [
    { label: 'Kind', fieldName: 'Kind__c' },
    { label: 'Line', fieldName: 'Line_Key__c' },
    { label: 'Salesforce', fieldName: 'Salesforce_Value__c' },
    { label: 'Billing', fieldName: 'Billing_Value__c' },
    { label: 'Run', fieldName: 'Run_Id__c' }
];

export default class SyncConsole extends LightningElement {
    @api recordId;
    summary;
    error;
    busy = false;
    wired;

    @wire(load, { contractId: '$recordId' })
    wiredSummary(result) {
        this.wired = result;
        if (result.data) {
            this.summary = result.data;
            this.error = undefined;
        } else if (result.error) {
            this.error = reduceError(result.error);
            this.summary = undefined;
        }
    }

    get messageColumns() {
        if (!this.summary || !this.summary.canRetry) {
            return MESSAGE_COLUMNS;
        }
        return [
            ...MESSAGE_COLUMNS,
            { type: 'action', typeAttributes: { rowActions: (row, done) => done(actionsFor(row)) } }
        ];
    }

    get breakColumns() {
        if (!this.summary || !this.summary.canRetry) {
            return BREAK_COLUMNS;
        }
        return [...BREAK_COLUMNS, { type: 'button', typeAttributes: { label: 'Resolve', name: 'resolve', variant: 'base' } }];
    }

    get messages() {
        return (this.summary?.messages || []).map((m) => ({ ...m, statusClass: statusClass(m.Status__c) }));
    }

    get breaks() {
        return this.summary?.openBreaks || [];
    }

    get hasMessages() {
        return this.messages.length > 0;
    }

    get hasBreaks() {
        return this.breaks.length > 0;
    }

    get headline() {
        const s = this.summary;
        if (!s) {
            return '';
        }
        if (s.inSync) {
            return `In sync with Billing at v${s.version}`;
        }
        const synced = s.lastSyncedVersion == null ? 'never' : `v${s.lastSyncedVersion}`;
        return `Billing behind: Salesforce v${s.version}, last acknowledged ${synced}`;
    }

    get headlineClass() {
        return this.summary?.inSync ? 'slds-text-color_success' : 'slds-text-color_error';
    }

    get stuckCount() {
        return this.messages.filter((m) => m.Status__c === 'Dead' || m.Status__c === 'Parked').length;
    }

    async handleMessageAction(event) {
        const row = event.detail.row;
        if (event.detail.action.name !== 'retry') {
            return;
        }
        await this.run(() => retry({ messageId: row.Id }), (status) => `${row.Name} re-queued (${status})`);
    }

    async handleBreakAction(event) {
        const row = event.detail.row;
        await this.run(() => resolveBreak({ breakId: row.Id }), () => 'Break marked resolved');
    }

    async run(call, successMessage) {
        this.busy = true;
        try {
            const result = await call();
            this.toast('success', successMessage(result));
            await refreshApex(this.wired);
        } catch (e) {
            this.toast('error', reduceError(e));
        } finally {
            this.busy = false;
        }
    }

    handleRefresh() {
        return refreshApex(this.wired);
    }

    toast(variant, message) {
        this.dispatchEvent(new ShowToastEvent({ title: variant === 'success' ? 'Done' : 'Could not complete', message, variant }));
    }
}
