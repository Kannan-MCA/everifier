package com.k3n.everifier.util;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import javax.net.ssl.SSLSocket;
import javax.net.ssl.SSLSocketFactory;
import javax.naming.directory.InitialDirContext;
import javax.naming.directory.Attributes;
import javax.naming.directory.Attribute;
import javax.naming.NamingException;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.PrintWriter;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;

import java.util.concurrent.*;

@Component
public class SmtpRcptValidator {

    private static final Logger logger = LoggerFactory.getLogger(SmtpRcptValidator.class);

    private static final int TIMEOUT_MS = 15000; // 15 seconds timeout
    private static final int[] SMTP_PORTS = {25, 587, 465};

    public boolean checkSmtpCatchAllSingleSession(String mxHost, String testEmail, String domain) {
        try {
            ValidationResult result = validateRecipient(testEmail);
            // Assuming if the result status is Valid, it's a catch-all
            return result != null && result.getStatus() == SmtpRecipientStatus.Valid;
        } catch (IOException e) {
            // Log or handle as needed
            return false;
        }
    }

    public enum SmtpRecipientStatus {
        Valid, UserNotFound, TemporaryFailure, UnknownFailure, Blacklisted, UncertainDueToCatchAll, InvalidFormat, NoMxRecord
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

        public boolean isTlsSupported() {
            return tlsSupported;
        }

        public boolean isCatchAllDomain() {
            return isCatchAllDomain;
        }

        private final boolean tlsSupported;

        public int getPortUsed() {
            return portUsed;
        }

        private final int portUsed;
        private final boolean isCatchAllDomain;

        public ValidationResult(SmtpRecipientStatus status, int smtpCode, String smtpResponse,
                                String errorMessage, String mxHost, String fullTranscript,
                                String timestamp, String diagnosticTag,
                                boolean tlsSupported, int portUsed, boolean isCatchAllDomain) {
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
            this.isCatchAllDomain = isCatchAllDomain;
        }

        public SmtpRecipientStatus getStatus() { return status; }
        public int getSmtpCode() { return smtpCode; }
        public String getSmtpResponse() { return smtpResponse; }
        public String getErrorMessage() { return errorMessage; }
        public String getMxHost() { return mxHost; }
        public String getFullTranscript() { return fullTranscript; }
        public String getTimestamp() { return timestamp; }
        public String getDiagnosticTag() { return diagnosticTag; }
    }

    public ValidationResult validateRecipient(String email) throws IOException {
        if (email == null || !email.contains("@")) {
            return new ValidationResult(SmtpRecipientStatus.InvalidFormat, -1, null,
                    "Invalid email format", null, "", LocalDateTime.now().toString(),
                    "InvalidFormat", false, -1, false);
        }

        String domain = email.substring(email.indexOf('@') + 1);

        String mxHost;
        InetAddress inetAddress;
        try {
            mxHost = resolveMxHostOrThrow(domain);
            inetAddress = InetAddress.getByName(mxHost);
            logger.info("Resolved MX host {} to IP {}", mxHost, inetAddress.getHostAddress());
        } catch (IOException e) {
            return new ValidationResult(SmtpRecipientStatus.NoMxRecord, -1, null,
                    "MX lookup failed: " + e.getMessage(), domain, "", LocalDateTime.now().toString(),
                    "NoMxRecord", false, -1, false);
        }

        ParallelPortChecker portChecker = new ParallelPortChecker(SMTP_PORTS, port -> attemptValidation(inetAddress, mxHost, email, port));
        try {
            return portChecker.checkAllPorts();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return new ValidationResult(SmtpRecipientStatus.UnknownFailure, -1, "Validation interrupted",
                    "Interrupted", mxHost, "", LocalDateTime.now().toString(),
                    "Interrupted", false, -1, false);
        }
    }

