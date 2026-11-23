/**
 * Platform Event subscriber. Runs as the Automated Process user, in its own transaction, after the
 * contract save committed. Delivery is at-least-once, and that's fine: OutboxService inserts are
 * idempotent, so a redelivered or retried batch creates nothing new.
 */
trigger Q2CChangeSubscriber on Q2C_Change__e (after insert) {
    OutboxService.enqueueFromEvents(Trigger.new);
}
