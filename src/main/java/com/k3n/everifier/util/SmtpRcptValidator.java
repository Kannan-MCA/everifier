package com.k3n.everifier.util;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Scope;
import org.springframework.stereotype.Component;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import javax.net.ssl.SSLSocket;
import javax.net.ssl.SSLSocketFactory;
import java.io.*;
import java.net.*;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.*;
import java.util.stream.Collectors;

@Component
@Scope("prototype")
public class SmtpRcptValidator {

    private static final Logger logger = LoggerFactory.getLogger(SmtpRcptValidator.class);

    @Value("${smtp.timeout.ms:15000}")
    private int timeoutMs;

    private static final int[] SMTP_PORTS = {25, 587, 465};

    static {
        System.setProperty("java.net.preferIPv4Stack", "true");
    }

    public enum SmtpRecipientStatus {
        Valid, UserNotFound, TemporaryFailure, UnknownFailure, Blacklisted
    }

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
        private final int portUsed;

        public ValidationResult(SmtpRecipientStatus status, int smtpCode, String smtpResponse,
                                String errorMessage, String mxHost, String fullTranscript,
                                String timestamp, String diagnosticTag,
                                boolean tlsSupported, int portUsed) {
            this.status = status;
            this.smtpCode = smtpCode;
            this.smtpResponse = smtpResponse;
            this.errorMessage = errorMessage;
            this.mxHost = mxHost;
            this.fullTranscript = fullTranscript;
            this.timestamp = timestamp;
            this.diagnosticTag = diagnosticTag;
            this.tlsSupported = tlsSupported;
            this.portUsed = portUsed;
        }

        public SmtpRecipientStatus getStatus() {
            return status;
        }

        public int getSmtpCode() {
            return smtpCode;
        }

        public String getSmtpResponse() {
            return smtpResponse;
        }

        public String getErrorMessage() {
            return errorMessage;
        }

        public String getMxHost() {
            return mxHost;
        }

        public String getFullTranscript() {
            return fullTranscript;
        }

        public String getTimestamp() {
            return timestamp;
        }

        public String getDiagnosticTag() {
            return diagnosticTag;
        }

        public boolean isTlsSupported() {
            return tlsSupported;
        }

