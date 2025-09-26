package com.k3n.everifier.controller;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.k3n.everifier.dto.EmailValidationResult;
import com.k3n.everifier.model.main.EmailEntity;
import com.k3n.everifier.model.cache.EmailVerificationResultEntity;
import com.k3n.everifier.repository.main.emailrepository;
import com.k3n.everifier.repository.cache.emailverificationresultrepository;
import com.k3n.everifier.services.MXLookupService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/email")
public class EmailValidationController {

    private static final Logger logger = LoggerFactory.getLogger(EmailValidationController.class);

    private final MXLookupService mxLookupService;
    private final ObjectMapper objectMapper;
    private final emailrepository emailRepository;
    private final emailverificationresultrepository resultRepository;

        @Autowired
    public EmailValidationController(MXLookupService mxLookupService, ObjectMapper objectMapper,
                                     emailrepository emailRepository,
                                     emailverificationresultrepository resultRepository) {
        this.mxLookupService = mxLookupService;
        this.objectMapper = objectMapper;
        this.emailRepository = emailRepository;
        this.resultRepository = resultRepository;
    }

    /**
     * Verifies a single email address and returns detailed validation result.
     *
     * @param email Email address to verify
     * @return EmailValidationResult with full details
     */
    @GetMapping
    public ResponseEntity<?> verifySingleEmail(@RequestParam("email") String email) {
        try {
            EmailValidationResult result = mxLookupService.categorizeEmail(email);
            return ResponseEntity.ok(result);
        } catch (Exception ex) {
            logger.error("Error verifying email {}: {}", email, ex.getMessage());
            return ResponseEntity.status(500).body(errorResponse("Internal error processing email."));
        }
    }

    /**
     * Verifies a batch of emails provided in the request body.
     * Saves results in database with JSON serialized result.
     *
     * @param emails List of email addresses to verify
     * @return Confirmation message
     */
    @PostMapping("/batch")
    public ResponseEntity<?> verifyBatchEmails(@RequestBody List<String> emails) {
        if (emails == null || emails.isEmpty()) {
            return ResponseEntity.badRequest().body(errorResponse("Email list must not be empty."));
        }

        for (String email : emails) {
            try {
                EmailValidationResult result = mxLookupService.categorizeEmail(email);
                saveVerificationResult(email, result);
            } catch (Exception e) {
                logger.warn("Failed to process email {}: {}", email, e.getMessage());
            }
        }
        return ResponseEntity.ok(successResponse("Processed and stored email validation results."));
    }

    /**
     * Processes all emails stored in database.
     * Runs validation and saves the results.
     *
     * @return Confirmation message
     */
    @PostMapping("/process-from-db")
    public ResponseEntity<?> processEmailsFromDb() {
        List<EmailEntity> emails = emailRepository.findAll();
        if (emails == null || emails.isEmpty()) {
            return ResponseEntity.ok(successResponse("No emails found to process."));
        }

        for (EmailEntity emailEntity : emails) {
            String email = emailEntity.getEmail();
            try {
                EmailValidationResult result = mxLookupService.categorizeEmail(email);
                saveVerificationResult(email, result);
            } catch (Exception e) {
                logger.warn("Failed to process email {}: {}", email, e.getMessage());
            }
        }

        return ResponseEntity.ok(successResponse("Processed and stored email validation results."));
    }

    /**
     * Saves serialized EmailValidationResult as JSON in the database.
     *
     * @param email  Email address
     * @param result EmailValidationResult object
     */
    private void saveVerificationResult(String email, EmailValidationResult result) {
        try {
            String jsonResult = objectMapper.writeValueAsString(result);
            EmailVerificationResultEntity resultEntity = new EmailVerificationResultEntity();
            resultEntity.setEmail(email);
            resultEntity.setVerificationResultJson(jsonResult);
            resultRepository.save(resultEntity);
        } catch (JsonProcessingException e) {
            logger.error("Error serializing validation result for email {}: {}", email, e.getMessage());
        }
    }

    /**
     * Builds a standardized error response.
     *
     * @param message Error message
     * @return Map with error key
     */
    private Map<String, String> errorResponse(String message) {
        Map<String, String> response = new HashMap<>();
        response.put("error", message);
        return response;
    }

    /**
     * Builds a standardized success response.
     *
     * @param message Success message
     * @return Map with message key
     */
    private Map<String, String> successResponse(String message) {
        Map<String, String> response = new HashMap<>();
        response.put("message", message);
        return response;
    }
}
