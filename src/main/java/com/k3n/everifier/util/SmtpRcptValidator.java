package com.k3n.everifier.util;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import javax.net.ssl.SSLSocket;
import javax.net.ssl.SSLSocketFactory;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.PrintWriter;
import java.net.Socket;
import java.net.SocketTimeoutException;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;

/**
 * Utility for validating an email address's existence via SMTP RCPT TO command.
 * Supports TLS upgrade, robust resource management, and diagnostic transcript.
 */
@Component
public class SmtpRcptValidator {

    private static final Logger logger = LoggerFactory.getLogger(SmtpRcptValidator.class);

    @Value("${smtp.timeout.ms:5000}")
    private int timeoutMs;

    /**
     * SMTP recipient validation result status.
     */
    public enum SmtpRecipientStatus {
        Valid, UserNotFound, TemporaryFailure, UnknownFailure, Blacklisted
    }

    /**
     * Complete result for an SMTP recipient validation (immutable).
     */
    public static class ValidationResult {
        private final SmtpRecipientStatus status;
        private final int smtpCode;
        private final String smtpResponse;
        private final String errorMessage;
        private final String mxHost;
        private final String fullTranscript;
        private final String timestamp;
        private final String diagnosticTag;
        private final boolean tlsSupported;

        public ValidationResult(SmtpRecipientStatus status, int smtpCode, String smtpResponse,
                                String errorMessage, String mxHost, String fullTranscript,
                                String timestamp, String diagnosticTag, boolean tlsSupported) {
            this.status = status;
            this.smtpCode = smtpCode;
            this.smtpResponse = smtpResponse;
            this.errorMessage = errorMessage;
            this.mxHost = mxHost;
            this.fullTranscript = fullTranscript;
            this.timestamp = timestamp;
            this.diagnosticTag = diagnosticTag;
            this.tlsSupported = tlsSupported;
        }

        public SmtpRecipientStatus getStatus() { return status; }
        public int getSmtpCode() { return smtpCode; }
        public String getSmtpResponse() { return smtpResponse; }
        public String getErrorMessage() { return errorMessage; }
        public String getMxHost() { return mxHost; }
        public String getFullTranscript() { return fullTranscript; }
        public String getTimestamp() { return timestamp; }
        public String getDiagnosticTag() { return diagnosticTag; }
        public boolean isTlsSupported() { return tlsSupported; }
    }

