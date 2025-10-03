package com.k3n.everifier.controller;

import com.k3n.everifier.dto.EmailValidationResult;
import com.k3n.everifier.model.main.EmailEntity;
import com.k3n.everifier.services.EmailCacheService;
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

    private final EmailCacheService emailCacheService;
    private final Executor taskExecutor;
    private final com.k3n.everifier.repository.main.emailrepository emailRepository;

    @Autowired
    public EmailValidationController(EmailCacheService emailCacheService,
                                     com.k3n.everifier.repository.main.emailrepository emailRepository,
                                     Executor taskExecutor) {
        this.emailCacheService = emailCacheService;
        this.emailRepository = emailRepository;
        this.taskExecutor = taskExecutor;
    }

    /** Validate single email with cache TTL-aware */
    @GetMapping
    public ResponseEntity<?> verifySingleEmail(@RequestParam @NotEmpty @Email String email) {
        try {
            EmailValidationResult result = emailCacheService.fetchValidationResult(email);
            return ResponseEntity.ok(result);
        } catch (Exception ex) {
            logger.error("Error verifying email {}: {}", email, ex.getMessage(), ex);
            return ResponseEntity.status(500).body(singletonError("Internal error processing email."));
        }
    }

    /** Async batch validation endpoint with concurrency control using cache-aware fetch */
    @PostMapping("/batch-async")
    public ResponseEntity<?> verifyBatchEmailsAsync(@RequestBody @NotEmpty List<@Email String> emails) {
        List<CompletableFuture<EmailValidationResult>> futures = emails.stream()
                .map(email -> CompletableFuture.supplyAsync(() -> {
                    try {
                        return emailCacheService.fetchValidationResult(email);
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

    /** Async processing of all emails fetched from DB with caching */
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
                    return emailCacheService.fetchValidationResult(email);
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

    private static Map<String, String> singletonError(String message) {
        return java.util.Collections.singletonMap("error", message);
    }

    private static Map<String, String> singletonSuccess(String message) {
        return java.util.Collections.singletonMap("message", message);
    }
}
