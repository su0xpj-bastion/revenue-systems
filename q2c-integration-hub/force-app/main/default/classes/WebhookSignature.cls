/**
 * Verifies the CLM webhook signature:
 *   X-CLM-Timestamp: <unix seconds>
 *   X-CLM-Signature: sha256=<hex HMAC-SHA256(secret, timestamp + "." + rawBody)>
 *
 * Signing the timestamp with the body stops a captured request from being replayed later; the
 * comparison takes the same time whether the first or last character differs.
 */
public inherited sharing class WebhookSignature {
    public static final Integer MAX_SKEW_SECONDS = 300;

    public static String sign(String secret, String timestamp, String body) {
        Blob mac = Crypto.generateMac('hmacSHA256', Blob.valueOf(timestamp + '.' + body), Blob.valueOf(secret));
        return 'sha256=' + EncodingUtil.convertToHex(mac);
    }

    public static Boolean verify(String secret, String timestamp, String signature, String body, Long nowSeconds) {
        if (String.isBlank(secret) || String.isBlank(timestamp) || String.isBlank(signature) || body == null) {
            return false;
        }
        Long ts;
        try {
            ts = Long.valueOf(timestamp);
        } catch (TypeException e) {
            return false;
        }
        if (Math.abs(nowSeconds - ts) > MAX_SKEW_SECONDS) {
            return false;
        }
        return constantTimeEquals(sign(secret, timestamp, body), signature.trim().toLowerCase());
    }

    @TestVisible
    static Boolean constantTimeEquals(String a, String b) {
        if (a.length() != b.length()) {
            return false;
        }
        Integer diff = 0;
        for (Integer i = 0; i < a.length(); i++) {
            diff = diff | (a.charAt(i) ^ b.charAt(i));
        }
        return diff == 0;
    }
}
