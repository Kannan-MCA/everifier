package com.k3n.everifier.util;

public class SmtpResponseClassifier {

    public static SmtpRcptValidator.SmtpRecipientStatus classifyResponse(int code, String enhancedCode, String response) {
        String lower = response != null ? response.toLowerCase() : "";

        if (!enhancedCode.isEmpty()) {
            switch (enhancedCode) {
                case "5.1.1":
                case "5.1.0":
                    return SmtpRcptValidator.SmtpRecipientStatus.UserNotFound;
                case "4.2.1":
                case "4.3.0":
                case "4.4.7":
                    return SmtpRcptValidator.SmtpRecipientStatus.TemporaryFailure;
                case "5.7.1":
                    return SmtpRcptValidator.SmtpRecipientStatus.Blacklisted;
                default:
                    break;
            }
        }

        if (code >= 250 && code <= 259) return SmtpRcptValidator.SmtpRecipientStatus.Valid;
        if (code == 252 || (code >= 400 && code < 500)) return SmtpRcptValidator.SmtpRecipientStatus.TemporaryFailure;
        if (code == 550 || lower.contains("user unknown") || lower.contains("no such user"))
            return SmtpRcptValidator.SmtpRecipientStatus.UserNotFound;
        if (lower.contains("blacklist") || lower.contains("spamhaus") || lower.contains("blocked"))
            return SmtpRcptValidator.SmtpRecipientStatus.Blacklisted;
        return SmtpRcptValidator.SmtpRecipientStatus.UnknownFailure;
    }

    public static String generateDiagnosticTag(int code, String response) {
        if (code == 250) return "Accepted";
        if (code == 550) return "UserNotFound";
        if (code == 554) return "Rejected";
        if (code == 451) return "Temporary";
        if (response != null && response.toLowerCase().contains("blacklist")) return "BlockedByBlacklist";
        return "Unclassified";
    }
}
