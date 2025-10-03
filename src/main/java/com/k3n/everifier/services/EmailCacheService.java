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

@Service
public class EmailCacheService {

    private static final long CACHE_TTL_DAYS = 30L;

    @Autowired
    private emailverificationresultrepository cacheRepository;
    @Autowired private emailrepository primaryRepository;
    @Autowired private MXLookupService mxLookupService;
    @Autowired private ObjectMapper objectMapper;

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
}