    /**
     * Validates the given recipient using a direct SMTP RCPT TO session.
     *
     * @param mxHost MX server host address (required, not null or empty)
     * @param email  Email to check (required, not null or empty)
     * @return validation result with SMTP code/response/status
     */
    public ValidationResult validateRecipient(final String mxHost, final String email) {
        if (mxHost == null || mxHost.trim().isEmpty()) {
            throw new IllegalArgumentException("mxHost must not be null or empty");
        }
        if (email == null || email.trim().isEmpty()) {
            throw new IllegalArgumentException("email must not be null or empty");
        }

        final StringBuilder transcript = new StringBuilder();
        final DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSS");
        final String timestamp = LocalDateTime.now().format(formatter);
        boolean tlsSupported = false;

        try (
                Socket socket = new Socket(mxHost, 25);
                BufferedReader reader = new BufferedReader(new InputStreamReader(socket.getInputStream()));
                PrintWriter writer = new PrintWriter(socket.getOutputStream(), true)
        ) {
            socket.setSoTimeout(timeoutMs);

            transcript.append(readAndLog(reader)).append('\n');
            String ehloResponse = sendAndLog("EHLO syfer25.com", reader, writer);
            transcript.append(ehloResponse).append('\n');

            if (ehloResponse.toLowerCase().contains("starttls")) {
                tlsSupported = true;
                transcript.append(sendAndLog("STARTTLS", reader, writer)).append('\n');

                // Upgrade connection to TLS for remaining session
                try (
                        SSLSocket tlsSocket = (SSLSocket) upgradeToTls(socket, mxHost);
                        BufferedReader tlsReader = new BufferedReader(new InputStreamReader(tlsSocket.getInputStream()));
                        PrintWriter tlsWriter = new PrintWriter(tlsSocket.getOutputStream(), true)
                ) {
                    tlsSocket.setSoTimeout(timeoutMs);

                    transcript.append("<< TLS handshake successful\n");
                    transcript.append("<< TLS protocol: " + tlsSocket.getSession().getProtocol() + '\n');
                    transcript.append("<< TLS cipher suite: " + tlsSocket.getSession().getCipherSuite() + '\n');
                    transcript.append(sendAndLog("EHLO syfer25.com", tlsReader, tlsWriter)).append('\n');
                    transcript.append(sendAndLog("MAIL FROM:<validator@syfer25.com>", tlsReader, tlsWriter)).append('\n');
                    String rcptResponse = sendAndLog("RCPT TO:<" + email + ">", tlsReader, tlsWriter);
                    transcript.append(rcptResponse).append('\n');

                    int code = parseSmtpCode(rcptResponse);
                    SmtpRecipientStatus status = classifyResponse(code, rcptResponse);
                    String tag = generateDiagnosticTag(code, rcptResponse);

                    return new ValidationResult(status, code, rcptResponse, null, mxHost,
                            transcript.toString().trim(), timestamp, tag, tlsSupported);
                } catch (Exception tlsEx) {
                    logger.error("TLS handshake failed ({}): {}", mxHost, tlsEx.getMessage());
                    transcript.append("<< TLS handshake failed: ")
                            .append(tlsEx.getClass().getSimpleName())
                            .append(" - ").append(tlsEx.getMessage()).append('\n');
                    return new ValidationResult(SmtpRecipientStatus.TemporaryFailure, -1, null,
                            "TLS handshake failed: " + tlsEx.getMessage(), mxHost, transcript.toString().trim(),
                            timestamp, "TLSHandshakeFailed", true);
                }
            } else {
                transcript.append(">> STARTTLS not supported by server\n");
                transcript.append(sendAndLog("MAIL FROM:<validator@syfer25.com>", reader, writer)).append('\n');
                String rcptResponse = sendAndLog("RCPT TO:<" + email + ">", reader, writer);
                transcript.append(rcptResponse).append('\n');

                int code = parseSmtpCode(rcptResponse);
                SmtpRecipientStatus status = classifyResponse(code, rcptResponse);
                String tag = generateDiagnosticTag(code, rcptResponse);

                return new ValidationResult(status, code, rcptResponse, null, mxHost,
                        transcript.toString().trim(), timestamp, tag, tlsSupported);
            }
        } catch (SocketTimeoutException e) {
            logger.warn("Timeout connecting to {}: {}", mxHost, e.getMessage());
            return new ValidationResult(SmtpRecipientStatus.TemporaryFailure, -1, null,
                    "Timeout: " + e.getMessage(), mxHost, transcript.toString().trim(),
                    timestamp, "Timeout", tlsSupported);
        } catch (Exception e) {
            logger.error("Exception connecting to {}: {}", mxHost, e.getMessage());
            return new ValidationResult(SmtpRecipientStatus.UnknownFailure, -1, null,
                    "Error: " + e.getMessage(), mxHost, transcript.toString().trim(),
                    timestamp, "Exception", tlsSupported);
        }
    }

    /**
     * Checks if the domain acts as a catch-all by testing target and random recipient acceptance in a single SMTP session.
     *
     * @param mxHost MX host to connect for SMTP session (required, not null or empty)
     * @param email  target email address to validate (required, not null or empty)
     * @param domain domain for generating random catch-all test address (required, not null or empty)
     * @return true if both target and random addresses are accepted, indicating catch-all; false otherwise
     */
    public boolean checkSmtpCatchAllSingleSession(final String mxHost, final String email, final String domain) {
        if (mxHost == null || mxHost.trim().isEmpty()) {
            throw new IllegalArgumentException("mxHost must not be null or empty");
        }
        if (email == null || email.trim().isEmpty()) {
            throw new IllegalArgumentException("email must not be null or empty");
        }
        if (domain == null || domain.trim().isEmpty()) {
            throw new IllegalArgumentException("domain must not be null or empty");
        }

        final String randomEmail = "random" + System.currentTimeMillis() + "@" + domain;

        try (
                Socket socket = new Socket(mxHost, 25);
                BufferedReader reader = new BufferedReader(new InputStreamReader(socket.getInputStream()));
                PrintWriter writer = new PrintWriter(socket.getOutputStream(), true)
        ) {
            socket.setSoTimeout(timeoutMs);

            readFullResponse(reader); // Server greeting

            String ehloResponse = sendAndLog("EHLO syfer25.com", reader, writer);

            boolean tlsSupported = ehloResponse.toLowerCase().contains("starttls");
            BufferedReader sessionReader = reader;
            PrintWriter sessionWriter = writer;
            Socket sessionSocket = socket;

            if (tlsSupported) {
                sendAndLog("STARTTLS", reader, writer);
                SSLSocket tlsSocket = (SSLSocket) upgradeToTls(socket, mxHost);
                tlsSocket.setSoTimeout(timeoutMs);
                sessionReader = new BufferedReader(new InputStreamReader(tlsSocket.getInputStream()));
                sessionWriter = new PrintWriter(tlsSocket.getOutputStream(), true);
                sessionSocket = tlsSocket;
                sendAndLog("EHLO syfer25.com", sessionReader, sessionWriter);
            }

            sendAndLog("MAIL FROM:<validator@syfer25.com>", sessionReader, sessionWriter);

            String rcptResponseTarget = sendAndLog("RCPT TO:<" + email + ">", sessionReader, sessionWriter);
            int codeTarget = parseSmtpCode(rcptResponseTarget);

            String rcptResponseRandom = sendAndLog("RCPT TO:<" + randomEmail + ">", sessionReader, sessionWriter);
            int codeRandom = parseSmtpCode(rcptResponseRandom);

            // Close session socket if TLS socket was created
            if (!sessionSocket.isClosed()) {
                sessionSocket.close();
            }

            return (codeTarget >= 250 && codeTarget < 260) && (codeRandom >= 250 && codeRandom < 260);
        } catch (Exception e) {
            logger.error("Error during SMTP catch-all check for {}: {}", mxHost, e.getMessage());
            return false;
        }
    }

