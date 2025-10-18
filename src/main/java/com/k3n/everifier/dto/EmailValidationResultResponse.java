package com.k3n.everifier.dto;

import java.util.List;

public class EmailValidationResultResponse {

    private String status;
    private String message;
    private List<EmailValidationResult> data;

    public EmailValidationResultResponse(String status, String message, List<EmailValidationResult> data) {
        this.status = status;
        this.message = message;
        this.data = data;
    }

    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }

    public String getMessage() { return message; }
    public void setMessage(String message) { this.message = message; }

    public List<EmailValidationResult> getData() { return data; }
    public void setData(List<EmailValidationResult> data) { this.data = data; }
}