        public int getPortUsed() {
            return portUsed;
        }
    }

    public ValidationResult validateRecipient(String mxHost, String email) {
        InetAddress inetAddress;
        try {
            inetAddress = InetAddress.getByName(mxHost);
            logger.info("Resolved MX host {} to IP {}", mxHost, inetAddress.getHostAddress());
        } catch (UnknownHostException e) {
            logger.error("DNS resolution failed for {}: {}", mxHost, e.getMessage());
            return new ValidationResult(
                    SmtpRecipientStatus.UnknownFailure, -1, null,
                    "DNS resolution failed: " + e.getMessage(),
                    mxHost, "", LocalDateTime.now().toString(), "DNSResolutionFailed", false, -1);
        }

        ExecutorService executor = Executors.newFixedThreadPool(SMTP_PORTS.length);
        List<Future<ValidationResult>> futures = null;
        try {
            futures = Arrays.stream(SMTP_PORTS)
                    .mapToObj(port -> executor.submit(() -> {
                        try {
                            return attemptValidation(inetAddress, mxHost, email, port);
                        } catch (IOException e) {
                            logger.warn("Port {} failed: {}", port, e.getMessage());
                            return new ValidationResult(
                                    SmtpRecipientStatus.UnknownFailure, -1, e.getMessage(),
                                    "Port validation failed", mxHost, "", LocalDateTime.now().toString(),
                                    "PortFailed", false, port);
                        }
                    }))
                    .collect(Collectors.toList());

            for (Future<ValidationResult> future : futures) {
                try {
                    ValidationResult result = future.get();
                    if (result.getStatus() == SmtpRecipientStatus.Valid) {
                        // Cancel other tasks
                        for (Future<ValidationResult> f : futures) {
                            if (!f.isDone()) {
                                f.cancel(true);
                            }
                        }
                        return result;
                    }
                } catch (CancellationException e) {
                    // Ignored - task was cancelled
                } catch (Exception e) {
                    logger.error("Exception during validation execution: {}", e.getMessage());
                }
            }

            // No success; return first failure or UnknownFailure if none found
            for (Future<ValidationResult> future : futures) {
                if (future.isDone() && !future.isCancelled()) {
                    try {
                        ValidationResult res = future.get();
                        if (res != null) {
                            return res;
                        }
                    } catch (Exception e) {
                        // ignore exceptions here
                    }
                }
            }
        } finally {
            if (executor != null) {
                executor.shutdownNow();
            }
        }

        return new ValidationResult(
                SmtpRecipientStatus.UnknownFailure, -1, "All ports failed", "No successful validation",
                mxHost, "", LocalDateTime.now().toString(), "AllPortsFailed", false, -1);
    }

    private ValidationResult attemptValidation(InetAddress inetAddress, String mxHost, String email, int port) throws IOException {
        boolean tlsSupported = false;
        final StringBuilder transcript = new StringBuilder();
        final DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSS");
        final String timestamp = LocalDateTime.now().format(formatter);

        try (
                Socket socket = openSocket(inetAddress, port);
                BufferedReader reader = new BufferedReader(new InputStreamReader(socket.getInputStream()));
                PrintWriter writer = new PrintWriter(socket.getOutputStream(), true)
        ) {
            transcript.append(readAndLog(reader)).append('\n');

            boolean implicitTls = (port == 465 || port == 2465);

            if (!implicitTls) {
                String ehloResponse = sendAndLog("EHLO syfer25.com", reader, writer);
                transcript.append(ehloResponse).append('\n');

                if (ehloResponse.toLowerCase().contains("starttls")) {
                    tlsSupported = true;
                    transcript.append(sendAndLog("STARTTLS", reader, writer)).append('\n');

                    try (
                            SSLSocket tlsSocket = (SSLSocket) upgradeToTls(socket, mxHost);
                            BufferedReader tlsReader = new BufferedReader(new InputStreamReader(tlsSocket.getInputStream()));
                            PrintWriter tlsWriter = new PrintWriter(tlsSocket.getOutputStream(), true)
                    ) {
                        tlsSocket.setEnabledProtocols(tlsSocket.getSupportedProtocols());
                        tlsSocket.setSoTimeout(timeoutMs);

                        transcript.append("<< TLS handshake successful\n");

                        transcript.append(sendAndLog("EHLO syfer25.com", tlsReader, tlsWriter)).append('\n');
                        transcript.append(sendAndLog("MAIL FROM:<validator@syfer25.com>", tlsReader, tlsWriter)).append('\n');

                        String rcptResponse = sendAndLog("RCPT TO:<" + email + ">", tlsReader, tlsWriter);
                        transcript.append(rcptResponse).append('\n');

                        int code = parseSmtpCode(rcptResponse);
                        SmtpRecipientStatus status = classifyResponse(code, rcptResponse);
                        String tag = generateDiagnosticTag(code, rcptResponse);

                        return new ValidationResult(status, code, rcptResponse, null, mxHost,
                                transcript.toString().trim(), timestamp, tag, tlsSupported, port);
                    }
                }
            }

            if (implicitTls) {
                transcript.append("<< Implicit TLS connection established\n");

                // Send EHLO after implicit TLS handshake, before MAIL FROM
                String ehloResponse = sendAndLog("EHLO syfer25.com", reader, writer);
                transcript.append(ehloResponse).append('\n');
            }

            transcript.append(sendAndLog("MAIL FROM:<validator@syfer25.com>", reader, writer)).append('\n');
            String rcptResponse = sendAndLog("RCPT TO:<" + email + ">", reader, writer);
            int code = parseSmtpCode(rcptResponse);
            SmtpRecipientStatus status = classifyResponse(code, rcptResponse);
            String tag = generateDiagnosticTag(code, rcptResponse);

            return new ValidationResult(status, code, rcptResponse, null, mxHost,
                    transcript.toString().trim(), timestamp, tag, tlsSupported || implicitTls, port);

        } catch (SocketTimeoutException e) {
            throw new IOException("Timeout on port " + port + ": " + e.getMessage(), e);
        }
    }

    private Socket openSocket(InetAddress inetAddress, int port) throws IOException {
        Socket socket;
        if (port == 465 || port == 2465) {
            SSLSocketFactory factory = (SSLSocketFactory) SSLSocketFactory.getDefault();
            socket = factory.createSocket(inetAddress, port);
            ((SSLSocket) socket).setEnabledProtocols(((SSLSocket) socket).getSupportedProtocols());
        } else {
            SocketAddress sockaddr = new InetSocketAddress(inetAddress, port);
            socket = new Socket();
            socket.setReuseAddress(true);
            socket.setKeepAlive(true);
            socket.connect(sockaddr, timeoutMs);
        }
        socket.setSoTimeout(timeoutMs);
        return socket;
    }

    private Socket upgradeToTls(Socket plainSocket, String mxHost) throws IOException {
        SSLSocketFactory factory = (SSLSocketFactory) SSLSocketFactory.getDefault();
        SSLSocket sslSocket = (SSLSocket) factory.createSocket(plainSocket, mxHost, plainSocket.getPort(), true);
        sslSocket.setEnabledProtocols(sslSocket.getSupportedProtocols());
        sslSocket.startHandshake();
        return sslSocket;
    }

    private String sendAndLog(String command, BufferedReader reader, PrintWriter writer) throws IOException {
        writer.println(command);
        writer.flush();
        String response = readFullResponse(reader);
        return ">> " + command + "\n<< " + response;
    }

    private String readAndLog(BufferedReader reader) throws IOException {
        String response = readFullResponse(reader);
        return "<< " + response;
    }

    private String readFullResponse(BufferedReader reader) throws IOException {
        StringBuilder response = new StringBuilder();
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
        String last = lines[lines.length - 1].trim();
        if (last.startsWith("<< ")) last = last.substring(3).trim();
        try {
            return Integer.parseInt(last.substring(0, 3));
        } catch (NumberFormatException e) {
            return -1;
        }
    }

    private SmtpRecipientStatus classifyResponse(int code, String response) {
        String lower = response != null ? response.toLowerCase() : "";
        if (code >= 250 && code <= 259) return SmtpRecipientStatus.Valid;
        if (code == 252 || (code >= 400 && code < 500)) return SmtpRecipientStatus.TemporaryFailure;
        if (code == 550 || lower.contains("user unknown") || lower.contains("no such user"))
            return SmtpRecipientStatus.UserNotFound;
        if (lower.contains("blacklist") || lower.contains("spamhaus") || lower.contains("blocked"))
            return SmtpRecipientStatus.Blacklisted;
        return SmtpRecipientStatus.UnknownFailure;
    }

    private String generateDiagnosticTag(int code, String response) {
        if (code == 250) return "Accepted";
        if (code == 550) return "UserNotFound";
        if (code == 554) return "Rejected";
        if (code == 451) return "Temporary";
        if (response != null && response.toLowerCase().contains("blacklist")) return "BlockedByBlacklist";
        return "Unclassified";
    }

    private String getStackTrace(Throwable throwable) {
        StringWriter sw = new StringWriter();
        PrintWriter pw = new PrintWriter(sw);
        throwable.printStackTrace(pw);
        return sw.toString();
    }

    /**
     * Check catch-all by sending RCPT TO for a guaranteed non-existing address.
     */
    public boolean checkSmtpCatchAllSingleSession(String mxHost, String testEmail, String domain) throws IOException {
        ValidationResult result = validateRecipient(mxHost, testEmail);
        return result != null && result.getStatus() == SmtpRecipientStatus.Valid;
    }
}
