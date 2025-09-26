package com.k3n.everifier.services;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.k3n.everifier.dto.EmailValidationResult;
import com.k3n.everifier.model.main.EmailEntity;
import com.k3n.everifier.model.cache.EmailVerificationResultEntity;
import com.k3n.everifier.repository.main.emailrepository;
import com.k3n.everifier.repository.cache.emailverificationresultrepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class EmailValidationScheduler {

    private static final Logger logger = LoggerFactory.getLogger(EmailValidationScheduler.class);

    private final emailrepository emailRepository;
    private final emailverificationresultrepository resultRepository;
    private final MXLookupService mxLookupService;
    private final ObjectMapper objectMapper;

    @Autowired
    public EmailValidationScheduler(emailrepository emailRepository,
                                    emailverificationresultrepository resultRepository,
                                    MXLookupService mxLookupService,
                                    ObjectMapper objectMapper) {
        this.emailRepository = emailRepository;
        this.resultRepository = resultRepository;
        this.mxLookupService = mxLookupService;
        this.objectMapper = objectMapper;
    }

    /**
     * Scheduled task runs every minute (adjust cron or fixedDelay as needed).
     * Looks for unprocessed emails and validates them.
     */
    @Scheduled(fixedDelayString = "${email.validation.interval.ms:60000}")
    public void processNewEmails() {
        List<EmailEntity> newEmails = emailRepository.findByProcessedFalse(); // Define in repo

        if (newEmails == null || newEmails.isEmpty()) {
            logger.info("No new emails to process");
            return;
        }

        for (EmailEntity emailEntity : newEmails) {
            String email = emailEntity.getEmail();
            try {
                logger.info("Validating new email: {}", email);
                EmailValidationResult result = mxLookupService.categorizeEmail(email);
                saveVerificationResult(email, result);
                emailEntity.setProcessed(true);  // Mark processed, add this field in EmailEntity
                emailRepository.save(emailEntity);
            } catch (Exception e) {
                logger.error("Error validating email {}: {}", email, e.getMessage());
            }
        }
    }

    private void saveVerificationResult(String email, EmailValidationResult result) {
        try {
            String jsonResult = objectMapper.writeValueAsString(result);
            EmailVerificationResultEntity resultEntity = new EmailVerificationResultEntity();
            resultEntity.setEmail(email);
            resultEntity.setVerificationResultJson(jsonResult);
            resultRepository.save(resultEntity);
        } catch (Exception e) {
            logger.error("Failed to save validation result for email {}: {}", email, e.getMessage());
        }
    }
}
