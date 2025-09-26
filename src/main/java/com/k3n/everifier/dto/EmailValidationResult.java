package com.k3n.everifier.dto;

public class EmailValidationResult {
    private String email;
    private String category;
    private String diagnosticTag;
    private int smtpCode;
    private String status;
    private String transcript;
    private String mailHost;
    private boolean portOpened;
    private boolean connectionSuccessful;
    private String errors;
    private boolean catchAll;
    private String timestamp;

    public String getEmail() { return email; }
    public void setEmail(String email) { this.email = email; }
    public String getCategory() { return category; }
    public void setCategory(String category) { this.category = category; }
    public String getDiagnosticTag() { return diagnosticTag; }
    public void setDiagnosticTag(String diagnosticTag) { this.diagnosticTag = diagnosticTag; }
    public int getSmtpCode() { return smtpCode; }
    public void setSmtpCode(int smtpCode) { this.smtpCode = smtpCode; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public String getTranscript() { return transcript; }
    public void setTranscript(String transcript) { this.transcript = transcript; }
    public String getMailHost() { return mailHost; }
    public void setMailHost(String mailHost) { this.mailHost = mailHost; }
    public boolean isPortOpened() { return portOpened; }
    public void setPortOpened(boolean portOpened) { this.portOpened = portOpened; }
    public boolean isConnectionSuccessful() { return connectionSuccessful; }
    public void setConnectionSuccessful(boolean connectionSuccessful) { this.connectionSuccessful = connectionSuccessful; }
    public String getErrors() { return errors; }
    public void setErrors(String errors) { this.errors = errors; }
    public boolean isCatchAll() { return catchAll; }
    public void setCatchAll(boolean catchAll) { this.catchAll = catchAll; }
    public String getTimestamp() { return timestamp; }
    public void setTimestamp(String timestamp) { this.timestamp = timestamp; }
}
