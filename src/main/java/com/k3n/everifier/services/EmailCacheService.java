package com.k3n.everifier.services;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.k3n.everifier.dto.EmailValidationResult;
import com.k3n.everifier.model.cache.EmailVerificationResultEntity;
import com.k3n.everifier.model.main.EmailEntity;
import com.k3n.everifier.repository.cache.emailverificationresultrepository;
import com.k3n.everifier.repository.main.emailrepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;
import java.util.stream.Collectors;

@Service
public class EmailCacheService {

    private static final long CACHE_TTL_DAYS = 30L;

    @Autowired
    private emailverificationresultrepository cacheRepository;

    @Autowired
    private emailrepository primaryRepository;

    @Autowired
    private MXLookupService mxLookupService;

    @Autowired
    private ObjectMapper objectMapper;

    /**
     * Fetch validation result from cache if not expired;
     * otherwise do fresh validation and cache the result.
     */
    public EmailValidationResult fetchValidationResult(String email) throws JsonProcessingException {
        LocalDateTime expiryThreshold = LocalDateTime.now().minusDays(CACHE_TTL_DAYS);
        Optional<EmailVerificationResultEntity> cachedOpt = cacheRepository.findByEmail(email);

        if (cachedOpt.isPresent()) {
            EmailVerificationResultEntity cached = cachedOpt.get();
            if (cached.getCachedAt().isAfter(expiryThreshold)) {
                // Serve from cache
                return objectMapper.readValue(cached.getVerificationResultJson(), EmailValidationResult.class);
            }
        }

        // Cache miss or expired, validate fresh and save cache
        EmailValidationResult result = mxLookupService.categorizeEmail(email);
        saveOrUpdateCache(email, result);
        return result;
    }

    /**
     * Save new or update existing cached entry for the given email.
     */
    private void saveOrUpdateCache(String email, EmailValidationResult result) throws JsonProcessingException {
        String json = objectMapper.writeValueAsString(result);
        LocalDateTime now = LocalDateTime.now();

        Optional<EmailVerificationResultEntity> cachedOpt = cacheRepository.findByEmail(email);
        EmailVerificationResultEntity entity;
        if (cachedOpt.isPresent()) {
            entity = cachedOpt.get();
            entity.setVerificationResultJson(json);
            entity.setCachedAt(now);
        } else {
            entity = new EmailVerificationResultEntity();
            entity.setEmail(email);
            entity.setVerificationResultJson(json);
            entity.setCachedAt(now);
        }
        cacheRepository.save(entity);
    }

    /**
     * Refresh cached entries that have expired based on TTL.
     * Also saves email in primary DB if not present.
     */
    public void refreshExpiredCacheEntries() throws JsonProcessingException {
        LocalDateTime expiryThreshold = LocalDateTime.now().minusDays(CACHE_TTL_DAYS);
        List<EmailVerificationResultEntity> expiredEntries = cacheRepository.findByCachedAtBefore(expiryThreshold);

        for (EmailVerificationResultEntity expired : expiredEntries) {
            String email = expired.getEmail();

            if (!primaryRepository.existsByEmail(email)) {
                EmailEntity primaryEntity = new EmailEntity();
                primaryEntity.setEmail(email);
                primaryRepository.save(primaryEntity);
            }

            EmailValidationResult newResult = mxLookupService.categorizeEmail(email);
            saveOrUpdateCache(email, newResult);
        }
    }

    /**
     * Fetch all cached results where category indicates valid email.
     */
    public List<EmailValidationResult> getAllValidCachedEmails() {
        List<EmailVerificationResultEntity> entities = cacheRepository.findAll();

        return entities.stream()
                .map(entity -> {
                    try {
                        return objectMapper.readValue(entity.getVerificationResultJson(), EmailValidationResult.class);
                    } catch (JsonProcessingException e) {
                        // Optional: log error
                        return null;
                    }
                })
                .filter(result -> result != null
                        && ("Valid".equalsIgnoreCase(result.getCategory()) || "Success".equalsIgnoreCase(result.getCategory())))
                .collect(Collectors.toList());
    }


    public List<EmailValidationResult> getCachedEmailsByCategory(String category) {
        List<EmailVerificationResultEntity> allCached = cacheRepository.findAll();

        return allCached.stream()
                .map(entity -> {
                    try {
                        return objectMapper.readValue(entity.getVerificationResultJson(), EmailValidationResult.class);
                    } catch (JsonProcessingException e) {
                        // Optionally log parse error
                        return null;
                    }
                })
                .filter(result -> result != null && category.equalsIgnoreCase(result.getCategory()))
                .collect(Collectors.toList());
    }
}
