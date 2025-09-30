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
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import reactor.core.publisher.Flux;

import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.stream.Collectors;

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

    @GetMapping
    public ResponseEntity<?> verifySingleEmail(@RequestParam("email") String email) {
        try {
            EmailValidationResult result = mxLookupService.categorizeEmail(email);
            saveVerificationResult(email, result);
            return ResponseEntity.ok(result);
        } catch (Exception ex) {
            logger.error("Error verifying email {}: {}", email, ex.getMessage(), ex);
            return ResponseEntity.status(500).body(errorResponse("Internal error processing email."));
        }
    }

    @PostMapping(value = "/stream-batch", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public Flux<EmailValidationResult> streamBatchEmails(@RequestBody List<String> emails) {
        if (emails == null || emails.isEmpty()) {
            return Flux.error(new IllegalArgumentException("Email list must not be empty."));
        }
        return Flux.fromIterable(emails)
                .map(email -> {
                    try {
                        EmailValidationResult result = mxLookupService.categorizeEmail(email);
                        saveVerificationResult(email, result);
                        return result;
                    } catch (Exception e) {
                        logger.warn("Failed processing email {}: {}", email, e.getMessage(), e);
                        EmailValidationResult errorResult = new EmailValidationResult();
                        errorResult.setEmail(email);
                        errorResult.setCategory("Error");
                        errorResult.setErrors(e.getMessage());
                        return errorResult;
                    }
                });
    }

    @PostMapping("/batch")
    public ResponseEntity<?> verifyBatchEmails(@RequestBody List<String> emails) {
        if (emails == null || emails.isEmpty()) {
            return ResponseEntity.badRequest().body(errorResponse("Email list must not be empty."));
        }
        List<EmailValidationResult> results = new ArrayList<>();
        for (String email : emails) {
            try {
                EmailValidationResult result = mxLookupService.categorizeEmail(email);
                saveVerificationResult(email, result);
                results.add(result);
            } catch (Exception e) {
                logger.warn("Failed processing email {}: {}", email, e.getMessage(), e);
                EmailValidationResult errorResult = new EmailValidationResult();
                errorResult.setEmail(email);
                errorResult.setCategory("Error");
                errorResult.setErrors(e.getMessage());
                results.add(errorResult);
            }
        }
        return ResponseEntity.ok(results);
    }

    // New async batch endpoint
    @PostMapping("/batch-async")
    public ResponseEntity<?> verifyBatchEmailsAsync(@RequestBody List<String> emails) {
        if (emails == null || emails.isEmpty()) {
            return ResponseEntity.badRequest().body(errorResponse("Email list must not be empty."));
        }
        List<CompletableFuture<EmailValidationResult>> futures = emails.stream()
                .map(email -> mxLookupService.categorizeEmailAsync(email)
                        .thenApply(result -> {
                            saveVerificationResult(email, result);
                            return result;
                        })
                        .exceptionally(ex -> {
                            logger.warn("Failed to process email {}: {}", email, ex.getMessage(), ex);
                            EmailValidationResult errorResult = new EmailValidationResult();
                            errorResult.setEmail(email);
                            errorResult.setCategory("Error");
                            errorResult.setErrors(ex.getMessage());
                            return errorResult;
                        }))
                .collect(Collectors.toList());

        CompletableFuture.allOf(futures.toArray(new CompletableFuture[0])).join();

        List<EmailValidationResult> results = futures.stream()
                .map(CompletableFuture::join)
                .collect(Collectors.toList());

        return ResponseEntity.ok(results);
    }

    @PostMapping("/process-from-db")
    public ResponseEntity<?> processEmailsFromDb() {
        List<EmailEntity> emails = emailRepository.findAll();
        if (emails == null || emails.isEmpty()) {
            return ResponseEntity.ok(successResponse("No emails found to process."));
        }
        List<EmailValidationResult> results = new ArrayList<>();
        for (EmailEntity emailEntity : emails) {
            String email = emailEntity.getEmail();
            try {
                EmailValidationResult result = mxLookupService.categorizeEmail(email);
                saveVerificationResult(email, result);
                results.add(result);
            } catch (Exception e) {
                logger.warn("Failed to process email {}: {}", email, e.getMessage(), e);
                EmailValidationResult errorResult = new EmailValidationResult();
                errorResult.setEmail(email);
                errorResult.setCategory("Error");
                errorResult.setErrors(e.getMessage());
                results.add(errorResult);
            }
        }
        return ResponseEntity.ok(results);
    }

    private void saveVerificationResult(String email, EmailValidationResult result) {
        try {
            if (resultRepository.findByEmail(email).isPresent()) {
                logger.info("Skipping duplicate email: {}", email);
                return;
            }
            String jsonResult = objectMapper.writeValueAsString(result);
            EmailVerificationResultEntity resultEntity = new EmailVerificationResultEntity();
            resultEntity.setEmail(email);
            resultEntity.setVerificationResultJson(jsonResult);
            resultRepository.save(resultEntity);
        } catch (JsonProcessingException e) {
            logger.error("Error serializing validation result for email {}: {}", email, e.getMessage(), e);
        }
    }

    private Map<String, String> errorResponse(String message) {
        Map<String, String> response = new HashMap<>();
        response.put("error", message);
        return response;
    }

    private Map<String, String> successResponse(String message) {
        Map<String, String> response = new HashMap<>();
        response.put("message", message);
        return response;
    }
}
