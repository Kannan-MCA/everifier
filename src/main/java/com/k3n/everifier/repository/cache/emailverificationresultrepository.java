package com.k3n.everifier.repository.cache;

import com.k3n.everifier.model.cache.EmailVerificationResultEntity;
import org.springframework.data.jpa.repository.JpaRepository;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

public interface emailverificationresultrepository extends JpaRepository<EmailVerificationResultEntity, Long> {
    Optional<EmailVerificationResultEntity> findByEmail(String email);
    List<EmailVerificationResultEntity> findByCachedAtBefore(LocalDateTime expiryThreshold);


}