    private String resolveMxHostOrThrow(String domain) throws IOException {
        try {
            InitialDirContext iDirContext = new InitialDirContext();
            Attributes attributes = iDirContext.getAttributes("dns:/" + domain, new String[]{"MX"});
            Attribute attribute = attributes.get("MX");
            if (attribute == null) {
                throw new IOException("No MX records for domain " + domain);
            }
            String mxRecord = (String) attribute.get(0);
            String mxHost = mxRecord.substring(mxRecord.indexOf(' ') + 1).trim();
            if (mxHost.endsWith(".")) {
                mxHost = mxHost.substring(0, mxHost.length() - 1);
            }
            return mxHost;
        } catch (NamingException e) {
            throw new IOException("MX lookup failed: " + e.getMessage(), e);
        }
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
            transcript.append(readFullResponse(reader)).append('\n');

            boolean implicitTls = (port == 465 || port == 2465);

            if (!implicitTls) {
                String ehloResponse = sendAndLog("EHLO validator.com", reader, writer);
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
                        tlsSocket.setSoTimeout(TIMEOUT_MS);

                        transcript.append("<< TLS handshake successful\n");

                        transcript.append(sendAndLog("EHLO validator.com", tlsReader, tlsWriter)).append('\n');
                        transcript.append(sendAndLog("MAIL FROM:<validator@validator.com>", tlsReader, tlsWriter)).append('\n');

                        String rcptResponse = sendAndLog("RCPT TO:<" + email + ">", tlsReader, tlsWriter);
                        transcript.append(rcptResponse).append('\n');

                        int code = parseSmtpCode(rcptResponse);
                        String enhancedCode = parseEnhancedSmtpCode(rcptResponse);
                        SmtpRecipientStatus status = SmtpResponseClassifier.classifyResponse(code, enhancedCode, rcptResponse);
                        String tag = SmtpResponseClassifier.generateDiagnosticTag(code, rcptResponse);
                        return new ValidationResult(status, code, rcptResponse, null, mxHost,
                                transcript.toString().trim(), timestamp, tag, tlsSupported, port, false);
                    }
                }
            }

            if (implicitTls) {
                transcript.append("<< Implicit TLS connection established\n");
                String ehloResponse = sendAndLog("EHLO validator.com", reader, writer);
                transcript.append(ehloResponse).append('\n');
            }

            transcript.append(sendAndLog("MAIL FROM:<validator@validator.com>", reader, writer)).append('\n');
            String rcptResponse = sendAndLog("RCPT TO:<" + email + ">", reader, writer);
            int code = parseSmtpCode(rcptResponse);
            String enhancedCode = parseEnhancedSmtpCode(rcptResponse);
            SmtpRecipientStatus status = SmtpResponseClassifier.classifyResponse(code, enhancedCode, rcptResponse);
            String tag = SmtpResponseClassifier.generateDiagnosticTag(code, rcptResponse);

            return new ValidationResult(status, code, rcptResponse, null, mxHost,
                    transcript.toString().trim(), timestamp, tag, tlsSupported || implicitTls, port, false);

        } catch (IOException e) {
            throw e;
        }
    }

    private Socket openSocket(InetAddress inetAddress, int port) throws IOException {
        if (port == 465 || port == 2465) {
            SSLSocketFactory factory = (SSLSocketFactory) SSLSocketFactory.getDefault();
            SSLSocket socket = (SSLSocket) factory.createSocket(inetAddress, port);
            socket.setEnabledProtocols(socket.getSupportedProtocols());
            socket.setSoTimeout(TIMEOUT_MS);
            return socket;
        } else {
            Socket socket = new Socket();
            socket.setReuseAddress(true);
            socket.setKeepAlive(true);
            socket.connect(new InetSocketAddress(inetAddress, port), TIMEOUT_MS);
            socket.setSoTimeout(TIMEOUT_MS);
            return socket;
        }
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

    private String readFullResponse(BufferedReader reader) throws IOException {
        StringBuilder response = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) {
            response.append(line).append('\n');
            if (line.length() < 4 || line.charAt(3) != '-') break;
        }
        return response.toString().trim();
    }

    private int parseSmtpCode(String response) {
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

    private String parseEnhancedSmtpCode(String response) {
        if (response == null) return "";
        String[] lines = response.split("\n");
        String last = lines[lines.length - 1].trim();
        if (last.startsWith("<< ")) last = last.substring(3).trim();
        String[] parts = last.split(" ");
        if (parts.length >= 2 && parts[1].matches("\\d\\.\\d\\.\\d")) {
            return parts[1];
        }
        return "";
    }
}
