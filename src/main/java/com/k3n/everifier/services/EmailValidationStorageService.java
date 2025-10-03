package com.k3n.everifier.services;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.k3n.everifier.dto.EmailValidationResult;
import com.k3n.everifier.model.main.EmailEntity;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;

@Service
public class EmailValidationStorageService {

    @Autowired
    private com.k3n.everifier.repository.main.emailrepository emailRepository;

    @Autowired
    private com.k3n.everifier.services.EmailCacheService emailCacheService;

    /**
     * Validates the given email ID and if validated for the very first time,
     * stores it in the primary database.
     *
     * @param email The email ID to validate and store.
     * @return true if the email is validated and stored or already exists; false if validation fails.
     */
    @Transactional
    public boolean validateAndStoreFirstTime(String email) {
        // Check if already stored
        if (emailRepository.existsByEmail(email)) {
            return true; // Already exists, consider validated
        }

        // Validate email through existing cache or validation service
        EmailValidationResult validationResult = null;
        try {
            validationResult = emailCacheService.fetchValidationResult(email);
        } catch (JsonProcessingException e) {
            throw new RuntimeException(e);
        }

        if (validationResult == null) {
            return false; // Could not validate
        }

        // Assuming "Valid" or "Success" category indicates a validated email
        String category = validationResult.getCategory();
        if (!"Valid".equalsIgnoreCase(category) && !"Success".equalsIgnoreCase(category)) {
            return false; // Validation failed
        }

        // Save to primary DB
        EmailEntity newEmail = new EmailEntity();
        newEmail.setEmail(email);
        newEmail.setValidatedAt(Instant.ofEpochMilli(System.currentTimeMillis()));
        emailRepository.save(newEmail);

        return true;
    }
}
