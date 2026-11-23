/**
 * What to do with the result of one outbound delivery attempt. Pure: no queries, no DML.
 *
 * ACK         2xx. The target applied the message (or replayed its earlier answer for this
 *             Idempotency-Key, which is the same thing to us).
 * SUPERSEDED  409. The target already holds a newer version of this entity; sending ours would
 *             move it backwards. Nothing to retry.
 * RETRY       Transient: timeout, connection error, 408/425/429/5xx. Safe to resend because every
 *             request carries the same Idempotency-Key.
 * DEAD        Anything else (400/401/403/404/422...): resending the same bytes can't succeed.
 *             A person has to look. Also where RETRY ends up after maxAttempts.
 *
 * Same rules as vectors/sync-vectors.json -> "retry" and "backoff".
 */
public inherited sharing class RetryPolicy {
    public enum Decision { ACK, RETRY, DEAD, SUPERSEDED }

    public static final Integer BASE_SECONDS = 30;
    public static final Integer CAP_SECONDS = 3600;

    @TestVisible
    static final Set<Integer> RETRYABLE_STATUS = new Set<Integer>{ 408, 425, 429, 500, 502, 503, 504 };

    public static Decision classify(Integer status, Boolean timedOut, Integer attempts, Integer maxAttempts) {
        Boolean transientFailure = timedOut == true || status == null || status == 0 || RETRYABLE_STATUS.contains(status);
        if (!transientFailure) {
            if (status >= 200 && status < 300) {
                return Decision.ACK;
            }
            if (status == 409) {
                return Decision.SUPERSEDED;
            }
            return Decision.DEAD;
        }
        return attempts >= maxAttempts ? Decision.DEAD : Decision.RETRY;
    }

    /** 30s, 60s, 120s ... doubling per attempt, capped at one hour. */
    public static Integer baseBackoffSeconds(Integer attempts) {
        Integer n = Math.max(attempts == null ? 1 : attempts, 1);
        if (n > 8) {
            return CAP_SECONDS;
        }
        Integer seconds = BASE_SECONDS * Math.pow(2, n - 1).intValue();
        return Math.min(seconds, CAP_SECONDS);
    }

    /**
     * Half the base plus a random share of the other half. When a target comes back after an outage,
     * the messages that failed together don't all retry in the same second.
     */
    public static Integer jitteredBackoffSeconds(Integer attempts) {
        Integer base = baseBackoffSeconds(attempts);
        Integer half = base / 2;
        return half + Math.floor(Math.random() * (half + 1)).intValue();
    }
}
