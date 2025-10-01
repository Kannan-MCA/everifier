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
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import javax.validation.constraints.Email;
import javax.validation.constraints.NotEmpty;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executor;
import java.util.stream.Collectors;

@RestController
@RequestMapping("/email")
@Validated
public class EmailValidationController {

    private static final Logger logger = LoggerFactory.getLogger(EmailValidationController.class);

    private final MXLookupService mxLookupService;
    private final ObjectMapper objectMapper;
    private final emailrepository emailRepository;
    private final emailverificationresultrepository resultRepository;
    private final Executor taskExecutor;

    @Autowired
    public EmailValidationController(MXLookupService mxLookupService, ObjectMapper objectMapper,
                                     emailrepository emailRepository,
                                     emailverificationresultrepository resultRepository,
                                     Executor taskExecutor) {
        this.mxLookupService = mxLookupService;
        this.objectMapper = objectMapper;
        this.emailRepository = emailRepository;
        this.resultRepository = resultRepository;
        this.taskExecutor = taskExecutor;
    }

    /** Validate single email synchronously and save result */
    @GetMapping
    public ResponseEntity<?> verifySingleEmail(@RequestParam @NotEmpty @Email String email) {
        try {
            EmailValidationResult result = mxLookupService.categorizeEmail(email);
            saveVerificationResult(email, result);
            return ResponseEntity.ok(result);
        } catch (Exception ex) {
            logger.error("Error verifying email {}: {}", email, ex.getMessage(), ex);
            return ResponseEntity.status(500).body(singletonError("Internal error processing email."));
        }
    }

    /** Async batch validation endpoint with concurrency control */
    @PostMapping("/batch-async")
    public ResponseEntity<?> verifyBatchEmailsAsync(@RequestBody @NotEmpty List<@Email String> emails) {
        List<CompletableFuture<EmailValidationResult>> futures = emails.stream()
                .map(email -> CompletableFuture.supplyAsync(() -> {
                    try {
                        EmailValidationResult result = mxLookupService.categorizeEmail(email);
                        saveVerificationResult(email, result);
                        return result;
                    } catch (Exception ex) {
                        logger.warn("Failed to process email {}: {}", email, ex.getMessage(), ex);
                        EmailValidationResult errorResult = new EmailValidationResult();
                        errorResult.setEmail(email);
                        errorResult.setCategory("Error");
                        errorResult.setErrors(ex.getMessage());
                        return errorResult;
                    }
                }, taskExecutor))
                .collect(Collectors.toList());

        CompletableFuture.allOf(futures.toArray(new CompletableFuture[0])).join();

        List<EmailValidationResult> results = futures.stream().map(CompletableFuture::join).collect(Collectors.toList());

        return ResponseEntity.ok(results);
    }

    /** Async processing of all emails fetched from DB with concurrency control */
    @PostMapping("/process-from-db")
    public ResponseEntity<?> processEmailsFromDb() {
        List<EmailEntity> emails = emailRepository.findAll();
        if (emails.isEmpty()) {
            return ResponseEntity.ok(singletonSuccess("No emails found to process."));
        }

        List<CompletableFuture<EmailValidationResult>> futures = new ArrayList<>();
        for (EmailEntity entity : emails) {
            final String email = entity.getEmail();
            futures.add(CompletableFuture.supplyAsync(() -> {
                try {
                    EmailValidationResult result = mxLookupService.categorizeEmail(email);
                    saveVerificationResult(email, result);
                    return result;
                } catch (Exception ex) {
                    logger.warn("Failed to process email {}: {}", email, ex.getMessage(), ex);
                    EmailValidationResult errorResult = new EmailValidationResult();
                    errorResult.setEmail(email);
                    errorResult.setCategory("Error");
                    errorResult.setErrors(ex.getMessage());
                    return errorResult;
                }
            }, taskExecutor));
        }

        CompletableFuture.allOf(futures.toArray(new CompletableFuture[0])).join();

        List<EmailValidationResult> results = futures.stream().map(CompletableFuture::join).collect(Collectors.toList());

        return ResponseEntity.ok(results);
    }

    /** Save result in repository if not already present */
    private void saveVerificationResult(String email, EmailValidationResult result) {
        try {
            if (resultRepository.findByEmail(email).isPresent()) {
                logger.info("Skipping duplicate email: {}", email);
                return;
            }
            String json = objectMapper.writeValueAsString(result);
            EmailVerificationResultEntity entity = new EmailVerificationResultEntity();
            entity.setEmail(email);
            entity.setVerificationResultJson(json);
            resultRepository.save(entity);
        } catch (JsonProcessingException e) {
            logger.error("Error serializing result for email {}: {}", email, e.getMessage(), e);
        }
    }

    private static Map<String, String> singletonError(String message) {
        return java.util.Collections.singletonMap("error", message);
    }

    private static Map<String, String> singletonSuccess(String message) {
        return java.util.Collections.singletonMap("message", message);
    }
}