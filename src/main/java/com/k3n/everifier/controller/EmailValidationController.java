package com.k3n.everifier.controller;

import com.k3n.everifier.dto.EmailValidationResult;
import com.k3n.everifier.dto.EmailValidationResultResponse;
import com.k3n.everifier.model.main.EmailEntity;
import com.k3n.everifier.repository.main.emailrepository;
import com.k3n.everifier.services.EmailCacheService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import javax.validation.constraints.Email;
import javax.validation.constraints.NotEmpty;
import java.time.Instant;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executor;
import java.util.stream.Collectors;

@RestController
@RequestMapping("/email")
@Validated
public class EmailValidationController {

    private static final Logger logger = LoggerFactory.getLogger(EmailValidationController.class);

    private final EmailCacheService emailCacheService;
    private final Executor taskExecutor;
    private final emailrepository emailRepository;

    @Autowired
    public EmailValidationController(EmailCacheService emailCacheService,
                                     emailrepository emailRepository,
                                     Executor taskExecutor) {
        this.emailCacheService = emailCacheService;
        this.emailRepository = emailRepository;
        this.taskExecutor = taskExecutor;
    }

    // 1. Validate Single Email with Cache
    @GetMapping("/validate")
    public ResponseEntity<?> validateSingleEmail(@RequestParam @NotEmpty @Email String email) {
        try {
            EmailValidationResult result = emailCacheService.fetchValidationResult(email);
            return ResponseEntity.ok(result);
        } catch (Exception e) {
            logger.error("Error validating email {}: {}", email, e.getMessage(), e);
            return ResponseEntity.status(500)
                    .body(Collections.singletonMap("error", "Internal error validating email."));
        }
    }

    // 2. Validate and Store Single Email if First-Time
    @PostMapping("/validate-store")
    public ResponseEntity<?> validateAndStoreEmail(@RequestParam @NotEmpty @Email String email) {
        try {
            if (emailRepository.existsByEmail(email)) {
                return ResponseEntity.ok(Collections.singletonMap("message", "Email already validated and stored."));
            }
            EmailValidationResult result = emailCacheService.fetchValidationResult(email);
            if (result == null || (!"Valid".equalsIgnoreCase(result.getCategory()) && !"Success".equalsIgnoreCase(result.getCategory()))) {
                return ResponseEntity.badRequest().body(Collections.singletonMap("error", "Invalid or failed validation."));
            }

            EmailEntity entity = new EmailEntity();
            entity.setEmail(email);
            entity.setProcessed(false);
            entity.setValidatedAt(Instant.now());
            emailRepository.save(entity);

            return ResponseEntity.ok(Collections.singletonMap("message", "Email validated and stored."));
        } catch (Exception e) {
            logger.error("Error validating/storing email {}: {}", email, e.getMessage(), e);
            return ResponseEntity.status(500)
                    .body(Collections.singletonMap("error", "Internal error validating and storing email."));
        }
    }

    // 3. Async Batch Validate and Store Emails
    @PostMapping("/batch-validate-store")
    public ResponseEntity<?> batchValidateStoreAsync(@RequestBody @NotEmpty List<@Email String> emails) {
        List<CompletableFuture<EmailValidationResult>> futures = emails.stream()
                .map(email -> CompletableFuture.supplyAsync(() -> {
                    try {
                        logger.info("Starting validation for email: {}", email);

                        if (emailRepository.existsByEmail(email)) {
                            EmailValidationResult existing = new EmailValidationResult();
                            existing.setEmail(email);
                            existing.setCategory("Already Stored");
                            logger.info("Email {} already stored", email);
                            return existing;
                        }

                        EmailValidationResult validationResult = emailCacheService.fetchValidationResult(email);
                        if (validationResult == null) {
                            logger.warn("Validation result null for email: {}", email);
                        } else {
                            logger.info("Validation result for {}: category={}", email, validationResult.getCategory());
                        }

                        if (validationResult == null ||
                                (!"Valid".equalsIgnoreCase(validationResult.getCategory()) && !"Success".equalsIgnoreCase(validationResult.getCategory()))) {
                            EmailValidationResult invalid = new EmailValidationResult();
                            invalid.setEmail(email);
                            invalid.setCategory("Invalid");
                            invalid.setErrors("Validation failed");
                            logger.info("Validation failed for email: {}", email);
                            return invalid;
                        }

                        EmailEntity entity = new EmailEntity();
                        entity.setEmail(email);
                        entity.setValidatedAt(Instant.now());
                        entity.setProcessed(false);
                        emailRepository.save(entity);
                        logger.info("Stored validated email: {}", email);

                        return validationResult;
                    } catch (Exception e) {
                        logger.error("Error processing email {}: {}", email, e.getMessage(), e);
                        EmailValidationResult errorResult = new EmailValidationResult();
                        errorResult.setEmail(email);
                        errorResult.setCategory("Error");
                        errorResult.setErrors(e.getMessage());
                        return errorResult;
                    }
                }, taskExecutor))
                .collect(Collectors.toList());

        CompletableFuture.allOf(futures.toArray(new CompletableFuture[0])).join();

        List<EmailValidationResult> results = futures.stream()
                .map(CompletableFuture::join)
                .collect(Collectors.toList());

        return ResponseEntity.ok(results);
    }

    // 4. Get Cached Validation Results by Category
    @GetMapping("/validation-results/by-category")
    public ResponseEntity<EmailValidationResultResponse> getCachedEmailsByCategory(@RequestParam String category) {
        List<EmailValidationResult> filtered = emailCacheService.getCachedEmailsByCategory(category);
        EmailValidationResultResponse response = new EmailValidationResultResponse(
                "success",
                "Fetched cached emails for category: " + category,
                filtered);
        return ResponseEntity.ok(response);
    }
}