    private Socket upgradeToTls(final Socket plainSocket, final String mxHost) throws IOException {
        final SSLSocketFactory sslSocketFactory = (SSLSocketFactory) SSLSocketFactory.getDefault();
        final SSLSocket sslSocket = (SSLSocket) sslSocketFactory.createSocket(
                plainSocket, mxHost, plainSocket.getPort(), true);
        sslSocket.setEnabledProtocols(new String[] {"TLSv1.2"});
        sslSocket.startHandshake();
        return sslSocket;
    }

    private String sendAndLog(final String command, final BufferedReader reader, final PrintWriter writer) throws IOException {
        writer.println(command);
        writer.flush(); // Ensure command is sent immediately
        String response = readFullResponse(reader);
        return ">> " + command + "\n<< " + response;
    }

    private String readAndLog(final BufferedReader reader) throws IOException {
        String response = readFullResponse(reader);
        return "<< " + response;
    }

    private String readFullResponse(final BufferedReader reader) throws IOException {
        final StringBuilder response = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) {
            response.append(line).append('\n');
            if (line.length() < 4 || line.charAt(3) != '-') break;
        }
        return response.toString().trim();
    }

    private int parseSmtpCode(final String response) {
        if (response == null || response.length() < 3) return -1;
        String[] lines = response.split("\n");
        String lastLine = lines[lines.length - 1].trim();
        if (lastLine.startsWith("<< ")) lastLine = lastLine.substring(3).trim();
        try {
            return Integer.parseInt(lastLine.substring(0, 3));
        } catch (NumberFormatException e) {
            return -1;
        }
    }

    private SmtpRecipientStatus classifyResponse(final int code, final String response) {
        final String lower = response != null ? response.toLowerCase() : "";
        if (code >= 250 && code <= 259) return SmtpRecipientStatus.Valid;
        if (code == 252 || (code >= 400 && code < 500)) return SmtpRecipientStatus.TemporaryFailure;
        if (code == 550 || code == 551 || code == 553 ||
                lower.contains("user not found") || lower.contains("user unknown") ||
                lower.contains("recipient address rejected") || lower.contains("no such user")) {
            return SmtpRecipientStatus.UserNotFound;
        }
        if (code == 554 || lower.contains("relay access denied") || lower.contains("not permitted")) {
            return SmtpRecipientStatus.UnknownFailure;
        }
        if (code >= 500 && code < 600) return SmtpRecipientStatus.UnknownFailure;
        if (code == 550 && (lower.contains("blocked") || lower.contains("spamhaus") || lower.contains("blacklist"))) {
            return SmtpRecipientStatus.Blacklisted;
        }
        return SmtpRecipientStatus.UnknownFailure;
    }

    private String generateDiagnosticTag(final int code, final String response) {
        final String lower = response != null ? response.toLowerCase() : "";
        if (code == 250) return "Accepted";
        if (code == 251) return "Forwarded";
        if (code == 252) return "CannotVerify";
        if (code == 421) return "ServiceUnavailable";
        if (code == 450) return "MailboxBusy";
        if (code == 451) return "LocalError";
        if (code == 452) return "InsufficientStorage";
        if (code == 550 && lower.contains("blocked")) return "Blocked";
        if (code == 550 && lower.contains("spamhaus")) return "BlockedBySpamhaus";
        if (code == 550 && lower.contains("blacklist")) return "BlockedByBlacklist";
        if (code == 550) return "UserNotFound";
        if (code == 551) return "UserNotLocal";
        if (code == 552) return "StorageExceeded";
        if (lower.contains("relay access denied")) return "RelayDenied";
        if (lower.contains("not permitted")) return "AccessDenied";
        if (lower.contains("user unknown") || lower.contains("recipient address rejected") || lower.contains("no such user"))
            return "UserUnknown";
        return "Unclassified";
    }
}
